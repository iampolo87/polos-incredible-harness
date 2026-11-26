#!/usr/bin/env python3
"""
Inject vanilla inline JS + CSS that makes every <table> column-sortable.

Design constraints:
- Self-contained: zero external dependencies (no CDN, no module imports).
- Print-safe: sort indicators hidden when @media print.
- Offline-safe: pure inline <script> block, works from file:// URL.
- Multi-row thead aware: handles colspan/rowspan correctly using grid walk
  (the Mini-PERT table has rowspan=2 + colspan=5 in its header).
- Idempotent: strips prior injection before re-inserting.
- Tri-state: ascending → descending → unsorted (restores original order).
- Numeric-aware: detects numeric columns (including suffixes like "h", "d", "%")
  and sorts numerically; otherwise locale-aware string sort.
- No external libs, no jQuery, no frameworks.

Usage: add-sortable-tables.py <report.html>  (mutates the file in place)
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _safety import BackupGuard, assert_strip_safe  # noqa: E402

STRIP_PATTERN = (
    r"\s*<!--\s+[─\-=*\s]*BEGIN:\s*sortable tables"
    r"[\s\S]*?"
    r"END:\s*sortable tables[─\-=*\s]*-->\s*"
)

INJECTION = """
<!-- ─── BEGIN: sortable tables (inline, idempotent, print-safe) ─── -->
<style>
  table th[data-sortable] {
    cursor: pointer;
    user-select: none;
    position: relative;
    padding-right: 18px;
  }
  table th[data-sortable]:hover {
    background: var(--accent-soft, rgba(0,0,0,0.05));
  }
  table th[data-sortable]::after {
    content: '↕';
    position: absolute;
    right: 6px;
    top: 50%;
    transform: translateY(-50%);
    opacity: 0.35;
    font-size: 0.85em;
    font-weight: normal;
    pointer-events: none;
  }
  table th[data-sort-dir="asc"]::after  { content: '↑'; opacity: 1; color: var(--accent, currentColor); }
  table th[data-sort-dir="desc"]::after { content: '↓'; opacity: 1; color: var(--accent, currentColor); }
  @media print {
    table th[data-sortable] { cursor: default; padding-right: inherit; }
    table th[data-sortable]::after,
    table th[data-sort-dir]::after { content: '' !important; display: none !important; }
  }
</style>
<script>
(function () {
  'use strict';

  // Resolve leaf headers respecting colspan/rowspan. Returns array of
  // { th, colIdx } where colIdx maps to a 0-based logical column matching
  // <tbody> cells when no body-level spans exist.
  function getLeafHeaders(thead) {
    var rows = Array.prototype.slice.call(thead.querySelectorAll(':scope > tr'));
    if (!rows.length) return [];
    var grid = [];
    var maxCols = 0;
    rows.forEach(function (row, rIdx) {
      if (!grid[rIdx]) grid[rIdx] = [];
      var cIdx = 0;
      Array.prototype.slice.call(row.cells).forEach(function (th) {
        while (grid[rIdx][cIdx] !== undefined) cIdx++;
        var rowspan = parseInt(th.getAttribute('rowspan'), 10) || 1;
        var colspan = parseInt(th.getAttribute('colspan'), 10) || 1;
        for (var r = 0; r < rowspan; r++) {
          if (!grid[rIdx + r]) grid[rIdx + r] = [];
          for (var c = 0; c < colspan; c++) {
            grid[rIdx + r][cIdx + c] = th;
          }
        }
        cIdx += colspan;
        if (cIdx > maxCols) maxCols = cIdx;
      });
    });
    var bottom = grid[grid.length - 1] || [];
    var seen = new Set();
    var leaves = [];
    for (var c = 0; c < maxCols; c++) {
      var th = bottom[c];
      if (th && !seen.has(th)) {
        seen.add(th);
        leaves.push({ th: th, colIdx: c });
      }
    }
    return leaves;
  }

  // Parse a numeric value from a cell string. Returns NaN if not numeric.
  // Tolerant of suffixes (h, d, %, etc.) and decimal commas.
  function parseNum(s) {
    if (!s) return NaN;
    var cleaned = s.replace(/\\s+/g, '').replace(',', '.');
    var m = cleaned.match(/^-?\\d+(?:\\.\\d+)?/);
    if (!m) return NaN;
    var rest = cleaned.slice(m[0].length);
    // Allow common suffixes: h, d, %, hr, hrs, days
    if (rest && !/^(h|d|%|hr|hrs|hour|hours|day|days|min|m|s|sec)$/i.test(rest)) {
      // Has trailing non-suffix junk → not a clean number
      return NaN;
    }
    return parseFloat(m[0]);
  }

  function getCellText(row, colIdx) {
    var cell = row.cells[colIdx];
    return cell ? (cell.textContent || '').trim() : '';
  }

  function sortBody(tbody, colIdx, direction) {
    var rows = Array.prototype.slice.call(tbody.querySelectorAll(':scope > tr'));
    if (direction === 'none') {
      // Restore original order via data-orig-index
      rows.sort(function (a, b) {
        return (parseInt(a.dataset.origIndex, 10) || 0) -
               (parseInt(b.dataset.origIndex, 10) || 0);
      });
    } else {
      var mult = direction === 'asc' ? 1 : -1;
      // Sample first 3 rows to decide numeric vs string mode
      var sample = rows.slice(0, Math.min(3, rows.length))
        .map(function (r) { return getCellText(r, colIdx); });
      var allNumeric = sample.length > 0 && sample.every(function (s) {
        return s !== '' && !isNaN(parseNum(s));
      });
      rows.sort(function (a, b) {
        var aT = getCellText(a, colIdx);
        var bT = getCellText(b, colIdx);
        if (allNumeric) {
          var aN = parseNum(aT);
          var bN = parseNum(bT);
          if (isNaN(aN) && isNaN(bN)) return 0;
          if (isNaN(aN)) return 1;   // empty/non-numeric to the end
          if (isNaN(bN)) return -1;
          return (aN - bN) * mult;
        }
        return aT.localeCompare(bT, undefined, {
          numeric: true,
          sensitivity: 'base'
        }) * mult;
      });
    }
    var frag = document.createDocumentFragment();
    rows.forEach(function (r) { frag.appendChild(r); });
    tbody.appendChild(frag);
  }

  function attachTable(table) {
    if (table.dataset.sortableInit === '1') return;
    var thead = table.querySelector(':scope > thead');
    var tbody = table.querySelector(':scope > tbody');
    if (!thead || !tbody) return;
    var leaves = getLeafHeaders(thead);
    if (!leaves.length) return;

    // Stamp original index for tri-state restore
    Array.prototype.slice.call(tbody.querySelectorAll(':scope > tr'))
      .forEach(function (r, i) { r.dataset.origIndex = String(i); });

    leaves.forEach(function (entry) {
      var th = entry.th;
      var colIdx = entry.colIdx;
      th.setAttribute('data-sortable', 'true');
      th.setAttribute('tabindex', '0');
      th.setAttribute('aria-sort', 'none');
      th.setAttribute('title', 'Click para ordenar (asc → desc → original)');
      // NOTE: do NOT set role="button" — that would clobber the implicit
      // role="columnheader" on <th>. Screen readers correctly announce a
      // <th aria-sort="ascending"> as "column header, sorted ascending".

      function activate() {
        var current = th.getAttribute('data-sort-dir') || 'none';
        var next;
        if (current === 'none') next = 'asc';
        else if (current === 'asc') next = 'desc';
        else next = 'none';
        // Clear all sibling sort indicators in this table
        leaves.forEach(function (e) {
          e.th.removeAttribute('data-sort-dir');
          e.th.setAttribute('aria-sort', 'none');
        });
        if (next !== 'none') {
          th.setAttribute('data-sort-dir', next);
          th.setAttribute('aria-sort', next === 'asc' ? 'ascending' : 'descending');
        }
        sortBody(tbody, colIdx, next);
      }

      th.addEventListener('click', activate);
      th.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter' || ev.key === ' ') {
          ev.preventDefault();
          activate();
        }
      });
    });

    table.dataset.sortableInit = '1';
  }

  function init() {
    Array.prototype.slice.call(document.querySelectorAll('table'))
      .forEach(attachTable);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
</script>
<!-- ─── END: sortable tables ─── -->
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="Inject sortable-table JS/CSS into an HTML report (idempotent).")
    ap.add_argument("report", type=Path, help="HTML report to mutate in place")
    args = ap.parse_args()
    report = args.report

    # Mandatory fixture test BEFORE touching the real file (Lesson #38).
    assert_strip_safe(STRIP_PATTERN, marker="sortable tables")

    # Atomic mutation guard (Lesson #37). Backs up before any write and
    # auto-restores if the file shrinks > 10% (Lesson #39).
    with BackupGuard(report, label="sortable-tables") as guard:
        content = report.read_text()
        content = re.sub(STRIP_PATTERN, "\n", content, flags=re.DOTALL)

        if "</body>" not in content:
            raise SystemExit("Could not find </body>")
        content = content.replace("</body>", INJECTION + "\n</body>", 1)

        report.write_text(content)
        guard.commit(content)

    table_count = content.count("<table")
    print(f"Tables in report: {table_count}")
    print(f"Sortable JS block present: {content.count('BEGIN: sortable tables')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
