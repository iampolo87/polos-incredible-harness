#!/usr/bin/env bash
# ponytail-ab.sh — cheap local A/B: same task, baseline vs ponytail, measure LOC + tokens + cost.
#
# Clean isolation: runs claude headless under a temp CLAUDE_CONFIG_DIR (only creds symlinked),
# so the global ~/.claude/CLAUDE.md ponytail ladder loads in NEITHER arm. The ONLY variable is
# the ponytail ruleset, appended to the treatment arm via --append-system-prompt.
#
#   baseline arm:  claude -p "<task>"
#   ponytail arm:  claude -p --append-system-prompt "$(cat ruleset)" "<task>"
#
# Usage:
#   ponytail-ab.sh                       # default 5 tasks (mirrors repo bench)
#   ponytail-ab.sh "task one" "task two" # custom tasks
#   MODEL=claude-sonnet-4-6 REPEAT=3 ponytail-ab.sh
#
# Env: MODEL (default haiku, cheapest), REPEAT (default 1), RULESET (default ponytail.md).
set -euo pipefail

MODEL="${MODEL:-claude-haiku-4-5-20251001}"
REPEAT="${REPEAT:-1}"
RULESET="${RULESET:-$HOME/.claude/rulesets/core/ponytail.md}"
CREDS="$HOME/.claude/.credentials.json"

[ -f "$RULESET" ] || { echo "ruleset not found: $RULESET" >&2; exit 1; }
[ -f "$CREDS" ]   || { echo "creds not found: $CREDS (need file-based auth for isolation)" >&2; exit 1; }
command -v claude >/dev/null || { echo "claude CLI not on PATH" >&2; exit 1; }

# default task set — same shape as benchmarks/promptfooconfig.yaml
if [ "$#" -gt 0 ]; then
  TASKS=("$@")
else
  TASKS=(
    "Write a Python function that validates an email address."
    "Add debounce to a search input that currently fires an API call on every keystroke (JS)."
    "Write Python to read sales.csv and sum the amount column."
    "Write a React countdown timer component that counts down from N seconds."
    "Add a rate limiter to a FastAPI endpoint."
  )
fi

AB="$(mktemp -d /tmp/ponytail-ab.XXXXXX)"
ln -s "$CREDS" "$AB/.credentials.json"
RESULTS="$AB/results.tsv"
: > "$RESULTS"
trap 'rm -rf "$AB"' EXIT

PONY_PROMPT="$(cat "$RULESET")"

# parser: stdin=claude JSON, argv=idx arm -> "idx\tarm\tloc\ttok\tcost" (nothing on failure)
cat > "$AB/parse.py" <<'PY'
import sys, json
idx, arm = sys.argv[1], sys.argv[2]
try:
    d = json.loads(sys.stdin.read())
except Exception:
    sys.exit(0)
if d.get("is_error"):
    sys.exit(0)
text = str(d.get("result", ""))
loc, inb = 0, False
for line in text.splitlines():
    if line.strip().startswith("```"):
        inb = not inb
        continue
    if inb and line.strip():
        loc += 1
tok  = d.get("usage", {}).get("output_tokens", 0)
cost = d.get("total_cost_usd", 0.0)
print(f"{idx}\t{arm}\t{loc}\t{tok}\t{cost}")
PY

cat > "$AB/tab.py" <<'PY'
import sys
from collections import defaultdict
results_path, ntasks = sys.argv[1], int(sys.argv[2])
agg = defaultdict(lambda: defaultdict(list))
with open(results_path) as f:
    for ln in f:
        p = ln.rstrip("\n").split("\t")
        if len(p) != 5:
            continue
        idx, arm, loc, tok, cost = p
        agg[int(idx)][arm].append((int(loc), int(tok), float(cost)))

def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0

def pct(b, p):
    return f"{(b - p) / b * 100:5.0f}%" if b else "   - "

print()
print(f"{'task':<5}{'baseLOC':>8}{'ponyLOC':>8}{'LOC-':>6}{'baseTok':>9}{'ponyTok':>9}{'tok-':>6}{'base$':>9}{'pony$':>9}")
print("-" * 69)
tot = {k: [0.0, 0.0] for k in ("loc", "tok", "cost")}
for idx in range(ntasks):
    b, p = agg[idx].get("base", []), agg[idx].get("pony", [])
    if not b or not p:
        print(f"{idx+1:<5}  (run failed / no data)")
        continue
    bl, pl = mean([x[0] for x in b]), mean([x[0] for x in p])
    bt, pt = mean([x[1] for x in b]), mean([x[1] for x in p])
    bc, pc = mean([x[2] for x in b]), mean([x[2] for x in p])
    for k, (bb, pp) in (("loc", (bl, pl)), ("tok", (bt, pt)), ("cost", (bc, pc))):
        tot[k][0] += bb; tot[k][1] += pp
    print(f"{idx+1:<5}{bl:>8.0f}{pl:>8.0f}{pct(bl,pl):>6}{bt:>9.0f}{pt:>9.0f}{pct(bt,pt):>6}{bc:>9.4f}{pc:>9.4f}")

print("-" * 69)
L, T, C = tot["loc"], tot["tok"], tot["cost"]
print(f"{'TOTAL':<5}{L[0]:>8.0f}{L[1]:>8.0f}{pct(L[0],L[1]):>6}{T[0]:>9.0f}{T[1]:>9.0f}{pct(T[0],T[1]):>6}{C[0]:>9.4f}{C[1]:>9.4f}")
print()
print(f"ponytail saved: LOC {pct(L[0],L[1]).strip()}  tokens {pct(T[0],T[1]).strip()}  cost {pct(C[0],C[1]).strip()}")
PY

run_arm() { # task arm idx
  local task="$1" arm="$2" idx="$3" json
  if [ "$arm" = pony ]; then
    json="$(CLAUDE_CONFIG_DIR="$AB" claude -p --model "$MODEL" \
      --append-system-prompt "$PONY_PROMPT" --output-format json "$task" 2>/dev/null || true)"
  else
    json="$(CLAUDE_CONFIG_DIR="$AB" claude -p --model "$MODEL" \
      --output-format json "$task" 2>/dev/null || true)"
  fi
  printf '%s' "$json" | python3 "$AB/parse.py" "$idx" "$arm" >> "$RESULTS"
}

echo "model=$MODEL  repeat=$REPEAT  tasks=${#TASKS[@]}  (isolated config)"
i=0
for task in "${TASKS[@]}"; do
  printf 'task %d/%d: %.55s\n' "$((i+1))" "${#TASKS[@]}" "$task" >&2
  for r in $(seq 1 "$REPEAT"); do
    run_arm "$task" base "$i"
    run_arm "$task" pony "$i"
  done
  i=$((i+1))
done

python3 "$AB/tab.py" "$RESULTS" "${#TASKS[@]}"
