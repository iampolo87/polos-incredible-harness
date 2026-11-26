#!/usr/bin/env bash
# Export the shareable part of a Claude Code setup (~/.claude + MCP servers) into this repo.
# Safety model: allowlist copy -> rewrite machine paths -> private replacements -> scans that fail the run.
set -euo pipefail
cd "$(dirname "$0")"
SRC="${CLAUDE_HOME:-$HOME/.claude}"
CLAUDE_JSON="${CLAUDE_JSON:-$HOME/.claude.json}"

# Machine- and owner-specific knobs live in sync.local.sh (gitignored). See sync.local.example.sh.
EXCLUDES=()        # extra rsync --exclude=... rules, anchored at ~/.claude
MCP_SKIP='[]'      # JSON array of MCP server names to leave out
REPLACE=()         # sed -E expressions applied to every exported text file
PRIVATE_TERMS=''   # extended regex; any case-insensitive hit left in the export fails the run
# Fail closed: without it nothing private would be excluded, renamed or rejected.
[ -f sync.local.sh ] || { echo "sync: sync.local.sh missing (start from sync.local.example.sh). Refusing to export." >&2; exit 1; }
# shellcheck disable=SC1091
. ./sync.local.sh
[ -n "$PRIVATE_TERMS" ] || { echo "sync: PRIVATE_TERMS is empty. Refusing to export." >&2; exit 1; }
trap 'echo "sync: FAILED at line $LINENO. Nothing was published." >&2' ERR

# Everything is built in a staging directory and reaches the working tree only after the scans pass,
# so a failed run leaves nothing new to stage by accident.
D=.stage
rm -rf "$D"; mkdir -p "$D/claude"

# Never exported, wherever they sit: VCS data, caches, hidden files, logs, archives, retired code.
JUNK=(--exclude=.git/ --exclude=__pycache__/ --exclude=node_modules/ --exclude='.*' --exclude='*.log'
      --exclude='*.zip' --exclude=_archive/ --exclude=retired/)

# 1. Allowlist. Anything not named here (credentials, history, sessions, projects, caches, work state) is never copied.
#    First matching rule wins, so every exclude precedes the includes.
rsync -a --delete --delete-excluded --no-links --info=nonreg0 "${JUNK[@]}" "${EXCLUDES[@]}" \
  --exclude='/skills/synced/' \
  --include='/CLAUDE.md' --include='/settings.json' --include='/keybindings.json' --include='/policy.toml' \
  --include='/agents/***' --include='/bin/***' --include='/commands/***' --include='/hooks/***' \
  --include='/rulesets/***' --include='/skills/***' --include='/skill-packs/***' \
  --include='/output-styles/***' --include='/snippets/***' --include='/tools/***' \
  --include='/playbooks/***' --include='/patches/***' \
  --exclude='*' "$SRC/" "$D/claude/"

# 2. Top-level symlinks (nested ones are never followed). EXCLUDES apply to them too.
#    Target in a repo with a remote: listed in links.txt, not copied; left out entirely if it names something private.
#    No remote: vendor the real target with the same junk rules, or it is backed up nowhere.
: > "$D/links.txt"
(cd "$SRC" && { find agents commands hooks rulesets skills skill-packs -maxdepth 1 -type l 2>/dev/null || true; } | sort) |
while read -r link; do
  for e in "${EXCLUDES[@]}"; do p=${e#--exclude=}; [[ "/$link" == ${p%/} ]] && continue 2; done
  target=$(readlink -f "$SRC/$link")
  dir=$target; [ -d "$dir" ] || dir=$(dirname "$dir")
  remote=$(git -C "$dir" remote get-url origin 2>/dev/null | sed -E 's#//[^@/]*@#//#' || true)
  if [ -n "$remote" ]; then
    grep -qiE "$PRIVATE_TERMS" <<< "$link $remote" || echo "$link -> $remote" >> "$D/links.txt"
  else
    from=$target; to="$D/claude/$link"
    if [ -d "$target" ]; then from+=/; to+=/; fi
    rsync -a --delete --delete-excluded --no-links --info=nonreg0 "${JUNK[@]}" "$from" "$to"
  fi
done

# 3. MCP servers (user scope + every project scope, deduplicated by name) in .mcp.json shape.
#    env/header values become ${NAME} references; URL credentials, query strings and token-like
#    path segments are dropped; the value of any --*token/key/secret/password* argument becomes ${ARG}.
jq -S --argjson skip "$MCP_SKIP" '
  def ref: "${" + (ascii_upcase | gsub("[^A-Z0-9_]"; "_")) + "}";
  def scrub_args: [foreach .[] as $a ({prev: ""}; {prev: $a, out: (
      if (.prev | test("^-.*(token|key|secret|passw|auth|header|tenant|account|org)"; "i")) and ($a | startswith("-") | not) then "${ARG}"
      else ($a | sub("(?<k>^-[^=]*(token|key|secret|passw|auth|header|tenant|account|org)[^=]*=).*"; "\(.k)${ARG}"; "i")) end)}; .out)];
  [(.projects[] | .mcpServers // {}), (.mcpServers // {})] | add | del(.[$skip[]])
  | map_values(
      (if .env then .env |= with_entries(.value = (.key | ref)) else . end)
      | (if .headers then .headers |= with_entries(.value = (.key | ref)) else . end)
      | (if .args then .args |= scrub_args else . end)
      | (if .url then .url |= (sub("\\?.*$"; "") | sub("#.*$"; "") | sub("//[^@/]*@"; "//") | gsub("/[A-Za-z0-9_-]{24,}(?=/|$)"; "/${TOKEN}")) else . end)
    )
  | {mcpServers: .}' "$CLAUDE_JSON" > "$D/mcp.json"

# 4. Plugins: marketplaces and installed versions only (enabled/disabled state is in claude/settings.json).
jq -S -n --slurpfile i "$SRC/plugins/installed_plugins.json" --slurpfile m "$SRC/plugins/known_marketplaces.json" \
  '{marketplaces: ($m[0] | map_values(.source)), plugins: ($i[0].plugins | map_values(.[0].version))}' > "$D/plugins.json"

# 5. Portability and privacy rewrites: home directory -> ${HOME} (shell and .mcp.json both expand it), then REPLACE.
SED=(-e "s#$HOME#\${HOME}#g")
for r in "${REPLACE[@]}"; do SED+=(-e "$r"); done
grep -rIlZ . "$D" | xargs -0 sed -E -i "${SED[@]}"
# A single-quoted '${HOME}/...' would not expand in a hook command: requote it.
jq --arg q "'" 'walk(if type == "string" then gsub($q + "(?<p>\\$\\{HOME\\}[^ " + $q + "]*)" + $q; "\"\(.p)\"") else . end)' \
  "$D/claude/settings.json" > "$D/settings.tmp" && mv "$D/settings.tmp" "$D/claude/settings.json"

# 6. Scans. Only file:line is printed, never the matching text. A hit means: fix or exclude the source.
SECRETS='(api[_-]?key|secret|token|passw(or)?d|authorization)[a-z0-9_]*["'"'"']?[[:space:]]*[=:][[:space:]]*["'"'"']?[a-z0-9_.+-]{20,}'
SECRETS+='|(bearer|--(token|api-key|password))[[:space:]=]+[a-z0-9_.+-]{16,}'
SECRETS+='|NR(AK|II|AL)-[a-z0-9]{20,}|glpat-[a-z0-9_-]{20,}|gh[pousr]_[a-z0-9]{30,}|sk-[a-z0-9_-]{20,}'
SECRETS+='|xox[bpas]-[a-z0-9-]{10,}|AKIA[0-9a-z]{16}|-----BEGIN [a-z ]*PRIVATE KEY|://[^/@[:space:]]+:[^/@[:space:]]+@'
OUT=("$D")
fail=0
# Binary files dodge both the rewrites and the scans: refuse them.
hits=$(find "${OUT[@]}" -type f -size +0 -print0 | xargs -0 grep -IL . || true)
if [ -n "$hits" ]; then echo "sync: non-text file (exclude it or publish it by hand):" >&2; echo "$hits" >&2; fail=1; fi
hits=$(grep -rniaE "$SECRETS" "${OUT[@]}" | cut -d: -f1,2 | sort -u || true)
if [ -n "$hits" ]; then echo "sync: possible secret at:" >&2; echo "$hits" >&2; fail=1; fi
if [ -n "$PRIVATE_TERMS" ]; then
  hits=$( { grep -rniaE "$PRIVATE_TERMS" "${OUT[@]}" | cut -d: -f1,2; find "$D" | grep -iE "$PRIVATE_TERMS"; } | sort -u || true)
  if [ -n "$hits" ]; then echo "sync: private term left at:" >&2; echo "$hits" >&2; fail=1; fi
fi
[ "$fail" -eq 0 ] || { echo "sync: FAILED. Nothing was published; the rejected export is in $D/." >&2; exit 1; }

# 7. Publish the staged export.
rsync -a --delete "$D/claude/" claude/
mv "$D/mcp.json" "$D/plugins.json" "$D/links.txt" .
rm -rf "$D"
echo "sync: ok ($(find claude mcp.json plugins.json links.txt -type f | wc -l) files, $(du -sh claude | cut -f1))"
