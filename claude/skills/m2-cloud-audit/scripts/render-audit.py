#!/usr/bin/env python3
"""Render audit-input.json into a self-contained English HTML report.

Builds HTML fragments in Python and substitutes {{PLACEHOLDER}} tokens in
templates/audit-report.html (same pattern as the sibling estimate renderer).
No external assets — the output opens standalone.

Usage:
  render-audit.py --input audit-input.json --template audit-report.html
        --output audit.html
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

TIER_LABEL = {1: "T1", 2: "T2", 3: "T3", 4: "T4"}


def esc(v) -> str:
    return html.escape("" if v is None else str(v))


def _card_class(n_high, n_med=0) -> str:
    if n_high:
        return "high"
    if n_med:
        return "med"
    return "ok"


def patch_table(patches: dict) -> str:
    gaps = patches.get("gaps", [])
    if not gaps:
        return "<p>None — every applicable patch is declared applied.</p>"
    rows = []
    for g in gaps:
        tier = g.get("tier", 4)
        req = g.get("requires_unapplied") or []
        req_html = ("<br><span class='src'>needs first: "
                    + esc(", ".join(req)) + "</span>") if req else ""
        rows.append(
            "<tr>"
            f"<td data-v='{tier}'><span class='pill t{tier}'>{TIER_LABEL.get(tier,'T4')}</span></td>"
            f"<td class='id'><code>{esc(g.get('id'))}</code></td>"
            f"<td>{esc(', '.join(g.get('categories', [])))}</td>"
            f"<td>{esc(g.get('title'))}{req_html}</td>"
            f"<td class='mono'>{esc(g.get('file'))}</td>"
            "</tr>")
    return (
        "<table class='sortable'><thead><tr>"
        "<th data-sort='num'>Tier</th><th data-sort='str'>Patch</th>"
        "<th data-sort='str'>Category</th><th data-sort='str'>Title</th>"
        "<th data-sort='str'>File</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>")


def applied_table(patches: dict) -> str:
    ids = patches.get("applied_present", [])
    if not ids:
        return "<p>No declared catalog patches detected as applied.</p>"
    chips = " ".join(f"<code>{esc(i)}</code>" for i in ids)
    return f"<p><b>Applied (declared):</b> {chips}</p>"


def manual_table(patches: dict) -> str:
    man = patches.get("manual_patches", [])
    if not man:
        return ""
    rows = "".join(
        f"<tr><td class='mono'>{esc(m.get('label'))}</td>"
        f"<td class='mono'>{esc(m.get('file'))}</td>"
        f"<td>{esc(m.get('source'))}</td></tr>" for m in man)
    return ("<h3>Manual / hotfix patches present</h3>"
            "<table><thead><tr><th>Label</th><th>File</th><th>Source</th>"
            "</tr></thead><tbody>" + rows + "</tbody></table>")


def config_table(configs: dict) -> str:
    findings = configs.get("findings", [])
    if not findings:
        return "<p>No config recommendations evaluated.</p>"
    rows = []
    for f in findings:
        st = f.get("status")
        cur = f.get("current_value")
        change = ""
        if st == "suboptimal":
            change = (f"<span class='mono'>{esc(cur)}</span> "
                      f"<span class='arrow'>&rarr;</span> "
                      f"<span class='mono'>{esc(f.get('recommended_value'))}</span>")
        elif st in ("missing", "deferred", "no_file", "na"):
            change = f"<span class='mono'>{esc(f.get('recommended_value'))}</span>"
        else:  # ok
            change = "<span class='mono'>set</span>"
        note = f"<br><span class='src'>{esc(f.get('note'))}</span>" if f.get("note") else ""
        src = (f"<br><a class='src' href='{esc(f.get('source_url'))}'>docs</a>"
               if f.get("source_url") else "")
        rows.append(
            "<tr>"
            f"<td class='mono'>{esc(f.get('setting'))}</td>"
            f"<td class='mono'>{esc(f.get('location'))}</td>"
            f"<td><span class='pill st-{esc(st)}'>{esc(st)}</span></td>"
            f"<td>{change}</td>"
            f"<td><span class='pill s-{esc(f.get('severity'))}'>{esc(f.get('severity'))}</span></td>"
            f"<td>{esc(f.get('rationale'))}{note}{src}</td>"
            "</tr>")
    return (
        "<table class='sortable'><thead><tr>"
        "<th data-sort='str'>Setting</th><th data-sort='str'>Location</th>"
        "<th data-sort='str'>Status</th><th>Current &rarr; Recommended</th>"
        "<th data-sort='str'>Severity</th><th>Why</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>")


def config_snippets(configs: dict) -> str:
    items = [f for f in configs.get("findings", [])
             if f.get("status") in ("missing", "suboptimal") and f.get("snippet")]
    if not items:
        return ""
    blocks = []
    for f in items:
        blocks.append(
            "<details><summary>Fix: <code>" + esc(f.get("setting"))
            + "</code> &middot; " + esc(f.get("location")) + "</summary>"
            "<pre class='snip'>" + esc(f.get("snippet")) + "</pre></details>")
    return "<h3>Paste-ready fixes</h3>" + "".join(blocks)


def service_table(services: dict) -> str:
    findings = services.get("findings", [])
    if not findings:
        return "<p>No service version data.</p>"
    rows = []
    for f in findings:
        rows.append(
            "<tr>"
            f"<td>{esc(f.get('label'))}</td>"
            f"<td class='mono'>{esc(f.get('current'))}</td>"
            f"<td><span class='pill st-{esc(f.get('status'))}'>{esc(f.get('status'))}</span></td>"
            f"<td class='mono'>{esc(f.get('eol_date') or '—')}</td>"
            f"<td class='mono'>{esc(f.get('recommended_floor') or '—')}</td>"
            f"<td>{esc(f.get('rationale'))}</td>"
            "</tr>")
    return (
        "<table class='sortable'><thead><tr>"
        "<th data-sort='str'>Service</th><th data-sort='str'>Current</th>"
        "<th data-sort='str'>Status</th><th data-sort='str'>EOL</th>"
        "<th data-sort='str'>Recommended</th><th>Notes</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>")


def _files_seen(data: dict) -> str:
    seen = []
    for f in data.get("configs", {}).get("findings", []):
        if f.get("status") not in ("no_file",) and f.get("location") not in seen:
            seen.append(f.get("location"))
    if data.get("services", {}).get("findings"):
        seen.append("services.yaml / .magento.app.yaml")
    return esc(", ".join(dict.fromkeys(seen)) or "none")


def render(data: dict, template: str) -> str:
    meta = data.get("meta", {})
    sc = data.get("scorecards", {})
    patches = data.get("patches", {})
    configs = data.get("configs", {})
    services = data.get("services", {})

    tiers = sc.get("patch_tiers", {}) or {}
    csum = sc.get("config_summary", {}) or {}
    scounts = sc.get("service_counts", {}) or {}

    cloud_banner = (
        "<div class='cloud-banner'>Adobe Commerce <b>Cloud</b> project — "
        "<code>.magento/services.yaml</code> and <code>.magento.env.yaml</code> inspected.</div>"
        if meta.get("is_cloud") else
        "<div class='cloud-banner'>Not detected as a Cloud project — Cloud "
        "config checks are limited; patch and service sections still apply.</div>")

    repl = {
        "PROJECT": esc(meta.get("project")),
        "MAGENTO_VERSION": esc(meta.get("magento_version")),
        "EDITION": esc(meta.get("edition")),
        "DATE": esc(meta.get("date")),
        "CLOUD_BANNER": cloud_banner,

        "SC_PATCHES": esc(sc.get("missing_patches", 0)),
        "SC_PATCHES_CLASS": _card_class(sc.get("missing_patches", 0)),
        "SC_PATCHES_SUB": esc(" ".join(
            f"T{t}:{tiers.get(str(t), 0)}" for t in (1, 2, 3, 4))),

        "SC_CONFIGS": esc(sc.get("config_issues", 0)),
        "SC_CONFIGS_CLASS": _card_class(csum.get("missing", 0), csum.get("suboptimal", 0)),
        "SC_CONFIGS_SUB": esc(f"{csum.get('missing', 0)} missing, "
                              f"{csum.get('suboptimal', 0)} suboptimal, "
                              f"{csum.get('ok', 0)} ok"),

        "SC_SERVICES": esc(sc.get("eol_services", 0)),
        "SC_SERVICES_CLASS": _card_class(scounts.get("eol", 0),
                                         scounts.get("below_recommended", 0)),
        "SC_SERVICES_SUB": esc(f"{scounts.get('eol', 0)} EOL, "
                               f"{scounts.get('below_recommended', 0)} below floor"),

        "PATCH_TABLE": patch_table(patches),
        "APPLIED_COUNT": esc(len(patches.get("applied_present", []))),
        "APPLIED_TABLE": applied_table(patches),
        "MANUAL_TABLE": manual_table(patches),

        "CONFIG_TABLE": config_table(configs),
        "CONFIG_SNIPPETS": config_snippets(configs),

        "SERVICE_TABLE": service_table(services),

        "CATALOG_VERSION": esc(configs.get("catalog_version") or "—"),
        "CATALOG_REVIEWED": esc(configs.get("last_reviewed") or "—"),
        "FILES_SEEN": _files_seen(data),
        "GENERATED": esc(meta.get("date")),
        "PATCH_CATALOG_NOTE": esc("read live from vendor/magento/quality-patches"),
    }
    out = template
    for k, v in repl.items():
        out = out.replace("{{" + k + "}}", v)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--template", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    data = json.loads(a.input.read_text())
    html_out = render(data, a.template.read_text())
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(html_out)
    print(f"wrote {a.output} ({len(html_out):,} bytes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
