#!/usr/bin/env bash
# Re-apply global opsx overrides to project-local OpenSpec files. Idempotent; re-run after `openspec update`.
#   apply   -> stub routing to the global opsx-apply skill (tiered implementers)
#   propose/explore -> prepend "recon via opsx-recon (Haiku Explore)" rule
#   propose -> prepend "implement-continues" rule (marker opsx-patch:implement-continues, 2026-09-29)
#   propose/explore -> soften the older recon header wording in place (2026-09-29)
# Originals backed up once to ~/.claude/backups/opsx-patch/<project>/...
set -euo pipefail
MARK='opsx-patch'
MARK2='opsx-patch:implement-continues'
BK=$HOME/.claude/backups/opsx-patch
root=${1:-$HOME/projects}

backup() { local rel=${1#"$root"/}; mkdir -p "$BK/$(dirname "$rel")"; [ -e "$BK/$rel" ] || cp "$1" "$BK/$rel"; }

stub() { # file, new description
  local f=$1; [ -f "$f" ] || return 0; grep -q "$MARK" "$f" && return 0; backup "$f"
  { awk -v d="$2" 'NR==1{print;next} !done{ if(/^description:/){print "description: \"" d "\""; next} print; if(/^---$/)done=1 }' "$f"
    printf '\n<!-- %s: stub; re-run ~/.claude/tools/opsx-patch.sh after `openspec update` -->\n' "$MARK"
    printf 'Invoke the `opsx-apply` skill (Skill tool) and follow it, passing along the change name or request ($ARGUMENTS).\n'
    printf 'Do not run the upstream OpenSpec apply loop.\n'
  } > "$f.tmp" && mv "$f.tmp" "$f"; echo "stub   $f"; }

prepend() { # file
  local f=$1; [ -f "$f" ] || return 0; grep -q "$MARK" "$f" && return 0; backup "$f"
  awk -v m="$MARK" 'NR==1{print;next} !done && /^---$/{print; print ""; print "<!-- " m " -->";
    print "**Recon (global override):** for context-heavy sweeps of the application code (many files, unknown entry points, naming conventions) invoke the `opsx-recon` skill; targeted reads of files you already know stay inline, as do OpenSpec CLI calls and reading `openspec/` artifacts."; done=1; next} {print}' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
  echo "recon  $f"; }

continues() { # file — routed propose keeps the user's implementation authorization
  local f=$1; [ -f "$f" ] || return 0; grep -q "$MARK2" "$f" && return 0; backup "$f"
  awk -v m="$MARK2" 'NR==1{print;next} !done && /^---$/{print; print ""; print "<!-- " m " -->";
    print "**Implementation authorization (global override):** the **Planning boundary** paragraph and the Guardrails bullet saying an implementation instruction does not carry forward apply when the user invoked this workflow themselves or asked only for a proposal. When routing (`~/.claude/rulesets/core/routing.md`) chose this step for a request that already asked to implement, build or fix, that authorization does carry forward: after the artifacts validate, continue to the `opsx-apply` skill in the same session instead of waiting for a new request."; done=1; next} {print}' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
  echo "cont   $f"; }

soften() { # file — reword the 2026-09-26 recon header in already-patched files (no-op once done)
  local f=$1; [ -f "$f" ] || return 0; grep -qF 'instead of reading or grepping that code in this thread' "$f" || return 0; backup "$f"
  python3 - "$f" <<'PY'
import sys; f=sys.argv[1]; s=open(f).read()
s=s.replace("**Recon first (global override):** whenever this workflow needs facts from the application code, invoke the `opsx-recon` skill instead of reading or grepping that code in this thread. OpenSpec CLI calls and reading `openspec/` artifacts stay inline.",
"**Recon (global override):** for context-heavy sweeps of the application code (many files, unknown entry points, naming conventions) invoke the `opsx-recon` skill; targeted reads of files you already know stay inline, as do OpenSpec CLI calls and reading `openspec/` artifacts.")
open(f,"w").write(s)
PY
  echo "soften $f"; }

for p in "$root"/*/; do
  c=${p}.claude/commands/opsx s=${p}.claude/skills
  stub "$c/apply.md" "Implement an OpenSpec change (routed to the global opsx-apply skill)"
  stub "$s/openspec-apply-change/SKILL.md" "Superseded by the global opsx-apply skill. Use opsx-apply to implement OpenSpec change tasks."
  for f in "$c/propose.md" "$c/explore.md" "$s/openspec-propose/SKILL.md" "$s/openspec-explore/SKILL.md"; do prepend "$f"; done
  for f in "$c/propose.md" "$s/openspec-propose/SKILL.md"; do continues "$f"; done
  for f in "$c/propose.md" "$c/explore.md" "$s/openspec-propose/SKILL.md" "$s/openspec-explore/SKILL.md"; do soften "$f"; done
done
