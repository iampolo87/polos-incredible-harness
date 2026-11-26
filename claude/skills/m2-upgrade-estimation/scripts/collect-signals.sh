#!/usr/bin/env bash
#
# Collect measured upgrade signals into <report-dir>/signals.json.
#
# Runs the automation tools that quantify upgrade effort and merges their counts
# with the core-diff inventory and the (owner-aware) custom-code impact summary.
# Every tool is OPTIONAL: a missing binary zero-fills its section + warns.
#
# Also measures a PHP version LADDER via Rector version-set change counts at each
# target PHP level (default: target, +1 minor, +2 minor) so the estimate can show
# the marginal cost of going further on PHP.
#
# Prerequisites (produced by earlier phases):
#   <report-dir>/raw/modules-changed.txt    (diff.sh)
#   <report-dir>/raw/magento.diff           (diff.sh)
#   <report-dir>/extension-impact-deep.json (extension-impact-deep.py)  [optional]
#
# Usage:
#   collect-signals.sh --report-dir DIR --app-code DIR \
#     --current-version X --target-version Y --current-php 8.1 --target-php 8.3 \
#     --edition enterprise [--vendor-bin DIR] [--rector-config FILE] [--uct-bin PATH] \
#     [--ext-conflicts N] [--php-ladder 8.3,8.4,8.5] [--phpstan-baseline N]
#
# --phpstan-baseline N: PHPStan error count on the CURRENT version (run PHPStan
#   on the un-upgraded checkout). Without it, PHPStan errors are surfaced but contribute
#   0 effort hours (raw count conflates pre-existing debt with upgrade-introduced breakage).
#
set -uo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPTS="$SKILL_DIR/scripts"

REPORT_DIR=""; APP_CODE="./app/code"
CUR_VER="?"; TGT_VER="?"; CUR_PHP="?"; TGT_PHP="?"; EDITION="?"
VENDOR_BIN="./vendor/bin"
RECTOR_CONFIG="$SKILL_DIR/references/rector.php"
UCT_BIN=""; EXT_CONFLICTS=0; PHP_LADDER=""; PS_BASELINE=""; PHPCOMPAT_VIOL=0
# Maintained-commercial vendors that ship target-compatible releases — EXCLUDED
# from migration counts (rector/UCT). Everything else in app/code (client code AND
# orphaned/agency modules with no maintained release) IS counted as migration work.
THIRD_PARTY_VENDORS="amasty,weltpixel,mirasvit,mageworx,mageplaza,webkul,aheadworks,bss,bsscommerce,magezon,magictoolbox,magiczoom,klevu"

while [ $# -gt 0 ]; do
  case "$1" in
    --report-dir) REPORT_DIR="$2"; shift 2;;
    --app-code) APP_CODE="$2"; shift 2;;
    --current-version) CUR_VER="$2"; shift 2;;
    --target-version) TGT_VER="$2"; shift 2;;
    --current-php) CUR_PHP="$2"; shift 2;;
    --target-php) TGT_PHP="$2"; shift 2;;
    --edition) EDITION="$2"; shift 2;;
    --vendor-bin) VENDOR_BIN="$2"; shift 2;;
    --rector-config) RECTOR_CONFIG="$2"; shift 2;;
    --uct-bin) UCT_BIN="$2"; shift 2;;
    --ext-conflicts) EXT_CONFLICTS="$2"; shift 2;;
    --php-ladder) PHP_LADDER="$2"; shift 2;;
    --phpstan-baseline) PS_BASELINE="$2"; shift 2;;
    --phpcompat-violations) PHPCOMPAT_VIOL="$2"; shift 2;;
    --third-party-vendors) THIRD_PARTY_VENDORS="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done
[ -n "$REPORT_DIR" ] || { echo "ERROR: --report-dir required" >&2; exit 2; }
RAW="$REPORT_DIR/raw"; mkdir -p "$RAW"
RECTOR_PHP="${TGT_PHP//./}"
[ -n "$PHP_LADDER" ] || PHP_LADDER="$TGT_PHP,8.4,8.5"

have() { [ -x "$VENDOR_BIN/$1" ] || [ -f "$VENDOR_BIN/$1" ]; }

# --- core diff inventory -----------------------------------------------------
MODULES_CHANGED=0; DIFF_LINES=0
[ -f "$RAW/modules-changed.txt" ] && MODULES_CHANGED=$(grep -c . "$RAW/modules-changed.txt" 2>/dev/null || echo 0)
[ -f "$RAW/magento.diff" ] && DIFF_LINES=$(wc -l < "$RAW/magento.diff" 2>/dev/null || echo 0)

# --- Rector (dry-run, json) --------------------------------------------------
RECTOR_PARSED="$RAW/signals-rector.json"
if have rector; then
  echo "[rector] dry-run (RECTOR_PHP_VERSION=$RECTOR_PHP) ..."
  RECTOR_PHP_VERSION="$RECTOR_PHP" "$VENDOR_BIN/rector" process "$APP_CODE" \
    --dry-run --no-progress-bar --output-format=json --config="$RECTOR_CONFIG" \
    > "$RAW/rector-dryrun.json" 2>/dev/null || true
  python3 "$SCRIPTS/parse-rector.py" --input "$RAW/rector-dryrun.json" --exclude-vendors "$THIRD_PARTY_VENDORS" --out "$RECTOR_PARSED" >/dev/null 2>&1 \
    || echo '{"files_changed":0,"by_ruleset":{"PHP_LEVEL":0,"CODE_QUALITY":0,"DEAD_CODE":0,"TYPE_DECLARATION":0,"OTHER":0}}' > "$RECTOR_PARSED"
else
  echo "[rector] WARN: not found — zero-filling"
  echo '{"files_changed":0,"by_ruleset":{"PHP_LEVEL":0,"CODE_QUALITY":0,"DEAD_CODE":0,"TYPE_DECLARATION":0,"OTHER":0}}' > "$RECTOR_PARSED"
fi

# --- PHP-version analysis: Rector (above) is the primary signal --------------
# PHPCompatibility-stable (9.x) predates PHP 8.3+ so it is no longer run. If you
# have a detector that covers the target PHP, pass its violation count via
# --phpcompat-violations N; otherwise the PHP-compat phase falls back to Rector's
# PHP_LEVEL count (build-pert-input.py).
PHPCOMPAT="$PHPCOMPAT_VIOL"

# --- PHPStan -----------------------------------------------------------------
PHPSTAN=0
if have phpstan; then
  echo "[phpstan] analyse ..."
  "$VENDOR_BIN/phpstan" analyse "$APP_CODE" --error-format=json --no-progress > "$RAW/phpstan.json" 2>/dev/null || true
  PHPSTAN=$(python3 -c "import json;print(json.load(open('$RAW/phpstan.json')).get('totals',{}).get('file_errors',0))" 2>/dev/null || echo 0)
else
  echo "[phpstan] WARN: not found — zero-filling"
fi

# --- Adobe UCT (EE only) -----------------------------------------------------
UCT_PARSED="$RAW/signals-uct.json"
[ -z "$UCT_BIN" ] && { [ -f "./bin/uct" ] && UCT_BIN="./bin/uct"; }
if [ -n "$UCT_BIN" ] && [ -f "$UCT_BIN" ]; then
  echo "[uct] upgrade:check $CUR_VER -> $TGT_VER ..."
  php "$UCT_BIN" upgrade:check --current-version="$CUR_VER" --coming-version="$TGT_VER" \
    --format=json "$APP_CODE" > "$RAW/uct-report.json" 2>/dev/null || true
  UCT_AUTOFIX=$(php "$UCT_BIN" refactor --dry-run "$APP_CODE" 2>/dev/null | grep -c -E 'would (be )?refactor|FIXED' || echo 0)
  python3 "$SCRIPTS/parse-uct.py" --input "$RAW/uct-report.json" --autofix "$UCT_AUTOFIX" --exclude-vendors "$THIRD_PARTY_VENDORS" --out "$UCT_PARSED" >/dev/null 2>&1 \
    || echo '{"findings":0,"autofix":0,"by_severity":{"critical":0,"error":0,"warning":0}}' > "$UCT_PARSED"
else
  echo "[uct] WARN: UCT binary not found (EE-only tool) — zero-filling"
  echo '{"findings":0,"autofix":0,"by_severity":{"critical":0,"error":0,"warning":0}}' > "$UCT_PARSED"
fi

# --- PHP ladder (Rector version-set change counts per level) -----------------
# PHPCompatibility-stable (9.x) predates PHP 8.3+, so it can't tell 8.3/8.4/8.5
# apart. Rector's UP_TO_PHP_* sets DO know modern PHP, so we count Rector PHP_LEVEL
# changes per level. Levels above Rector's highest known set (RECTOR_MAX_LEVEL,
# default 84 for rector 1.x) are reported "no medible" — never silently zero.
echo "[php-ladder] $PHP_LADDER (via rector) ..."
LADDER_FILE="$RAW/php-ladder.json"
RECTOR_MAX="${RECTOR_MAX_LEVEL:-84}"
LADDER_ENTRIES=""
IFS=',' read -ra LEVELS <<< "$PHP_LADDER"
for lvl in "${LEVELS[@]}"; do
  lvl="$(printf '%s' "$lvl" | tr -d ' ')"; nodot="${lvl//./}"
  changes=0; meas=false
  if have rector && [ "${nodot:-0}" -le "$RECTOR_MAX" ] 2>/dev/null; then
    RECTOR_PHP_VERSION="$nodot" "$VENDOR_BIN/rector" process "$APP_CODE" \
      --dry-run --no-progress-bar --output-format=json --config="$RECTOR_CONFIG" \
      > "$RAW/rector-ladder-$nodot.json" 2>/dev/null || true
    changes=$(python3 "$SCRIPTS/parse-rector.py" --input "$RAW/rector-ladder-$nodot.json" --exclude-vendors "$THIRD_PARTY_VENDORS" 2>/dev/null \
              | python3 -c "import json,sys;print(json.load(sys.stdin)['by_ruleset'].get('PHP_LEVEL',0))" 2>/dev/null || echo 0)
    meas=true
  fi
  LADDER_ENTRIES="${LADDER_ENTRIES}{\"php\":\"$lvl\",\"phpcompat\":${changes:-0},\"rector_autofix\":${changes:-0},\"measurable\":$meas},"
done
LADDER_ENTRIES="[${LADDER_ENTRIES%,}]"
printf '%s' "$LADDER_ENTRIES" > "$LADDER_FILE"

# --- merge into signals.json -------------------------------------------------
OUT="$REPORT_DIR/signals.json"
IMPACT_JSON="$REPORT_DIR/extension-impact-deep.json"
[ -f "$IMPACT_JSON" ] || IMPACT_JSON=""

python3 - "$OUT" "$RECTOR_PARSED" "$UCT_PARSED" "$IMPACT_JSON" "$LADDER_FILE" <<PY
import json, sys
out, rector_f, uct_f, impact_f, ladder_f = sys.argv[1:6]

def load(p, default):
    try:
        return json.load(open(p))
    except Exception:
        return default

rector = load(rector_f, {"files_changed":0,"by_ruleset":{}})
uct = load(uct_f, {"findings":0,"autofix":0,"by_severity":{}})

# owner-aware custom impact from the scanner's nested summary
ci = {"preference":0,"plugin":0,"extends":0,"implements":0,"virtualType":0,
      "template":0,"layout":0,"extends_signature_risk":0,"overlap_modules":0,"third_party_vendors":0}
if impact_f:
    s = load(impact_f, {}).get("summary", {})
    cust = s.get("custom", {})
    for k in ("preference","plugin","extends","implements","virtualType","template","layout"):
        ci[k] = cust.get(k, 0)
    ci["extends_signature_risk"] = s.get("extends_signature_risk", 0)
    ci["overlap_modules"] = s.get("overlap_modules", 0)
    # per-vendor verify cost → use distinct vendor COUNT, not finding count
    ci["third_party_vendors"] = len(s.get("third_party", {}).get("vendors", []))
    ci["third_party_findings"] = s.get("third_party", {}).get("count", 0)

ladder = load(ladder_f, [])

signals = {
    "meta": {
        "current_version": "$CUR_VER", "target_version": "$TGT_VER",
        "current_php": "$CUR_PHP", "target_php": "$TGT_PHP", "edition": "$EDITION",
    },
    "core_diff": {"modules_changed": $MODULES_CHANGED, "diff_lines": $DIFF_LINES},
    "custom_impact": ci,
    "rector": rector,
    "phpcompat": {"violations": ${PHPCOMPAT:-0}},
    "phpstan": {"errors": ${PHPSTAN:-0}, "baseline_errors": ${PS_BASELINE:-None}},
    "uct": uct,
    "composer": {"extension_conflicts": $EXT_CONFLICTS},
    "php_ladder": ladder,
}
open(out, "w").write(json.dumps(signals, indent=2, ensure_ascii=False))
print(f"[signals] {out}")
PY
