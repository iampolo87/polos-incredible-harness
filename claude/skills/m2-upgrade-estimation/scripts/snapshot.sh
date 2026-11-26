#!/usr/bin/env bash
# Phase 2.2 — Snapshot the current vendor state BEFORE running composer update.
# Usage: snapshot.sh <snapshot-dir>
# Example: snapshot.sh /tmp/magento-snapshot-2.4.7-p9
set -euo pipefail

SNAPSHOT_DIR="${1:?snapshot-dir required}"

[ -d vendor/magento ] || { echo "ERROR: vendor/magento not found — run composer install first" >&2; exit 1; }

mkdir -p "$SNAPSHOT_DIR"
cp -a vendor/magento "$SNAPSHOT_DIR/magento"
[ -d vendor/laminas ] && cp -a vendor/laminas "$SNAPSHOT_DIR/laminas"
cp composer.json "$SNAPSHOT_DIR/composer.json"
cp composer.lock "$SNAPSHOT_DIR/composer.lock"

echo "Snapshot complete at: $SNAPSHOT_DIR"
du -sh "$SNAPSHOT_DIR"/* 2>/dev/null
