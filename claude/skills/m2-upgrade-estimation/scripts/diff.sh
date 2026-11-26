#!/usr/bin/env bash
# Phase 3 — Generate raw + filtered diffs between snapshot and current vendor.
# Usage: diff.sh <snapshot-dir> <report-dir>
# Example: diff.sh /tmp/magento-snapshot-2.4.7-p9 docs/upgrades/2.4.7-p9-to-2.4.7-p10
set -euo pipefail

SNAPSHOT_DIR="${1:?snapshot-dir required}"
REPORT_DIR="${2:?report-dir required}"

mkdir -p "$REPORT_DIR/raw"

# Full diffs
diff -ruN "$SNAPSHOT_DIR/magento" vendor/magento > "$REPORT_DIR/raw/magento.diff" || true
if [ -d "$SNAPSHOT_DIR/laminas" ] && [ -d vendor/laminas ]; then
  diff -ruN "$SNAPSHOT_DIR/laminas" vendor/laminas > "$REPORT_DIR/raw/laminas.diff" || true
fi
diff -u "$SNAPSHOT_DIR/composer.lock" composer.lock > "$REPORT_DIR/raw/composer-lock.diff" || true

# Logic-only diff (ignore copyright headers and whitespace)
diff -ruN \
  -I '^\s*\*' \
  -I 'Copyright' \
  -I '^\s*$' \
  -b \
  "$SNAPSHOT_DIR/magento" vendor/magento \
  > "$REPORT_DIR/raw/magento.logic.diff" || true

# Closed list of modified Magento modules.
# `diff -ruN` emits `diff -ruN <snap>/magento/<mod>/... vendor/magento/<mod>/...`
# headers plus `Only in <dir>/magento/<mod>: file` for added/removed files.
# Extract the module segment (vendor/magento/<mod>) from both forms.
{
  grep -E '^diff -ruN ' "$REPORT_DIR/raw/magento.diff" 2>/dev/null \
    | grep -oE 'vendor/magento/[^/ ]+'
  grep -E '^Only in .*/magento/' "$REPORT_DIR/raw/magento.diff" 2>/dev/null \
    | grep -oE 'magento/[^/:]+' | sed -E 's|^magento/|vendor/magento/|'
} | sort -u > "$REPORT_DIR/raw/modules-changed.txt" || true

echo "Diffs written under: $REPORT_DIR/raw/"
wc -l "$REPORT_DIR/raw/"*.diff "$REPORT_DIR/raw/modules-changed.txt" 2>/dev/null
