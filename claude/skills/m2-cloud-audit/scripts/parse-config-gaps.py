#!/usr/bin/env python3
"""Diff a curated config-recommendation catalog against a project's actual
Cloud config files, emitting per-setting gaps with paste-ready snippets.

Statuses:
  ok          present and at the recommended value
  missing     the relevant file exists but the setting is absent
  suboptimal  present but not at the recommended value (captures current_value)
  na          applies_to gate excludes this project (service absent / too old)
  no_file     the location's file was not provided / does not exist (non-Cloud)
  deferred    location is env.php but it is Cloud-generated at deploy — cannot
              assert from the repo; the real value comes from deploy variables

Usage:
  parse-config-gaps.py --catalog config-recommendations.json
       [--services services.yaml] [--env-yaml .magento.env.yaml]
       [--php-ini php.ini] [--envphp-json env.php.json]
Emits config-gaps.json to stdout.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _miniyaml  # noqa: E402
import _semver_lite as sv  # noqa: E402


def _walk(data, path):
    cur = data
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None, False
        cur = cur[key]
    return cur, True


def _load_yaml(p: Path | None):
    if p and p.exists():
        return _miniyaml.load(p.read_text()) or {}, True
    return {}, False


def _load_ini(p: Path | None):
    """Flat key=value reader for php.ini / .user.ini (stdlib configparser is
    too strict for Magento's bare .user.ini files)."""
    if not (p and p.exists()):
        return {}, False
    out = {}
    for raw in p.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith((";", "#", "[")):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.split(";", 1)[0].strip()
    return out, True


def _norm(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v).strip().strip('"').strip("'")


def _evaluate(match: str, recommended: str, value) -> str:
    """Return 'ok' or 'suboptimal' for a PRESENT value."""
    rv = _norm(recommended)
    cur = _norm(value)
    if match == "present":
        return "ok"
    if match == "equals":
        return "ok" if cur.lower() == rv.lower() else "suboptimal"
    if match == "contains":
        return "ok" if rv.lower() in cur.lower() else "suboptimal"
    if match == "version_gte":
        try:
            return "ok" if sv.gte(cur, rv) else "suboptimal"
        except Exception:
            return "suboptimal"
    if match == "size_gte":
        try:
            return "ok" if _to_bytes(cur) >= _to_bytes(rv) else "suboptimal"
        except Exception:
            return "suboptimal"
    return "suboptimal"


def _to_bytes(s: str) -> int:
    """Parse a php-style byte size (e.g. 32k, 10M, 512, 1G) to bytes."""
    t = str(s).strip()
    mult = {"k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}
    if t and t[-1].lower() in mult:
        return int(float(t[:-1]) * mult[t[-1].lower()])
    return int(float(t))


def _applies(rec: dict, services: dict, services_present: bool) -> tuple[bool, str]:
    gate = rec.get("applies_to") or {}
    svc = gate.get("service")
    if svc:
        if not services_present:
            return True, ""   # can't gate without the file; handled as no_file later
        block = services.get(svc)
        if not isinstance(block, dict):
            return False, f"service '{svc}' not provisioned"
        minv = gate.get("min_version")
        if minv and isinstance(block.get("type"), str) and ":" in block["type"]:
            running = block["type"].split(":", 1)[1]
            if sv.lt(running, minv):
                return False, f"{svc} {running} < required {minv}"
    return True, ""


LOADERS = {
    "services.yaml": "services",
    ".magento.env.yaml": "env",
    "php.ini": "ini",
    "env.php": "envphp",
}


def audit(catalog: dict, sources: dict) -> dict:
    recs = catalog.get("recommendations", [])
    findings = []
    for rec in recs:
        loc = rec["location"]
        kind = LOADERS.get(loc)
        applies, na_reason = _applies(rec, sources["services"][0], sources["services"][1])

        if not applies:
            findings.append(_finding(rec, "na", note=na_reason))
            continue

        if loc == "env.php":
            data, present = sources["envphp"]
            if not present:
                findings.append(_finding(
                    rec, "deferred",
                    note="env.php is Cloud-generated at deploy; set via "
                         ".magento.env.yaml deploy variables, not the repo."))
                continue
        else:
            data, present = sources[kind]
            if not present:
                findings.append(_finding(rec, "no_file",
                                         note=f"{loc} not found in project"))
                continue

        if kind == "ini":
            value = data.get(rec["path"][0])
            found = rec["path"][0] in data
        else:
            value, found = _walk(data, rec["path"])

        if not found or value is None:
            findings.append(_finding(rec, "missing"))
            continue

        status = _evaluate(rec["match"], rec["recommended_value"], value)
        findings.append(_finding(rec, status, current_value=value))

    summary = {k: 0 for k in
               ("ok", "missing", "suboptimal", "na", "no_file", "deferred")}
    for f in findings:
        summary[f["status"]] = summary.get(f["status"], 0) + 1

    # sort: actionable first (missing/suboptimal) by severity, then the rest
    sev = {"high": 0, "medium": 1, "low": 2}
    order = {"missing": 0, "suboptimal": 1, "deferred": 2,
             "no_file": 3, "na": 4, "ok": 5}
    findings.sort(key=lambda f: (order.get(f["status"], 9),
                                 sev.get(f["severity"], 3), f["id"]))
    return {
        "catalog_version": catalog.get("catalog_version"),
        "last_reviewed": catalog.get("last_reviewed"),
        "summary": summary,
        "findings": findings,
    }


def _finding(rec, status, current_value=None, note=""):
    return {
        "id": rec["id"], "setting": rec["setting"], "location": rec["location"],
        "category": rec.get("category"), "severity": rec.get("severity"),
        "status": status,
        "recommended_value": rec.get("recommended_value"),
        "current_value": current_value,
        "default": rec.get("default"),
        "rationale": rec.get("rationale"), "source_url": rec.get("source_url"),
        "snippet": rec.get("snippet"), "note": note,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", type=Path, required=True)
    ap.add_argument("--services", type=Path)
    ap.add_argument("--env-yaml", type=Path)
    ap.add_argument("--php-ini", type=Path)
    ap.add_argument("--envphp-json", type=Path)
    a = ap.parse_args()

    catalog = json.loads(a.catalog.read_text())
    envphp = ({}, False)
    if a.envphp_json and a.envphp_json.exists():
        envphp = (json.loads(a.envphp_json.read_text()), True)
    sources = {
        "services": _load_yaml(a.services),
        "env": _load_yaml(a.env_yaml),
        "ini": _load_ini(a.php_ini),
        "envphp": envphp,
    }
    json.dump(audit(catalog, sources), sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
