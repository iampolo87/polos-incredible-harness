#!/usr/bin/env python3
"""Collect the set of quality patches a Magento Cloud project has DECLARED
as applied, from three independent sources, unioned:

  1. .magento.env.yaml  -> stage.build.QUALITY_PATCHES   (Cloud auto-apply)
  2. m2-hotfixes/*.patch -> catalog ids parsed from filenames
  3. composer.json       -> extra.patches                (cengage/vaimo style)

IMPORTANT: this detects DECLARED-applied, not file-content-verified-applied.
A patch listed here that silently failed to apply still shows as applied.
The report carries that caveat; do not over-claim.

Usage:
  collect-applied-set.py [--env-yaml P] [--composer-json P] [--hotfixes-dir P]
Emits applied-set.json to stdout. Every source is optional (non-Cloud or
partial projects degrade gracefully).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _miniyaml  # noqa: E402

# Catalog/security patch id prefixes that appear in QPT + Adobe hotfixes.
ID_RE = re.compile(r"\b(ACSD|MDVA|MC|MCLOUD|MCP|AC|B2B|VULN|MDVABUG)-\d+\b")


def _ids(text: str) -> list[str]:
    return [m.group(0) for m in ID_RE.finditer(text)]


def collect(env_yaml: Path | None, composer: Path | None, hotfixes: Path | None) -> dict:
    applied: list[str] = []
    manual: list[dict] = []
    hotfix_files: list[str] = []
    present = {"env_yaml": False, "composer_patches": False, "m2_hotfixes": False}

    if env_yaml and env_yaml.exists():
        present["env_yaml"] = True
        data = _miniyaml.load(env_yaml.read_text()) or {}
        qp = (((data.get("stage") or {}).get("build") or {}).get("QUALITY_PATCHES")) or []
        if isinstance(qp, list):
            applied.extend(str(x) for x in qp)

    if hotfixes and hotfixes.exists():
        present["m2_hotfixes"] = True
        for f in sorted(hotfixes.glob("*.patch")):
            hotfix_files.append(f.name)
            applied.extend(_ids(f.name))

    if composer and composer.exists():
        cfg = json.loads(composer.read_text())
        patches = ((cfg.get("extra") or {}).get("patches")) or {}
        if patches:
            present["composer_patches"] = True
        for pkg, entries in patches.items():
            for label, file in (entries or {}).items():
                manual.append(
                    {"source": "composer.json.extra.patches", "package": pkg,
                     "label": label, "file": file}
                )
                applied.extend(_ids(label))
                applied.extend(_ids(str(file)))

    # dedupe, preserve first-seen order
    seen: set[str] = set()
    deduped = [i for i in applied if not (i in seen or seen.add(i))]

    return {
        "applied_catalog_ids": deduped,
        "manual_patches": manual,
        "hotfix_files": hotfix_files,
        "sources_present": present,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-yaml", type=Path)
    ap.add_argument("--composer-json", type=Path)
    ap.add_argument("--hotfixes-dir", type=Path)
    a = ap.parse_args()
    result = collect(a.env_yaml, a.composer_json, a.hotfixes_dir)
    json.dump(result, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
