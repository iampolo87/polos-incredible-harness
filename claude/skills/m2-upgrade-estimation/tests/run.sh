#!/usr/bin/env bash
# Run every unit test in this directory. Exit non-zero if any fails.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"
fail=0
for t in test_*.py; do
  if python3 "$t"; then :; else echo "FAIL: $t"; fail=1; fi
done
[ "$fail" -eq 0 ] && echo "ALL TESTS PASS" || echo "SOME TESTS FAILED"
exit "$fail"
