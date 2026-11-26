#!/usr/bin/env bash
# Orchestrate the full m2-cloud-audit for a Magento 2 Cloud project.
# Read-only: produces a report + intermediate JSONs; mutates nothing in the project.
#
# Usage:
#   run-audit.sh --project /path/to/project [--name NAME] [--out DIR] [--date YYYY-MM-DD]
#
# NEVER calls `vendor/bin/magento-patches` (it segfaults in some envs); patch
# enumeration goes through match-patches.php + composer/semver instead.
set -euo pipefail

SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REFS="$(cd "$SCRIPTS/.." && pwd)/references"

PROJECT="$PWD"; NAME=""; OUT=""; DATE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --project) PROJECT="$2"; shift 2;;
    --name)    NAME="$2"; shift 2;;
    --out)     OUT="$2"; shift 2;;
    --date)    DATE="$2"; shift 2;;
    *) echo "unknown arg: $1" >&2; exit 2;;
  esac
done
PROJECT="$(cd "$PROJECT" && pwd)"
[ -n "$NAME" ] || NAME="$(basename "$PROJECT")"
[ -n "$DATE" ] || DATE="$(date +%F)"
[ -n "$OUT" ]  || OUT="$PROJECT/docs/cloud-audit/$DATE"
mkdir -p "$OUT"

log(){ echo "[m2-cloud-audit] $*" >&2; }

# ── prerequisites ────────────────────────────────────────────────────────────
command -v php >/dev/null     || { echo "php CLI required" >&2; exit 1; }
command -v python3 >/dev/null  || { echo "python3 required" >&2; exit 1; }
[ -f "$PROJECT/composer.lock" ] || { echo "composer.lock not found in $PROJECT" >&2; exit 1; }

LOCK="$PROJECT/composer.lock"
QP="$PROJECT/vendor/magento/quality-patches"
SERVICES="$PROJECT/.magento/services.yaml"
ENVYAML="$PROJECT/.magento.env.yaml"
APPYAML="$PROJECT/.magento.app.yaml"
COMPOSER="$PROJECT/composer.json"
HOTFIXES="$PROJECT/m2-hotfixes"
ENVPHP="$PROJECT/app/etc/env.php"
IS_CLOUD=1; [ -f "$SERVICES" ] || IS_CLOUD=0

# ── 1. patch matcher (PHP + composer/semver) ─────────────────────────────────
if [ -f "$QP/support-patches.json" ]; then
  log "matching quality patches against composer.lock ..."
  php "$SCRIPTS/match-patches.php" \
      --lock "$LOCK" \
      --catalog "$QP/support-patches.json" \
      --community "$QP/community-patches.json" \
      > "$OUT/matched-patches.json"
else
  log "magento/quality-patches not installed — skipping patch section"
  echo '{"applicable":[],"errors":[],"project_version":null,"edition":null}' > "$OUT/matched-patches.json"
fi

# ── 2. applied set + 3. patch gaps ───────────────────────────────────────────
log "collecting declared-applied set ..."
python3 "$SCRIPTS/collect-applied-set.py" \
    ${ENVYAML:+--env-yaml "$ENVYAML"} \
    ${COMPOSER:+--composer-json "$COMPOSER"} \
    ${HOTFIXES:+--hotfixes-dir "$HOTFIXES"} \
    > "$OUT/applied-set.json"

python3 "$SCRIPTS/parse-patch-gaps.py" \
    --matched "$OUT/matched-patches.json" \
    --applied "$OUT/applied-set.json" \
    > "$OUT/patch-gaps.json"

# ── 4. env.php dump (only if non-stub) ───────────────────────────────────────
ENVPHP_ARG=()
if [ -f "$ENVPHP" ] && [ "$(wc -c < "$ENVPHP")" -gt 1500 ]; then
  log "dumping app/etc/env.php ..."
  if php "$SCRIPTS/dump-envphp.php" "$ENVPHP" > "$OUT/envphp.json" 2>/dev/null; then
    ENVPHP_ARG=(--envphp-json "$OUT/envphp.json")
  fi
else
  log "env.php absent or a Cloud stub — env.php settings reported as deferred"
fi

# ── 5. config gaps ───────────────────────────────────────────────────────────
PHPINI=""
[ -f "$PROJECT/php.ini" ] && PHPINI="$PROJECT/php.ini"
[ -z "$PHPINI" ] && [ -f "$PROJECT/.user.ini" ] && PHPINI="$PROJECT/.user.ini"

log "auditing configuration recommendations ..."
python3 "$SCRIPTS/parse-config-gaps.py" \
    --catalog "$REFS/config-recommendations.json" \
    ${SERVICES:+--services "$SERVICES"} \
    ${ENVYAML:+--env-yaml "$ENVYAML"} \
    ${PHPINI:+--php-ini "$PHPINI"} \
    "${ENVPHP_ARG[@]}" \
    > "$OUT/config-gaps.json"

# ── 6. service versions ──────────────────────────────────────────────────────
log "checking service versions ..."
python3 "$SCRIPTS/parse-service-versions.py" \
    --services "$SERVICES" \
    --eol "$REFS/service-eol.json" \
    ${APPYAML:+--app "$APPYAML"} \
    --as-of "$DATE" \
    > "$OUT/service-gaps.json" \
  || { log "WARN: service-version check failed — section will be empty"; \
       echo '{"counts":{"eol":0,"below_recommended":0,"ok":0,"unknown":0},"findings":[]}' > "$OUT/service-gaps.json"; }

# ── 7. merge + 8. render ─────────────────────────────────────────────────────
log "merging + rendering report ..."
CLOUD_FLAG=(); [ "$IS_CLOUD" -eq 0 ] && CLOUD_FLAG=(--no-cloud)
python3 "$SCRIPTS/build-audit-input.py" \
    --patch-gaps "$OUT/patch-gaps.json" \
    --config-gaps "$OUT/config-gaps.json" \
    --service-gaps "$OUT/service-gaps.json" \
    --project-name "$NAME" --date "$DATE" "${CLOUD_FLAG[@]}" \
    > "$OUT/audit-input.json"

python3 "$SCRIPTS/render-audit.py" \
    --input "$OUT/audit-input.json" \
    --template "$(cd "$SCRIPTS/.." && pwd)/templates/audit-report.html" \
    --output "$OUT/audit.html"

log "done → $OUT/audit.html"
echo "$OUT/audit.html"
