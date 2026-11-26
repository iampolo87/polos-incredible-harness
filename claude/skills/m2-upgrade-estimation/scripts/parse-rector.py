#!/usr/bin/env python3
"""
Parse `rector process --dry-run --output-format=json` output into counts.

Groups applied rector rules into the four rule sets the skill cares about by
namespace prefix (Rector\\Php* → PHP_LEVEL, DeadCode, CodeQuality,
TypeDeclaration), counting rule *applications* across all changed files.
`files_changed` drives nothing on its own but is reported for the signals file.

Usage:
  parse-rector.py --input rector-dryrun.json [--out signals-rector.json]
Prints the result JSON to stdout (and to --out if given).
"""

import argparse
import json
import sys
from pathlib import Path

PREFIX_TO_SET = {
    "Rector\\Php": "PHP_LEVEL",
    "Rector\\DeadCode": "DEAD_CODE",
    "Rector\\CodeQuality": "CODE_QUALITY",
    "Rector\\TypeDeclaration": "TYPE_DECLARATION",
}


def classify(rule: str) -> str:
    for prefix, name in PREFIX_TO_SET.items():
        if rule.startswith(prefix):
            return name
    return "OTHER"


def vendor_of(path: str) -> str:
    """Extract the app/code Vendor segment from a (relative or absolute) file path."""
    if "/app/code/" in path:
        seg = path.split("/app/code/", 1)[1]
    elif path.startswith("app/code/"):
        seg = path[len("app/code/"):]
    else:
        seg = path
    return seg.split("/", 1)[0] if seg else ""


def parse(data: dict, exclude: set[str] | None = None) -> dict:
    exclude = exclude or set()
    by_ruleset = {"PHP_LEVEL": 0, "CODE_QUALITY": 0, "DEAD_CODE": 0, "TYPE_DECLARATION": 0, "OTHER": 0}
    file_diffs = [fd for fd in (data.get("file_diffs") or [])
                  if vendor_of(fd.get("file", "")).lower() not in exclude]
    for fd in file_diffs:
        for rule in fd.get("applied_rectors") or []:
            by_ruleset[classify(rule)] += 1
    return {"files_changed": len(file_diffs), "by_ruleset": by_ruleset}


def main() -> int:
    ap = argparse.ArgumentParser(description="Parse Rector dry-run JSON into rule-set counts.")
    ap.add_argument("--input", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--exclude-vendors", default="",
                    help="CSV of maintained-commercial vendors to exclude from counts")
    args = ap.parse_args()

    exclude = {v.strip().lower() for v in args.exclude_vendors.split(",") if v.strip()}
    raw = args.input.read_text().strip()
    data = json.loads(raw) if raw else {}
    result = parse(data, exclude)

    out_str = json.dumps(result, indent=2)
    if args.out:
        args.out.write_text(out_str)
    sys.stdout.write(out_str + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
