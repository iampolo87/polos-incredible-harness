#!/usr/bin/env python3
"""
Phase 5b — Custom Extension Deep Scan.

For every Magento file modified in the new version, find the custom code in
`app/code/` (and any non-Magento vendor namespace) that ACTUALLY EXTENDS that
file via one of the well-known Magento extension mechanisms:
  - <preference for="...">         → Crítica
  - <plugin type="...">            → Alta
  - <virtualType type="...">       → Alta
  - class X extends Magento\\Y\\Z    → Alta
  - class X implements Magento\\Y\\Z → Alta (interface implementation)
  - template override (.phtml)     → Media
  - layout override (.xml)         → Media
  - <observer name="..." instance="..."/> on events the modified module fires → Media

Usage:
  extension-impact-deep.py --diff PATH --out-json PATH [--app-code PATH]
                            [--app-design PATH] [--out-html PATH]

Outputs:
  --out-json  — structured findings, sorted by severity
  --out-html  — pre-rendered HTML fragment for injection (optional)
"""

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SEVERITY_RANK = {"Crítica": 1, "Alta": 2, "Media": 3, "Baja": 4}

# ============================================================================
# Owner / vendor classification
# ============================================================================
# Only KNOWN maintained-commercial vendors (they ship target-compatible releases).
# Conservative on purpose: unknown / regional-agency / orphaned vendors default to
# "custom" (= must be migrated). Do NOT add a vendor here unless it reliably ships
# updated releases — otherwise its abandoned modules get wrongly excluded from the
# estimate. Override per-project with --third-party-vendors / --client-vendors.
DEFAULT_THIRD_PARTY_DENYLIST = {
    "amasty", "weltpixel", "mirasvit", "mageworx", "mageplaza", "webkul",
    "aheadworks", "bss", "bsscommerce", "magezon", "magictoolbox", "magiczoom", "klevu",
}

# Canonical relationship values
VALID_RELATIONSHIPS = frozenset(
    {"preference", "plugin", "extends", "implements", "virtualType", "template", "layout", "observer"}
)

# Signature-risk line patterns (applied to +/- lines in a diff hunk)
_SIG_RISK_RE = re.compile(
    r"(?:public|protected|private)\s+function\b"
    r"|^[+-]\s*(?:abstract\s+)?(?:public|protected|private)\s+"
    r"|^[+-]\s*function\s+"
    r"|^[+-]\s*__construct\b"
    r"|^[+-]\s*abstract\b",
    re.MULTILINE,
)


def extract_vendor(custom_file: str) -> str:
    """Return the Vendor segment (PascalCase) from a custom file path."""
    # app/code/<Vendor>/<Module>/... or code/<Vendor>/...
    m = re.search(r"(?:app/)?code/([^/]+)/", custom_file)
    if m:
        return m.group(1)
    # app/design/<area>/<Vendor>_<Module>/... → take vendor from theme dir
    m = re.search(r"app/design/[^/]+/([^/]+)/", custom_file)
    if m:
        candidate = m.group(1)
        if "_" in candidate:
            return candidate.split("_", 1)[0]
        return candidate
    # vendor/<vendor>/<package>/... — reachable once declarations come from
    # m2graph, which sees the whole tree rather than app/code alone.
    m = re.search(r"(?:^|/)vendor/([^/]+)/", custom_file)
    if m:
        return m.group(1)
    return "Unknown"


def classify_owner(
    vendor: str,
    third_party_set: set[str],
    client_vendors: set[str],
) -> str:
    """Return "custom" or "third-party"."""
    v_lower = vendor.lower()
    if v_lower in client_vendors:
        return "custom"
    if v_lower in third_party_set:
        return "third-party"
    return "custom"
SEVERITY_BADGE = {
    "Crítica": "crit-critical",
    "Alta": "crit-high",
    "Media": "crit-medium",
    "Baja": "crit-low",
}

# ============================================================================
# Helpers
# ============================================================================
def kebab_to_pascal(s: str) -> str:
    return "".join((p[:1].upper() + p[1:]) if p else "" for p in s.split("-"))


def module_namespace(module: str) -> str | None:
    """Map vendor/magento/<module> directory name → top-level PHP namespace."""
    if module == "framework":
        return "Magento\\Framework"
    if module.startswith("module-"):
        return f"Magento\\{kebab_to_pascal(module[len('module-'):])}"
    if module.startswith("framework-"):
        return f"Magento\\Framework\\{kebab_to_pascal(module[len('framework-'):])}"
    # magento2-base, magento2-ee-base, ece-tools, magento-cloud-*, theme-* and
    # quality-patches / magento-coding-standard / magento-zf-mvc do not contribute
    # to the `Magento\<Module>\` namespace tree the way regular modules do.
    return None


def module_id(module: str) -> str | None:
    """vendor/magento/module-X → Magento_X for template/layout overrides."""
    if module.startswith("module-"):
        return f"Magento_{kebab_to_pascal(module[len('module-'):])}"
    return None


def file_to_fqcn(module: str, rel_path: str) -> str | None:
    """vendor/magento/module-X/Block/Foo.php → Magento\\X\\Block\\Foo"""
    if not rel_path.endswith(".php"):
        return None
    ns = module_namespace(module)
    if not ns:
        return None
    cls_path = rel_path[:-4].replace("/", "\\")
    return f"{ns}\\{cls_path}"


# ============================================================================
# Diff rendering
# ============================================================================
def render_diff_lines(block: str) -> str:
    out = []
    for line in block.split("\n"):
        escaped = html.escape(line)
        if line.startswith("+++") or line.startswith("---") or line.startswith("diff -ruN "):
            out.append(f'<span class="diff-header">{escaped}</span>')
        elif line.startswith("+"):
            out.append(f'<span class="add">{escaped}</span>')
        elif line.startswith("-"):
            out.append(f'<span class="del">{escaped}</span>')
        elif line.startswith("@@"):
            out.append(f'<span class="hunk">{escaped}</span>')
        else:
            out.append(escaped)
    return "\n".join(out)


# ============================================================================
# Findings
# ============================================================================
def m2graph_targeting(project_root: Path, targets: set[str]) -> list[dict] | None:
    """Ask m2graph which declarations aim at `targets`, or None if unavailable.

    m2graph resolves the whole config graph — vendor included, disabled modules
    excluded, merge order applied — where the fallback scan below only walks
    app/code. On a real store the difference is large: for three core classes on
    one project, 33 of 35 declarations came from vendor/ and would be invisible
    to an app/code-only scan.
    """
    binary = shutil.which("m2graph")
    if not binary or not targets:
        return None
    try:
        result = subprocess.run(
            [binary, "--project", str(project_root), "targeting", "--json", "--stdin"],
            input="\n".join(sorted(targets)),
            capture_output=True, text=True, timeout=300,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode not in (0, 1) or not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except ValueError:
        return None


M2GRAPH_NOTES = {
    "preference": "Reemplaza la clase entera; cualquier cambio de firma en el método público del padre rompe el proyecto.",
    "plugin": "Intercepta uno o varios métodos públicos; verificar que las firmas (params + retorno) no hayan cambiado.",
    "virtualType": "virtualType apunta a una clase modificada; chequear args del constructor.",
}
M2GRAPH_SEVERITY = {"preference": "Crítica", "plugin": "Alta", "virtualType": "Alta"}


def add_finding(findings: list, *, custom_file: str, custom_class: str,
                magento_target: str, relationship: str, severity: str,
                notes: str = "", detail: str = "",
                third_party_set: set | None = None,
                client_vendors: set | None = None) -> None:
    """Append a finding with owner/vendor/detail fields.

    `relationship` must be one of VALID_RELATIONSHIPS; callers may pass the
    legacy `"plugin (Name::foo)"` form — this function normalises it and moves
    the name detail into `detail`.
    `third_party_set` / `client_vendors` default to empty sets when omitted.
    """
    if third_party_set is None:
        third_party_set = set()
    if client_vendors is None:
        client_vendors = set()

    # Normalise relationship: strip any parenthetical suffix into detail
    rel_base = relationship.split(" ", 1)[0]
    if rel_base not in VALID_RELATIONSHIPS:
        # e.g. "template" from "template override (frontend)" → keep as "template"
        for canonical in VALID_RELATIONSHIPS:
            if relationship.lower().startswith(canonical):
                rel_base = canonical
                break
    if not detail:
        paren_m = re.search(r"\((.+)\)", relationship)
        if paren_m:
            detail = paren_m.group(1)

    vendor = extract_vendor(custom_file)
    owner = classify_owner(vendor, third_party_set, client_vendors)

    findings.append({
        "severity": severity,
        "severity_rank": SEVERITY_RANK[severity],
        "relationship": rel_base,
        "detail": detail,
        "vendor": vendor,
        "owner": owner,
        "custom_file": custom_file,
        "custom_class": custom_class,
        "magento_target": magento_target,
        "notes": notes,
        "signature_risk": False,  # filled in Step 3b for extends/implements+custom
    })


def normalize_class(s: str) -> str:
    return s.strip().lstrip("\\").replace("/", "\\")


# ============================================================================
# PHP class resolution
# ============================================================================
class_decl_re = re.compile(
    r"^(?:abstract\s+|final\s+)*class\s+(\w+)"
    r"(?:\s+extends\s+([\w\\]+))?"
    r"(?:\s+implements\s+([\w\\,\s]+?))?\s*\{",
    re.MULTILINE,
)
namespace_re = re.compile(r"^namespace\s+([\w\\]+);", re.MULTILINE)
use_re = re.compile(r"^use\s+([\w\\]+)(?:\s+as\s+(\w+))?;", re.MULTILINE)
dispatch_re = re.compile(r"->dispatch\(\s*['\"]([a-z][a-z0-9_]+)['\"]")


def resolve_class(name: str, namespace: str, use_map: dict[str, str]) -> str:
    name = name.strip()
    if name.startswith("\\"):
        return name.lstrip("\\")
    parts = name.split("\\", 1)
    first = parts[0]
    if first in use_map:
        if len(parts) > 1:
            return f"{use_map[first]}\\{parts[1]}"
        return use_map[first]
    if "\\" in name:
        return name  # already namespaced (or use was missing — best effort)
    return f"{namespace}\\{name}" if namespace else name


# ============================================================================
# HTML rendering
# ============================================================================
WHY_TEMPLATES = {
    "preference": (
        "La clase custom <code>{custom}</code> <strong>reemplaza completamente</strong> a "
        "<code>{magento}</code> vía <code>&lt;preference for=...&gt;</code>. Si el diff abajo "
        "modifica firmas de métodos públicos (params, tipos, return) o el constructor, el "
        "reemplazo se rompe en runtime. Inspección obligatoria."
    ),
    "plugin": (
        "El plugin <code>{custom}</code> intercepta uno o varios métodos de <code>{magento}</code>. "
        "Si el diff abajo modificó la firma de algún método interceptado, los métodos "
        "<code>before/around/after</code> del plugin pueden romperse o recibir argumentos distintos. "
        "Cross-checkear los nombres de método interceptados en la clase custom contra los métodos "
        "modificados abajo."
    ),
    "virtualType": (
        "El virtualType <code>{custom}</code> apunta a <code>{magento}</code>. Si el constructor "
        "Magento ganó nuevos parámetros requeridos, la declaración del virtualType necesita "
        "actualizarse para inyectar esas dependencias."
    ),
    "extends": (
        "La clase <code>{custom}</code> hereda directamente de <code>{magento}</code>. Si el diff "
        "abajo cambió el constructor, métodos <code>protected</code>, o propiedades de instancia, "
        "la herencia puede romperse. Especial atención a cambios en <code>__construct()</code>."
    ),
    "implements": (
        "La clase <code>{custom}</code> implementa la interfaz <code>{magento}</code>. Si el diff "
        "abajo agregó o cambió métodos requeridos, la implementación queda incompleta y PHP "
        "falla con <code>cannot instantiate</code>."
    ),
    "template": (
        "El template <code>{custom}</code> es un override del template Magento <code>{magento}</code>. "
        "El override copió la versión vieja del template. Si el diff abajo cambió estructura "
        "(nuevos bloques <code>data-bind</code>, escapado <code>$escaper-&gt;escapeHtml()</code> agregado, "
        "secciones nuevas), el override queda desactualizado — puede generar bugs visuales o de "
        "comportamiento, y en el peor caso introducir vulnerabilidades XSS si el escapado nuevo "
        "del upstream no se replica."
    ),
    "layout": (
        "El layout XML <code>{custom}</code> es un override de <code>{magento}</code>. Si el diff "
        "abajo modifica containers o blocks referenciados, el layout custom puede fallar al "
        "renderizar o producir elementos huérfanos."
    ),
    "observer": (
        "El observer <code>{custom}</code> está registrado sobre el evento <code>{magento}</code>. "
        "La clase Magento que dispara ese evento fue modificada en p10 — si cambió el array de "
        "parámetros pasado al <code>dispatch()</code> (claves agregadas, renombradas o tipos cambiados), "
        "el observer recibe data distinta y puede acceder a índices que ya no existen."
    ),
}


def lookup_finding_diff(f: dict, modified_php_paths: dict, template_vendor_path: dict,
                        layout_vendor_path: dict, event_source_file: dict,
                        file_diff_blocks: dict) -> str | None:
    """Return rendered HTML diff for the Magento target of this finding."""
    rel = f["relationship"]  # already canonical
    target = f["magento_target"]
    detail = f.get("detail", "")
    vendor_path: str | None = None
    if rel in ("preference", "plugin", "virtualType", "extends", "implements"):
        vendor_path = modified_php_paths.get(target)
    elif rel == "template":
        area = detail or "frontend"
        if "::" in target:
            mid, tpl_rel = target.split("::", 1)
            vendor_path = template_vendor_path.get((mid, area, tpl_rel))
    elif rel == "layout":
        if "::" in target:
            mid, sub = target.split("::", 1)
            m_area = re.match(r"view/(\w+)/layout/(.+)", sub)
            if m_area:
                vendor_path = layout_vendor_path.get((mid, m_area.group(1), m_area.group(2)))
    elif rel == "observer":
        ev_m = re.match(r"event '([^']+)'", target)
        if ev_m:
            vendor_path = event_source_file.get(ev_m.group(1))
    if vendor_path:
        return file_diff_blocks.get(vendor_path)
    return None


def render_finding_article(f: dict, modified_php_paths: dict, template_vendor_path: dict,
                           layout_vendor_path: dict, event_source_file: dict,
                           file_diff_blocks: dict, file_diff_line_counts: dict) -> str:
    badge_cls = SEVERITY_BADGE[f["severity"]]
    sev_lower = f["severity"].lower().replace("í", "i")  # css-friendly
    rel_base = f["relationship"]  # already canonical
    detail = f.get("detail", "")
    custom_escaped = html.escape(f["custom_class"])
    magento_escaped = html.escape(f["magento_target"])
    # For templates/layouts the custom_class is a placeholder "(template)"/"(layout)";
    # substitute the actual file path in the WHY text so it reads cleanly.
    why_custom = custom_escaped
    if rel_base in ("template", "layout"):
        why_custom = html.escape(f["custom_file"])
    why = WHY_TEMPLATES.get(rel_base, f["notes"]).format(
        custom=why_custom, magento=magento_escaped,
    )
    diff_html = lookup_finding_diff(f, modified_php_paths, template_vendor_path,
                                    layout_vendor_path, event_source_file, file_diff_blocks)
    if diff_html:
        target = f["magento_target"]
        diff_lookup_key = None
        if rel_base in ("preference", "plugin", "virtualType", "extends", "implements"):
            diff_lookup_key = modified_php_paths.get(target)
        elif rel_base == "template":
            area = detail or "frontend"
            if "::" in target:
                mid, tpl_rel = target.split("::", 1)
                diff_lookup_key = template_vendor_path.get((mid, area, tpl_rel))
        elif rel_base == "layout":
            if "::" in target:
                mid, sub = target.split("::", 1)
                m_area = re.match(r"view/(\w+)/layout/(.+)", sub)
                if m_area:
                    diff_lookup_key = layout_vendor_path.get((mid, m_area.group(1), m_area.group(2)))
        elif rel_base == "observer":
            ev_m = re.match(r"event '([^']+)'", target)
            if ev_m:
                diff_lookup_key = event_source_file.get(ev_m.group(1))
        line_count = file_diff_line_counts.get(diff_lookup_key, 0) if diff_lookup_key else 0
        diff_section = (
            f'<details class="finding-diff">'
            f'<summary>📂 Ver diff Magento que justifica el riesgo ({line_count} líneas)</summary>'
            f'{diff_html}'
            f'</details>'
        )
    else:
        diff_section = '<p class="empty">⚠ No se encontró diff embebible para este target. Verificar manualmente en <code>raw/magento.diff</code>.</p>'

    rel_display = f"{rel_base} ({detail})" if detail else rel_base
    sig_badge = (' <span class="sig-risk" title="Signature risk detected">⚠ sig</span>'
                 if f.get("signature_risk") else "")
    owner_badge = f' <span class="owner-{f.get("owner", "custom")}">{f.get("owner", "custom")}</span>'

    return (
        f'<article class="extension-finding sev-{sev_lower}">'
        f'  <header>'
        f'    <span class="badge {badge_cls}">{f["severity"]}</span> '
        f'    <span class="relationship">{html.escape(rel_display)}</span>'
        f'    {sig_badge}{owner_badge}'
        f'  </header>'
        f'  <div class="target-line">'
        f'    <strong>Custom:</strong> <code>{html.escape(f["custom_file"])}</code> '
        f'    → <code>{custom_escaped}</code><br>'
        f'    <strong>Target Magento:</strong> <code>{magento_escaped}</code>'
        f'  </div>'
        f'  <div class="why"><strong>Por qué afecta:</strong> {why}</div>'
        f'  {diff_section}'
        f'</article>'
    )


# ============================================================================
# Summary helpers
# ============================================================================
def _empty_summary() -> dict:
    return {
        "custom": {
            "preference": 0, "plugin": 0, "extends": 0, "implements": 0,
            "virtualType": 0, "template": 0, "layout": 0,
        },
        "third_party": {"count": 0, "vendors": []},
        "extends_signature_risk": 0,
        "overlap_modules": 0,
        "total": 0,
    }


def _build_summary(findings: list[dict]) -> dict:
    """Build the nested summary from the findings list."""
    custom_counts: dict[str, int] = {
        "preference": 0, "plugin": 0, "extends": 0, "implements": 0,
        "virtualType": 0, "template": 0, "layout": 0,
    }
    tp_vendors: set[str] = set()
    tp_count = 0
    sig_risk_count = 0
    overlap_modules: set[str] = set()

    for f in findings:
        rel = f["relationship"]
        owner = f.get("owner", "custom")
        if owner == "custom":
            if rel in custom_counts:
                custom_counts[rel] += 1
            if f.get("signature_risk") and rel in ("extends", "implements"):
                sig_risk_count += 1
            # Overlap modules: extract from magento_target
            target = f.get("magento_target", "")
            mod = _extract_module_key(target)
            if mod:
                overlap_modules.add(mod)
        else:
            tp_count += 1
            tp_vendors.add(f.get("vendor", "Unknown").lower())

    return {
        "custom": custom_counts,
        "third_party": {"count": tp_count, "vendors": sorted(tp_vendors)},
        "extends_signature_risk": sig_risk_count,
        "overlap_modules": len(overlap_modules),
        "total": len(findings),
    }


def _extract_module_key(target: str) -> str | None:
    """Best-effort: extract the Magento module identifier from a FQCN or path.

    Examples:
      Magento\\Catalog\\Block\\Product → "Catalog"
      Magento\\Framework\\Model\\... → "Framework"
      Magento_Catalog::template.phtml → "Catalog"
      vendor/magento/module-catalog/... → "Catalog"
    """
    # FQCN: Magento\\<Module>\\...
    m = re.match(r"Magento\\([^\\]+)", target)
    if m:
        return m.group(1)
    # Module-id: Magento_Catalog::...
    m = re.match(r"Magento_([^:]+)", target)
    if m:
        return m.group(1)
    # vendor path: vendor/magento/module-catalog-graph-ql/...
    m = re.search(r"vendor/magento/([^/]+)/", target)
    if m:
        return kebab_to_pascal(m.group(1).replace("module-", ""))
    return None


# ============================================================================
# Main
# ============================================================================
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 5b — Custom Extension Deep Scan. Finds custom code that "
                    "extends Magento core files modified in a diff.",
    )
    parser.add_argument("--diff", required=True, metavar="PATH",
                        help="Path to the magento.diff file")
    parser.add_argument("--app-code", default="./app/code", metavar="PATH",
                        help="Path to app/code directory (default: ./app/code)")
    parser.add_argument("--app-design", default="./app/design", metavar="PATH",
                        help="Path to app/design directory (default: ./app/design)")
    parser.add_argument("--out-json", required=True, metavar="PATH",
                        help="Output path for extension-impact-deep.json")
    parser.add_argument("--out-html", default=None, metavar="PATH",
                        help="Output path for extension-impact-deep.html (optional)")
    parser.add_argument("--third-party-vendors", default="", metavar="CSV",
                        help="Comma-separated vendor names to force-classify as third-party "
                             "(merged with built-in denylist: amasty,weltpixel,mirasvit,…)")
    parser.add_argument("--client-vendors", default="", metavar="CSV",
                        help="Comma-separated vendor names to force-classify as custom "
                             "(overrides denylist; e.g. Vendor,ClientCo)")
    args = parser.parse_args()

    diff_file = Path(args.diff)
    app_code = Path(args.app_code)
    app_design = Path(args.app_design)
    output_json = Path(args.out_json)
    output_html = Path(args.out_html) if args.out_html else None

    # Build owner-classification sets
    extra_tp = {v.strip().lower() for v in args.third_party_vendors.split(",") if v.strip()}
    third_party_set: set[str] = DEFAULT_THIRD_PARTY_DENYLIST | extra_tp
    client_vendors: set[str] = {v.strip().lower() for v in args.client_vendors.split(",") if v.strip()}
    # client_vendors overrides denylist: remove them from third_party_set
    third_party_set -= client_vendors

    # ============================================================================
    # Step 1 — Parse diff: list of (module, rel_path)
    # ============================================================================
    if not diff_file.exists() or diff_file.stat().st_size == 0:
        print("[1] Diff file empty or missing — producing zero findings")
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps({
            "summary": _empty_summary(),
            "findings": [],
        }, indent=2, ensure_ascii=False))
        if output_html:
            output_html.parent.mkdir(parents=True, exist_ok=True)
            output_html.write_text("")
        return 0

    diff_text = diff_file.read_text(errors="ignore")
    if not diff_text.strip():
        print("[1] Diff file is blank — producing zero findings")
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps({
            "summary": _empty_summary(),
            "findings": [],
        }, indent=2, ensure_ascii=False))
        if output_html:
            output_html.parent.mkdir(parents=True, exist_ok=True)
            output_html.write_text("")
        return 0

    modified_files: list[tuple[str, str]] = []
    for line in diff_text.splitlines():
        if not line.startswith("diff -ruN ") and not line.startswith("diff --git "):
            continue
        m = re.search(r"vendor/magento/([^/]+)/(\S+)", line)
        if not m:
            continue
        modified_files.append((m.group(1), m.group(2)))

    print(f"[1] {len(modified_files)} modified Magento files detected from diff")

    # Build sets of modified items
    modified_fqcns: set[str] = set()
    modified_php_paths: dict[str, str] = {}  # fqcn → "vendor/magento/<module>/<rel>"
    modified_templates: set[tuple[str, str, str]] = set()  # (module_id, area, tpl_rel)
    modified_layouts: set[tuple[str, str, str]] = set()  # (module_id, area, layout_name)
    template_vendor_path: dict[tuple[str, str, str], str] = {}
    layout_vendor_path: dict[tuple[str, str, str], str] = {}

    for module, rel in modified_files:
        if rel.endswith(".php"):
            fqcn = file_to_fqcn(module, rel)
            if fqcn:
                modified_fqcns.add(fqcn)
                modified_php_paths[fqcn] = f"vendor/magento/{module}/{rel}"
        elif rel.endswith(".phtml"):
            mid = module_id(module)
            if not mid:
                continue
            for area in ("frontend", "adminhtml", "base"):
                marker = f"view/{area}/templates/"
                if marker in rel:
                    tpl_rel = rel.split(marker, 1)[1]
                    key = (mid, area, tpl_rel)
                    modified_templates.add(key)
                    template_vendor_path[key] = f"vendor/magento/{module}/{rel}"
                    break
        elif rel.endswith(".xml") and "/layout/" in rel:
            mid = module_id(module)
            if not mid:
                continue
            if "view/frontend/layout/" in rel:
                area = "frontend"
            elif "view/adminhtml/layout/" in rel:
                area = "adminhtml"
            elif "view/base/layout/" in rel:
                area = "base"
            else:
                continue
            layout_name = rel.split("/layout/", 1)[1]
            key = (mid, area, layout_name)
            modified_layouts.add(key)
            layout_vendor_path[key] = f"vendor/magento/{module}/{rel}"

    # ============================================================================
    # Step 1b — Build per-file diff lookup map (path → rendered HTML)
    # ============================================================================
    file_diff_blocks: dict[str, str] = {}
    file_diff_line_counts: dict[str, int] = {}
    _file_blocks = re.split(r"^(?=diff )", diff_text, flags=re.MULTILINE)
    for block in _file_blocks:
        if not (block.startswith("diff -ruN ") or block.startswith("diff --git ")):
            continue
        first = block.split("\n", 1)[0]
        m_path = re.search(r"vendor/magento/(\S+)", first)
        if not m_path:
            continue
        key = f"vendor/magento/{m_path.group(1)}"
        file_diff_blocks[key] = f'<pre class="diff">{render_diff_lines(block)}</pre>'
        file_diff_line_counts[key] = block.count("\n")

    print(f"[1b] Built diff lookup for {len(file_diff_blocks)} files")
    print(f"    {len(modified_fqcns)} modified PHP classes (FQCNs)")
    print(f"    {len(modified_templates)} modified templates")
    print(f"    {len(modified_layouts)} modified layouts")

    # ============================================================================
    # Step 2 — Scan app/code for di.xml extensions
    # ============================================================================
    findings: list[dict] = []

    di_xml_count = 0
    graph_rows = m2graph_targeting(app_code.parent, modified_fqcns)
    if graph_rows is not None:
        skipped_core = 0
        for row in graph_rows:
            if row.get("disabled"):
                continue
            # A Magento module plugging a Magento class is Adobe's problem, not
            # the integrator's — they ship both sides of that change together.
            if (row.get("module") or "").startswith("Magento_"):
                skipped_core += 1
                continue
            kind = row["kind"]
            add_finding(
                findings,
                custom_file=row["file"],
                custom_class=row["source"] or "(sin clase)",
                magento_target=row["target"],
                relationship=kind,
                detail=row.get("detail", ""),
                severity=M2GRAPH_SEVERITY[kind],
                notes=M2GRAPH_NOTES[kind],
                third_party_set=third_party_set,
                client_vendors=client_vendors,
            )
        kept = sum(
            1 for f in findings if f["relationship"] in ("preference", "plugin", "virtualType")
        )
        third_party = sum(
            1 for r in graph_rows
            if r.get("origin") == "vendor" and not (r.get("module") or "").startswith("Magento_")
        )
        print(
            f"[2] m2graph: {kept} XML-based extensions "
            f"({third_party} from third-party vendor/ modules, invisible to an "
            f"app/code-only scan; {skipped_core} Magento-core declarations skipped)"
        )
    elif app_code.exists():
        print("[2] m2graph unavailable — falling back to app/code-only di.xml scan")
        for di_xml in app_code.rglob("etc/**/di.xml"):
            di_xml_count += 1
            try:
                tree = ET.parse(di_xml)
                root = tree.getroot()
            except ET.ParseError:
                continue
            custom_rel = str(di_xml.relative_to(app_code.parent))

            for pref in root.iter("preference"):
                for_attr = normalize_class(pref.get("for", ""))
                type_attr = pref.get("type", "")
                if for_attr and for_attr in modified_fqcns:
                    add_finding(
                        findings,
                        custom_file=custom_rel,
                        custom_class=type_attr,
                        magento_target=for_attr,
                        relationship="preference",
                        severity="Crítica",
                        notes="Reemplaza la clase entera; cualquier cambio de firma en el método público del padre rompe el proyecto.",
                        third_party_set=third_party_set,
                        client_vendors=client_vendors,
                    )

            for type_elem in root.iter("type"):
                type_name = normalize_class(type_elem.get("name", ""))
                if type_name not in modified_fqcns:
                    continue
                for plugin in type_elem.findall("plugin"):
                    add_finding(
                        findings,
                        custom_file=custom_rel,
                        custom_class=plugin.get("type", ""),
                        magento_target=type_name,
                        relationship="plugin",
                        detail=plugin.get("name", ""),
                        severity="Alta",
                        notes="Intercepta uno o varios métodos públicos; verificar que las firmas (params + retorno) no hayan cambiado.",
                        third_party_set=third_party_set,
                        client_vendors=client_vendors,
                    )

            for vt in root.iter("virtualType"):
                vt_target = normalize_class(vt.get("type", ""))
                if vt_target in modified_fqcns:
                    add_finding(
                        findings,
                        custom_file=custom_rel,
                        custom_class=vt.get("name", "(virtualType)"),
                        magento_target=vt_target,
                        relationship="virtualType",
                        severity="Alta",
                        notes="virtualType apunta a una clase modificada; chequear args del constructor.",
                        third_party_set=third_party_set,
                        client_vendors=client_vendors,
                    )

    if graph_rows is None:
        print(f"[2] Scanned {di_xml_count} di.xml files — {sum(1 for f in findings if f['relationship'] in ('preference', 'plugin', 'virtualType'))} XML-based extensions found")

    # ============================================================================
    # Step 3 — Scan app/code PHP for extends / implements
    # ============================================================================
    php_count = 0
    extends_implements_found = 0

    if app_code.exists():
        for php_file in app_code.rglob("*.php"):
            php_count += 1
            try:
                content = php_file.read_text(errors="ignore")
            except Exception:
                continue

            ns_match = namespace_re.search(content)
            namespace = ns_match.group(1) if ns_match else ""

            use_map: dict[str, str] = {}
            for m in use_re.finditer(content):
                full = m.group(1)
                alias = m.group(2)
                short = alias or full.rsplit("\\", 1)[-1]
                use_map[short] = full

            for m in class_decl_re.finditer(content):
                cls_name = m.group(1)
                extends = m.group(2)
                implements = m.group(3)

                custom_fqcn = f"{namespace}\\{cls_name}" if namespace else cls_name
                custom_rel = str(php_file.relative_to(app_code.parent))

                if extends:
                    parent_fqcn = resolve_class(extends, namespace, use_map)
                    if parent_fqcn in modified_fqcns:
                        add_finding(
                            findings,
                            custom_file=custom_rel,
                            custom_class=custom_fqcn,
                            magento_target=parent_fqcn,
                            relationship="extends",
                            severity="Alta",
                            notes="La clase custom hereda directamente de una clase Magento modificada. Verificar constructor + métodos protected/public.",
                            third_party_set=third_party_set,
                            client_vendors=client_vendors,
                        )
                        extends_implements_found += 1

                if implements:
                    for impl in re.split(r"\s*,\s*", implements.strip()):
                        impl = impl.strip()
                        if not impl:
                            continue
                        impl_fqcn = resolve_class(impl, namespace, use_map)
                        if impl_fqcn in modified_fqcns:
                            add_finding(
                                findings,
                                custom_file=custom_rel,
                                custom_class=custom_fqcn,
                                magento_target=impl_fqcn,
                                relationship="implements",
                                severity="Alta",
                                notes="La clase custom implementa una interfaz Magento modificada. Verificar que todos los métodos requeridos estén presentes.",
                                third_party_set=third_party_set,
                                client_vendors=client_vendors,
                            )
                            extends_implements_found += 1

    print(f"[3] Scanned {php_count} PHP files — {extends_implements_found} extends/implements hits")

    # ============================================================================
    # Step 3b — Signature-risk pass for extends/implements custom findings
    # ============================================================================
    sig_risk_checked = 0
    for f in findings:
        if f["relationship"] not in ("extends", "implements"):
            continue
        if f.get("owner") != "custom":
            continue
        parent_path = modified_php_paths.get(f["magento_target"])
        if not parent_path:
            # parent not in diff → unchanged, no risk
            continue
        diff_block = file_diff_blocks.get(parent_path, "")
        # Strip HTML tags from the rendered diff to check raw +/- lines
        plain_block = re.sub(r"<[^>]+>", "", diff_block)
        sig_risk = bool(_SIG_RISK_RE.search(plain_block))
        f["signature_risk"] = sig_risk
        sig_risk_checked += 1

    print(f"[3b] Signature-risk check: {sig_risk_checked} custom extends/implements findings evaluated; "
          f"{sum(1 for f in findings if f.get('signature_risk'))} with signature_risk=true")

    # ============================================================================
    # Step 4 — Template overrides (skip if app/design missing)
    # ============================================================================
    template_overrides = 0
    if app_design.exists():
        for mid, area, tpl_rel in modified_templates:
            search_root = app_design / area
            if not search_root.exists():
                continue
            for override in search_root.rglob(f"{mid}/templates/{tpl_rel}"):
                add_finding(
                    findings,
                    custom_file=str(override.relative_to(app_design.parent)),
                    custom_class="(template)",
                    magento_target=f"{mid}::{tpl_rel}",
                    relationship="template",
                    detail=area,
                    severity="Media",
                    notes=f"Override del template `.phtml` cuyo origen Magento fue modificado. Diff visual recomendado: comparar el template custom contra el nuevo de vendor.",
                    third_party_set=third_party_set,
                    client_vendors=client_vendors,
                )
                template_overrides += 1
    else:
        print(f"[4] app/design path '{app_design}' not found — skipping template scan")

    print(f"[4] Found {template_overrides} template overrides on modified templates")

    # ============================================================================
    # Step 5 — Layout overrides (skip if app/design missing)
    # ============================================================================
    layout_overrides = 0
    if app_design.exists():
        for mid, area, layout_name in modified_layouts:
            search_root = app_design / area
            if not search_root.exists():
                continue
            for override in search_root.rglob(f"{mid}/layout/{layout_name}"):
                add_finding(
                    findings,
                    custom_file=str(override.relative_to(app_design.parent)),
                    custom_class="(layout)",
                    magento_target=f"{mid}::view/{area}/layout/{layout_name}",
                    relationship="layout",
                    detail=area,
                    severity="Media",
                    notes="Override de layout XML modificado. Validar que los containers/blocks referenciados sigan existiendo.",
                    third_party_set=third_party_set,
                    client_vendors=client_vendors,
                )
                layout_overrides += 1

    print(f"[5] Found {layout_overrides} layout overrides on modified layouts")

    # ============================================================================
    # Step 5b — events.xml observers
    # Heuristic: scan modified Magento PHP files for dispatch() calls.
    # The vendor files are looked up relative to app_code's grandparent (project
    # root). If they don't exist (e.g., no worktree), this step is silently skipped.
    # ============================================================================
    dispatched_events: set[str] = set()
    event_source_file: dict[str, str] = {}
    project_root_guess = app_code.parent  # best-effort: assume PROJECT_ROOT/app/code

    for fqcn, magento_path in modified_php_paths.items():
        src_path = project_root_guess / magento_path
        if not src_path.exists():
            continue
        try:
            content = src_path.read_text(errors="ignore")
        except Exception:
            continue
        for m in dispatch_re.finditer(content):
            ev_name = m.group(1)
            dispatched_events.add(ev_name)
            event_source_file.setdefault(ev_name, magento_path)

    observer_hits = 0
    if app_code.exists():
        for events_xml in app_code.rglob("etc/**/events.xml"):
            try:
                tree = ET.parse(events_xml)
                root = tree.getroot()
            except ET.ParseError:
                continue
            custom_rel = str(events_xml.relative_to(app_code.parent))
            for ev in root.iter("event"):
                ev_name = ev.get("name", "")
                if ev_name in dispatched_events:
                    for obs in ev.findall("observer"):
                        add_finding(
                            findings,
                            custom_file=custom_rel,
                            custom_class=obs.get("instance", "(unknown)"),
                            magento_target=f"event '{ev_name}'",
                            relationship="observer",
                            detail=obs.get("name", ""),
                            severity="Media",
                            notes="Observer registrado sobre un evento que es despachado por una clase Magento modificada. Si cambió la firma del array de parámetros del dispatch, el observer puede recibir data distinta.",
                            third_party_set=third_party_set,
                            client_vendors=client_vendors,
                        )
                        observer_hits += 1

    print(f"[5b] Detected {len(dispatched_events)} events dispatched by modified Magento classes; {observer_hits} custom observers on those events")

    # ============================================================================
    # Step 6 — Sort by severity then alphabetically
    # ============================================================================
    findings.sort(key=lambda f: (f["severity_rank"], f["custom_file"], f["magento_target"]))

    print(f"[6] Total findings: {len(findings)}")
    sev_dist: dict[str, int] = {}
    for f in findings:
        sev_dist[f["severity"]] = sev_dist.get(f["severity"], 0) + 1
    print(f"    By severity: {sev_dist}")
    rel_dist: dict[str, int] = {}
    for f in findings:
        rel_dist[f["relationship"]] = rel_dist.get(f["relationship"], 0) + 1
    print(f"    By relationship: {rel_dist}")

    summary = _build_summary(findings)

    # Severity counts for HTML (kept as convenience locals)
    def _sev_count(label: str) -> int:
        label_n = label.lower()
        for k, v in sev_dist.items():
            if k.lower() == label_n:
                return v
        return 0

    # ============================================================================
    # Step 7 — Write JSON
    # ============================================================================
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps({
        "summary": summary,
        "findings": findings,
    }, indent=2, ensure_ascii=False))
    print(f"[7] Wrote {output_json}")

    # ============================================================================
    # Step 8 — Write HTML fragment (optional)
    # ============================================================================
    if output_html is None:
        return 0

    fragment_parts = [
        '<section id="extension-deep">',
        "  <h2>Análisis profundo de extensiones afectadas</h2>",
        "  <p>Esta sección lista <strong>cada archivo de código custom (en <code>app/code/</code> o themes bajo <code>app/design/</code>) que extiende explícitamente una funcionalidad Magento cuyo archivo fuente fue modificado</strong>. Se contemplan los mecanismos canónicos de extensión: <code>preference</code>, <code>plugin</code>, <code>virtualType</code>, <code>extends</code>/<code>implements</code> en PHP, y overrides de template/layout. Ordenado por severidad descendente.</p>",
        '  <div class="stat-grid">',
        f'    <div class="stat-card"><div class="label">Hallazgos totales</div><div class="value">{len(findings)}</div></div>',
        f'    <div class="stat-card"><div class="label">Severidad Crítica</div><div class="value danger">{_sev_count("crítica")}</div></div>',
        f'    <div class="stat-card"><div class="label">Severidad Alta</div><div class="value warn">{_sev_count("alta")}</div></div>',
        f'    <div class="stat-card"><div class="label">Severidad Media</div><div class="value">{_sev_count("media")}</div></div>',
        f'    <div class="stat-card"><div class="label">Clases Magento modificadas</div><div class="value">{len(modified_fqcns)}</div></div>',
        f'    <div class="stat-card"><div class="label">Archivos PHP custom escaneados</div><div class="value">{php_count}</div></div>',
        f'    <div class="stat-card"><div class="label">di.xml escaneados</div><div class="value">{di_xml_count}</div></div>',
        f'    <div class="stat-card"><div class="label">Eventos dispatched por código modificado</div><div class="value">{len(dispatched_events)}</div></div>',
        f'    <div class="stat-card"><div class="label">Observers custom sobre esos eventos</div><div class="value {"warn" if observer_hits else "ok"}">{observer_hits}</div></div>',
        "  </div>",
        "  <h4>Distribución por tipo de relación</h4>",
        "  <ul>",
    ]
    for rel_kind in sorted(rel_dist.keys(), key=lambda k: -rel_dist[k]):
        fragment_parts.append(f"    <li><code>{html.escape(rel_kind)}</code>: <strong>{rel_dist[rel_kind]}</strong></li>")
    fragment_parts.append("  </ul>")

    fragment_parts.extend([
        "  <h3>Hallazgos (ordenados por severidad)</h3>",
        "  <p>Cada hallazgo abajo trae <strong>(1)</strong> la severidad y relación, <strong>(2)</strong> archivo custom + clase/artefacto + target Magento, <strong>(3)</strong> una explicación de <em>por qué este cambio afecta al código custom</em>, y <strong>(4)</strong> un toggle con el git diff exacto del archivo Magento modificado — la evidencia técnica que justifica el riesgo.</p>",
    ])
    if not findings:
        fragment_parts.append('  <p class="empty">Ningún hallazgo — el código custom no extiende ninguna clase, template ni layout modificado. ¡Buenas noticias!</p>')
    else:
        fragment_parts.extend(
            render_finding_article(f, modified_php_paths, template_vendor_path,
                                   layout_vendor_path, event_source_file,
                                   file_diff_blocks, file_diff_line_counts)
            for f in findings
        )
    fragment_parts.extend([
        '  <div class="caveats">',
        "    <strong>Interpretación:</strong>",
        "    <ul>",
        "      <li><strong>Crítica (preference)</strong>: la clase custom <em>reemplaza completamente</em> a la Magento modificada. Si Magento cambió la firma de un método público, el reemplazo se rompe en runtime. Inspección obligatoria de cada hallazgo.</li>",
        "      <li><strong>Alta (plugin / virtualType / extends / implements)</strong>: la clase custom depende de la API pública/protected de la clase Magento. Cambios de firma o métodos quitados pueden romperla. Verificar a la luz del diff embebido en la sección Módulos modificados.</li>",
        "      <li><strong>Media (template / layout override / observer)</strong>: el override no se rompe automáticamente, pero puede quedar desactualizado si el template upstream cambió estructura (nuevos bloques, atributos data-bind, escapado distinto). Para observers, si el dispatch upstream cambió el array de parámetros, el observer recibe data distinta.</li>",
        "    </ul>",
        "    <strong>Mecanismos NO escaneados (revisión manual recomendada):</strong>",
        "    <ul>",
        "      <li><code>extension_attributes.xml</code> — atributos de extensión sobre interfaces Magento modificadas</li>",
        "      <li><code>webapi.xml</code> — overrides de rutas REST que puedan colisionar con cambios upstream</li>",
        "      <li><code>view/*/ui_component/*.xml</code> — overrides de UI components que pueden romper si Magento cambió la estructura del component</li>",
        "      <li><code>db_schema.xml</code> — schemas custom contra tablas Magento que pueden colisionar con cambios upstream</li>",
        "      <li><code>requirejs-config.js</code> mixins — mixins sobre archivos JS que Magento puede haber cambiado</li>",
        "      <li><code>csp_whitelist.xml</code> — relevante específicamente porque <code>module-csp</code> aparece modificado</li>",
        "      <li><code>crontab.xml</code> — overrides de cron jobs que apuntan a clases con firmas cambiadas</li>",
        "      <li>Resolución de <code>class_alias()</code> y autoload legacy</li>",
        "    </ul>",
        "  </div>",
        "</section>",
    ])

    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text("\n".join(fragment_parts))
    print(f"[8] Wrote {output_html}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
