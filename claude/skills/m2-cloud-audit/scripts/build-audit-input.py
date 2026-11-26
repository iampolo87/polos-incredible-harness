#!/usr/bin/env python3
"""Merge the three gap JSONs (patch / config / service) into one audit-input
contract with computed executive-summary scorecards, consumed by render-audit.

Usage:
  build-audit-input.py --project-name NAME --date YYYY-MM-DD
       [--patch-gaps patch-gaps.json] [--config-gaps config-gaps.json]
       [--service-gaps service-gaps.json] [--no-cloud]
Emits audit-input.json to stdout.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load(p: Path | None) -> dict:
    return json.loads(p.read_text()) if (p and p.exists()) else {}


def build(patches: dict, configs: dict, services: dict,
          project: str, date: str, is_cloud: bool) -> dict:
    csum = configs.get("summary", {}) or {}
    scounts = services.get("counts", {}) or {}
    scorecards = {
        "missing_patches": patches.get("gap_total", 0),
        "patch_tiers": patches.get("by_tier", {}),
        "config_issues": csum.get("missing", 0) + csum.get("suboptimal", 0),
        "config_summary": csum,
        "eol_services": scounts.get("eol", 0) + scounts.get("below_recommended", 0),
        "service_counts": scounts,
    }
    meta = {
        "project": project,
        "magento_version": patches.get("project_version"),
        "edition": patches.get("edition"),
        "date": date,
        "is_cloud": is_cloud,
    }
    return {
        "meta": meta,
        "scorecards": scorecards,
        "patches": patches,
        "configs": configs,
        "services": services,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--patch-gaps", type=Path)
    ap.add_argument("--config-gaps", type=Path)
    ap.add_argument("--service-gaps", type=Path)
    ap.add_argument("--project-name", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--no-cloud", action="store_true")
    a = ap.parse_args()
    result = build(
        _load(a.patch_gaps), _load(a.config_gaps), _load(a.service_gaps),
        a.project_name, a.date, not a.no_cloud)
    json.dump(result, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
