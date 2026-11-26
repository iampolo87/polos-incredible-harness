#!/usr/bin/env python3
"""
Parse Adobe Upgrade Compatibility Tool (UCT) JSON report into severity counts.

UCT report shapes vary (flat list, or nested module → file → findings), so this
walks the JSON recursively and tallies every object carrying a `level` field
(CRITICAL / ERROR / WARNING, case-insensitive).

The auto-fixable count is NOT inferable from `upgrade:check` output, so it is
passed in via --autofix (collect-signals.sh derives it from a separate
`uct refactor --dry-run` pass) and echoed through.

Usage:
  parse-uct.py --input uct-report.json [--autofix N] [--out signals-uct.json]
Prints the result JSON to stdout (and to --out if given).
"""

import argparse
import json
import sys
from pathlib import Path

LEVELS = ("critical", "error", "warning")


def vendor_of(path: str) -> str:
    """Extract the app/code Vendor segment from a UCT issue fileName."""
    if "/app/code/" in path:
        seg = path.split("/app/code/", 1)[1]
    elif path.startswith("app/code/"):
        seg = path[len("app/code/"):]
    else:
        seg = path
    return seg.split("/", 1)[0] if seg else ""


def walk_levels(node, acc: dict) -> None:
    """Fallback for nested UCT shapes without a top-level issues[] list."""
    if isinstance(node, dict):
        lvl = node.get("level")
        if isinstance(lvl, str):
            key = lvl.strip().lower()
            acc[key if key in acc else "other"] = acc.get(key if key in acc else "other", 0) + 1
        for v in node.values():
            walk_levels(v, acc)
    elif isinstance(node, list):
        for v in node:
            walk_levels(v, acc)


SAMPLE_CAP = 100
_RANK = {"CRITICAL": 0, "ERROR": 1, "WARNING": 2}


def rel_path(p: str) -> str:
    """Trim an absolute path down to the app/code-relative portion for display."""
    return "app/code/" + p.split("/app/code/", 1)[1] if "/app/code/" in p else p


def is_upgrade_delta(message: str) -> bool:
    """True only for API actually REMOVED/changed in the target — genuine upgrade
    work. 'non-API' / '@deprecated' / 'discouraged' findings are version-agnostic
    pre-existing debt (present on the current version too), NOT upgrade-introduced."""
    return "removed" in message.lower()


def parse(data, autofix: int, exclude: set[str] | None = None) -> dict:
    exclude = exclude or set()
    acc = {lvl: 0 for lvl in LEVELS}
    delta = {lvl: 0 for lvl in LEVELS}
    preexisting = 0
    kept: list[dict] = []
    issues = data.get("issues") if isinstance(data, dict) else None
    if isinstance(issues, list):
        # UCT 3.x --json-output-path shape: filter by vendor, tally by level, keep sample
        for it in issues:
            if vendor_of(str(it.get("fileName", ""))).lower() in exclude:
                continue
            lvl = str(it.get("level", "")).strip().lower()
            acc[lvl if lvl in acc else "other"] = acc.get(lvl if lvl in acc else "other", 0) + 1
            msg = str(it.get("message", "")).strip()
            is_delta = is_upgrade_delta(msg)
            if is_delta and lvl in delta:
                delta[lvl] += 1
            elif not is_delta:
                preexisting += 1
            kept.append({
                "level": str(it.get("level", "")).strip().upper(),
                "message": msg,
                "file": rel_path(str(it.get("fileName", ""))),
                "line": it.get("lineNumber"),
                "kind": "upgrade-delta" if is_delta else "preexisting",
            })
    else:
        walk_levels(data, acc)  # no per-issue path → exclusion / sample not applicable
    findings = sum(acc[lvl] for lvl in LEVELS) + acc.get("other", 0)
    by_severity = {lvl: acc[lvl] for lvl in LEVELS}
    if acc.get("other"):
        by_severity["other"] = acc["other"]
    kept.sort(key=lambda x: (x["kind"] != "upgrade-delta", _RANK.get(x["level"], 9)))
    return {
        "findings": findings, "autofix": autofix, "by_severity": by_severity,
        "upgrade_delta": {"findings": sum(delta.values()), "by_severity": delta},
        "preexisting": {"findings": preexisting},
        "sample": kept[:SAMPLE_CAP],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Parse UCT JSON report into severity counts.")
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--autofix", type=int, default=0)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--exclude-vendors", default="",
                    help="CSV of maintained-commercial vendors to exclude (by app/code path)")
    args = ap.parse_args()

    exclude = {v.strip().lower() for v in args.exclude_vendors.split(",") if v.strip()}
    raw = args.input.read_text().strip()
    data = json.loads(raw) if raw else {}
    result = parse(data, args.autofix, exclude)

    out_str = json.dumps(result, indent=2)
    if args.out:
        args.out.write_text(out_str)
    sys.stdout.write(out_str + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
