#!/usr/bin/env python3
"""Compute the quality-patch GAP: patches that apply to the project's exact
versions but are not in its declared-applied set, tier-ranked by category.

  gap = matched.applicable  -  applied.applied_catalog_ids

Tier (1 = highest value): impact-ordered using the 21 QPT categories.
A multi-category patch takes the HIGHEST-priority (lowest-number) tier.

Usage:
  parse-patch-gaps.py --matched matched-patches.json --applied applied-set.json
Emits patch-gaps.json to stdout.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Category -> tier. Covers all 21 QPT categories; anything unmapped -> tier 4.
TIER_BY_CATEGORY = {
    # T1 — site speed / stability (the reason a store is on Cloud)
    "Performance": 1, "Cache": 1, "Catalog Search": 1,
    # T2 — revenue path
    "Order/Checkout": 2, "Shopping Cart": 2, "Payments": 2,
    "Price/Tax": 2, "Inventory": 2,
    # T3 — operational
    "Cron": 3, "Admin": 3, "Customer": 3, "Catalog/Product": 3,
    "Web API": 3, "GraphQL": 3, "B2B": 3,
    # T4 — everything else
    "Content": 4, "Emails": 4, "Import/Export": 4, "Reports": 4,
    "Shipping": 4, "Other": 4,
}
DEFAULT_TIER = 4


def _tier(categories) -> int:
    tiers = [TIER_BY_CATEGORY.get(c, DEFAULT_TIER) for c in (categories or [])]
    return min(tiers) if tiers else DEFAULT_TIER


def compute(matched: dict, applied: dict) -> dict:
    applicable = matched.get("applicable", [])
    applied_ids = set(applied.get("applied_catalog_ids", []))

    gaps = []
    applied_present = []
    for p in applicable:
        if p["id"] in applied_ids:
            applied_present.append(p["id"])
            continue
        requires = p.get("requires", []) or []
        gaps.append({
            "id": p["id"],
            "title": p.get("title", ""),
            "categories": p.get("categories", []),
            "tier": _tier(p.get("categories", [])),
            "file": p.get("file", ""),
            "matched_package": p.get("matched_package", ""),
            "matched_version": p.get("matched_version", ""),
            "source": p.get("source", ""),
            "requires": requires,
            # prerequisites that are themselves still unapplied -> apply first
            "requires_unapplied": [r for r in requires if r not in applied_ids],
        })

    gaps.sort(key=lambda g: (g["tier"], g["id"]))

    by_tier = {"1": 0, "2": 0, "3": 0, "4": 0}
    for g in gaps:
        by_tier[str(g["tier"])] += 1

    notes = []
    if any(g["requires_unapplied"] for g in gaps):
        notes.append(
            "Some patches require prerequisite patches that are not yet "
            "applied — apply prerequisites first (see 'requires_unapplied')."
        )

    return {
        "project_version": matched.get("project_version"),
        "edition": matched.get("edition"),
        "applicable_total": len(applicable),
        "applied_total": len(applied_present),
        "gap_total": len(gaps),
        "by_tier": by_tier,
        "gaps": gaps,
        "applied_present": sorted(applied_present),
        "manual_patches": applied.get("manual_patches", []),
        "detection": "declared",
        "notes": notes,
        "errors": matched.get("errors", []),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--matched", type=Path, required=True)
    ap.add_argument("--applied", type=Path, required=True)
    a = ap.parse_args()
    matched = json.loads(a.matched.read_text())
    applied = json.loads(a.applied.read_text())
    json.dump(compute(matched, applied), sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
