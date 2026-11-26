#!/usr/bin/env python3
"""Flag Magento Cloud services running EOL or below-recommended versions.

Reads .magento/services.yaml (mysql/redis/opensearch/elasticsearch/rabbitmq)
and .magento.app.yaml (php), compares each against references/service-eol.json.

  status = eol               if the running version has an EOL date <= as-of
         = below_recommended if not EOL but below the recommended floor
         = ok                otherwise

Usage:
  parse-service-versions.py --services services.yaml --eol service-eol.json
        [--app .magento.app.yaml] [--as-of YYYY-MM-DD]
Emits service-gaps.json to stdout.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _miniyaml  # noqa: E402
import _semver_lite as sv  # noqa: E402


def _version_of(type_str) -> str | None:
    # "mysql:10.4" -> "10.4" ; "php:8.1" -> "8.1"
    if not isinstance(type_str, str) or ":" not in type_str:
        return None
    return type_str.split(":", 1)[1].strip()


def _app_php_version(text: str) -> str | None:
    """Extract the top-level `type: php:X.Y` from .magento.app.yaml.

    Top-level = zero indentation, so we never descend into hooks/crons blocks.
    """
    for raw in text.splitlines():
        if raw[:1] in (" ", "\t", "#", ""):
            continue
        stripped = raw.strip()
        if stripped.startswith("type:"):
            return _version_of(stripped.split(":", 1)[1].strip())
    return None


def _eol_date_for(version: str, eol_map: dict) -> str | None:
    """Match a running version to an EOL entry by major.minor."""
    if version in eol_map:
        return eol_map[version]
    mm = ".".join(version.split(".")[:2])
    return eol_map.get(mm)


def classify(version: str, spec: dict, as_of_ym: str) -> dict:
    eol_map = spec.get("eol", {}) or {}
    floor = spec.get("recommended_floor")
    eol_date = _eol_date_for(version, eol_map)
    if eol_date and eol_date <= as_of_ym:
        status, severity = "eol", "high"
    elif floor and sv.lt(version, floor):
        status, severity = "below_recommended", "medium"
    else:
        status, severity = "ok", "info"
    return {
        "current": version,
        "status": status,
        "severity": severity,
        "eol_date": eol_date,
        "recommended_floor": floor,
    }


def collect(services_yaml: Path, app_yaml: Path | None, eol: dict, as_of: str) -> dict:
    as_of_ym = as_of[:7]
    services_spec = eol.get("services", {})
    findings = []

    running: dict[str, str] = {}
    if services_yaml and services_yaml.exists():
        sdata = _miniyaml.load(services_yaml.read_text()) or {}
        for key, block in sdata.items():
            if isinstance(block, dict) and "type" in block:
                ver = _version_of(block["type"])
                if ver:
                    running[key] = ver
    if app_yaml and app_yaml.exists():
        # .magento.app.yaml carries block-scalar hooks/crons and flow sequences
        # beyond the miniyaml subset; we only need the top-level `type:` line,
        # so scan for it directly instead of parsing the whole file.
        ver = _app_php_version(app_yaml.read_text())
        if ver:
            running["php"] = ver

    for key, ver in running.items():
        spec = services_spec.get(key)
        if not spec:
            findings.append({
                "service": key, "label": key, "current": ver,
                "status": "unknown", "severity": "info",
                "eol_date": None, "recommended_floor": None,
                "rationale": "No EOL data for this service in the catalog.",
                "source_url": None,
            })
            continue
        c = classify(ver, spec, as_of_ym)
        rationale = {
            "eol": f"{spec['label']} {ver} reached end-of-life ({c['eol_date']}); "
                   f"no security fixes. Upgrade to >= {spec.get('recommended_floor')}.",
            "below_recommended": f"{spec['label']} {ver} is below the recommended "
                                 f"floor {spec.get('recommended_floor')}.",
            "ok": f"{spec['label']} {ver} is supported.",
        }[c["status"]]
        findings.append({
            "service": key, "label": spec["label"], **c,
            "rationale": rationale, "source_url": spec.get("source_url"),
        })

    findings.sort(key=lambda f: ({"high": 0, "medium": 1, "info": 2}.get(f["severity"], 3),
                                 f["service"]))
    counts = {"eol": 0, "below_recommended": 0, "ok": 0, "unknown": 0}
    for f in findings:
        counts[f["status"]] = counts.get(f["status"], 0) + 1
    return {
        "as_of": as_of,
        "catalog_version": eol.get("catalog_version"),
        "last_reviewed": eol.get("last_reviewed"),
        "counts": counts,
        "findings": findings,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--services", type=Path, required=True)
    ap.add_argument("--app", type=Path)
    ap.add_argument("--eol", type=Path, required=True)
    ap.add_argument("--as-of", default="2026-06-23")
    a = ap.parse_args()
    eol = json.loads(a.eol.read_text())
    json.dump(collect(a.services, a.app, eol, a.as_of), sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
