#!/usr/bin/env python3
"""
Renderizador del reporte de estimación de upgrade Magento 2.

Lee los artefactos producidos por el skill m2-upgrade-estimation y rellena
el template estimate-report.html con los valores calculados.

Artefactos esperados en --report-dir:
  - pert-estimation.json   (obligatorio — producido por compute-pert.py)
  - pert-estimation.html   (obligatorio — producido por compute-pert.py)
  - signals.json           (obligatorio — producido por build-pert-input.py)
  - extension-impact-deep.json  (opcional — producido por extension-impact-deep.py)

Uso:
  render-estimate.py --report-dir DIR --template PATH --out PATH
"""
from __future__ import annotations

import argparse
import html
import json
import math
import re
import sys
import unicodedata
from pathlib import Path


def _fold(s: str) -> str:
    """Strip diacritics so 'crítica' → 'critica' for ascii class/key lookups."""
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


# ─── Helpers ────────────────────────────────────────────────────────────────

def fmt(x: float) -> str:
    """Formato numérico sin trailing zeros."""
    return f"{x:.2f}".rstrip("0").rstrip(".") if x != int(x) else str(int(x))


def ceil_days(hours: float) -> int:
    return math.ceil(hours / 8)


def load_json(path: Path) -> dict | None:
    """Carga JSON; retorna None si el archivo no existe."""
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ─── Sección: resumen y meta ─────────────────────────────────────────────────

def build_meta(pert_data: dict) -> dict[str, str]:
    """Extrae claves de meta desde pert-estimation.json."""
    meta = pert_data.get("meta", {})
    return {
        "CURRENT_VERSION": html.escape(str(meta.get("current_version", "?"))),
        "TARGET_VERSION":  html.escape(str(meta.get("target_version", "?"))),
        "CURRENT_PHP":     html.escape(str(meta.get("current_php", "?"))),
        "TARGET_PHP":      html.escape(str(meta.get("target_php", "?"))),
        "EDITION":         html.escape(str(meta.get("edition", "?"))),
    }


def build_modules_changed(signals: dict) -> str:
    val = signals.get("core_diff", {}).get("modules_changed", "?")
    return html.escape(str(val))


# ─── Sección: estimación titular ─────────────────────────────────────────────

def build_headline_estimate(pert_data: dict) -> str:
    """
    Suma E_total y CI 90% para los dos tracks (Manual y automatización).
    Retorna HTML con la línea titular.
    """
    results = pert_data.get("results", {})

    auto_label = "Asistido por automatización"

    auto_E   = sum(r["E_total"] for k, r in results.items() if auto_label in k)
    manual_E = sum(r["E_total"] for k, r in results.items() if auto_label not in k)

    # CI 90% sumado (suma de los valores de CI individuales = upper bound combinado)
    auto_ci90   = sum(r["ci"]["90%"] for k, r in results.items() if auto_label in k)
    manual_ci90 = sum(r["ci"]["90%"] for k, r in results.items() if auto_label not in k)

    auto_e_str     = fmt(auto_E)
    manual_e_str   = fmt(manual_E)
    auto_ci_str    = fmt(auto_ci90)
    manual_ci_str  = fmt(manual_ci90)

    return (
        f"Con automatización: E&nbsp;&asymp;&nbsp;<strong>{auto_e_str}h</strong> "
        f"(CI90&nbsp;{auto_ci_str}h)&nbsp;&nbsp;&middot;&nbsp;&nbsp;"
        f"Sin automatización: E&nbsp;&asymp;&nbsp;<strong>{manual_e_str}h</strong> "
        f"(CI90&nbsp;{manual_ci_str}h)"
    )


# ─── Sección: tabla de automatización ───────────────────────────────────────

def build_automation_table(signals: dict) -> str:
    """Genera filas <tr> para la tabla de cobertura de automatización."""
    rows: list[str] = []

    def row(tool: str, found: int | str, autofix: int | str) -> str:
        found_i    = int(found) if str(found).isdigit() else 0
        autofix_i  = int(autofix) if str(autofix).isdigit() else 0
        manual     = max(0, found_i - autofix_i)
        autofix_display = autofix_i if str(autofix).isdigit() else "—"
        manual_display  = manual if str(autofix).isdigit() else found_i
        return (
            f"<tr>"
            f"<td><code>{html.escape(tool)}</code></td>"
            f"<td>{html.escape(str(found))}</td>"
            f"<td>{html.escape(str(autofix_display))}</td>"
            f"<td>{html.escape(str(manual_display))}</td>"
            f"</tr>"
        )

    # Rector
    rector = signals.get("rector", {})
    if rector:
        rows.append(row("Rector", rector.get("files_changed", 0), rector.get("autofix", rector.get("files_changed", 0))))

    # UCT (Upgrade Compatibility Tool)
    uct = signals.get("uct", {})
    if uct:
        rows.append(row("UCT (Upgrade Compatibility Tool)", uct.get("findings", 0), uct.get("autofix", 0)))

    # phpcompat — only if an external count was supplied (PHPCompatibility-stable
    # predates PHP 8.3+ and is no longer run by default; Rector is the PHP signal)
    phpcompat = signals.get("phpcompat", {})
    if phpcompat.get("violations", 0):
        rows.append(row("phpcompat (PHP compatibility check)", phpcompat.get("violations", 0), 0))

    # phpstan
    phpstan = signals.get("phpstan", {})
    if phpstan:
        rows.append(row("PHPStan", phpstan.get("errors", 0), 0))

    if not rows:
        return '<tr><td colspan="4" style="color: var(--ink-quaternary); font-style: italic;">Sin datos de automatización.</td></tr>'

    return "\n      ".join(rows)


# ─── Sección: impacto en código custom ──────────────────────────────────────

_UCT_BADGE = {"CRITICAL": "critical", "ERROR": "high", "WARNING": "medium"}


def build_uct_findings(signals: dict) -> str:
    """Tabla de hallazgos UCT (API deprecada/removida) sobre el código a migrar."""
    uct = signals.get("uct", {})
    sample = uct.get("sample") or []
    total = uct.get("findings", 0)
    if not sample:
        if total:
            return (f'<p class="php-ladder-note">UCT reportó {total} hallazgo(s) pero no se '
                    f'capturó el detalle (re-correr UCT con --json-output-path).</p>')
        return '<p class="php-ladder-note">sin hallazgos UCT (herramienta ausente o 0 issues en el código a migrar).</p>'

    rows = []
    for f in sample:
        lvl = str(f.get("level", "")).upper()
        badge = _UCT_BADGE.get(lvl, "")
        loc = html.escape(str(f.get("file", "—")))
        line = f.get("line")
        loc_str = f"{loc}:{int(line)}" if isinstance(line, int) else loc
        is_delta = f.get("kind") == "upgrade-delta"
        tipo = ('<span class="badge high">upgrade</span>' if is_delta
                else '<span class="badge" style="background:var(--surface-soft);color:var(--ink-tertiary);">pre-existente</span>')
        rows.append(
            f'<tr><td><span class="badge {badge}">{html.escape(lvl.capitalize())}</span></td>'
            f'<td>{tipo}</td>'
            f'<td>{html.escape(str(f.get("message", "")))}</td>'
            f'<td><code>{loc_str}</code></td></tr>'
        )
    shown = len(sample)
    delta_n = uct.get("upgrade_delta", {}).get("findings", 0)
    preexist_n = uct.get("preexisting", {}).get("findings", total - delta_n)
    split = (f'<p class="php-ladder-note"><strong>{delta_n}</strong> son introducidos por el upgrade '
             f'(API removida/cambiada en la versión objetivo) y suman horas; '
             f'<strong>{preexist_n}</strong> son <em>deuda pre-existente</em> (no-API / @deprecated / estilo) '
             f'que ya existe en la versión actual y NO suma horas de upgrade — revisar como mejora opcional. '
             f'Mostrando {shown} de {total} (delta primero).</p>')
    return (
        f'{split}'
        '<table><thead><tr><th>Severidad</th><th>Tipo</th><th>Mensaje</th><th>Archivo:línea</th></tr></thead>'
        f'<tbody>\n        {chr(10).join(rows)}\n      </tbody></table>'
    )


def build_impact_summary(impact_data: dict | None) -> str:
    """Genera chips de resumen por severidad."""
    if impact_data is None:
        return '<p style="color: var(--ink-quaternary); font-style: italic;">sin datos — extension-impact-deep.json no encontrado.</p>'

    summary = impact_data.get("summary", {})
    custom = summary.get("custom")
    if isinstance(custom, dict):
        # v2 nested shape: derive severity from relationship (custom-owner only)
        critica = custom.get("preference", 0)
        alta    = (custom.get("plugin", 0) + custom.get("extends", 0)
                   + custom.get("implements", 0) + custom.get("virtualType", 0))
        media   = custom.get("template", 0) + custom.get("layout", 0)
        total   = critica + alta + media
    else:
        critica = summary.get("critica", summary.get("critical", 0))
        alta    = summary.get("alta",    summary.get("high", 0))
        media   = summary.get("media",   summary.get("medium", 0))
        total   = summary.get("total",   critica + alta + media)

    return (
        f'<div class="impact-summary">'
        f'<div class="impact-chip critica"><span class="count">{critica}</span> <span>Crítica</span></div>'
        f'<div class="impact-chip alta"><span class="count">{alta}</span> <span>Alta</span></div>'
        f'<div class="impact-chip media"><span class="count">{media}</span> <span>Media</span></div>'
        f'<div class="impact-chip" style="border-left: 3px solid var(--border-strong);">'
        f'<span class="count" style="font-size: 18px;">{total}</span> <span>Total</span></div>'
        f'</div>'
    )


_SEV_BADGE = {
    "critica":  '<span class="badge critical">Crítica</span>',
    "alta":     '<span class="badge high">Alta</span>',
    "media":    '<span class="badge medium">Media</span>',
    "baja":     '<span class="badge low">Baja</span>',
    "critical": '<span class="badge critical">Crítica</span>',
    "high":     '<span class="badge high">Alta</span>',
    "medium":   '<span class="badge medium">Media</span>',
    "low":      '<span class="badge low">Baja</span>',
}


def build_impact_rows(impact_data: dict | None) -> str:
    """Genera filas <tr> de los top-20 hallazgos de extensiones."""
    if impact_data is None:
        return '<tr><td colspan="4" style="color: var(--ink-quaternary); font-style: italic;">sin datos</td></tr>'

    findings = impact_data.get("findings", [])
    if not findings:
        return '<tr><td colspan="4" style="color: var(--ink-quaternary); font-style: italic;">Sin hallazgos registrados.</td></tr>'

    rows: list[str] = []
    for f in findings[:20]:
        sev_raw  = _fold(str(f.get("severidad", f.get("severity", f.get("criticality", "")))).lower())
        sev_badge = _SEV_BADGE.get(sev_raw, f'<span class="badge">{html.escape(sev_raw)}</span>')
        rel  = html.escape(str(f.get("relationship", f.get("relacion", "—"))))
        cfile = html.escape(str(f.get("custom_file", f.get("archivo_custom", "—"))))
        mtarget = html.escape(str(f.get("magento_target", f.get("target", "—"))))
        sev_cls = sev_raw if sev_raw in ("critica", "alta", "media", "baja") else ""
        rows.append(
            f'<tr class="sev-{sev_cls}">'
            f"<td>{sev_badge}</td>"
            f"<td>{rel}</td>"
            f"<td><code>{cfile}</code></td>"
            f"<td><code>{mtarget}</code></td>"
            f"</tr>"
        )
    return "\n      ".join(rows)


# ─── Sección: escalera de versiones PHP ─────────────────────────────────────

def build_php_ladder(pert_data: dict) -> str:
    """Genera la tabla <table> de la escalera PHP. Retorna nota si no hay datos."""
    ladder = pert_data.get("php_ladder")
    if not ladder:
        return '<p class="php-ladder-note">sin datos de escalera PHP — php_ladder ausente en pert-estimation.json.</p>'

    base_php   = html.escape(str(ladder.get("base_php", "?")))
    base_hours = ladder.get("base_hours", 0)
    steps      = ladder.get("steps", [])

    rows: list[str] = []
    # Fila base
    rows.append(
        f'<tr class="php-ladder-base">'
        f'<td>PHP {base_php} <em>(base objetivo)</em></td>'
        f'<td>—</td>'
        f'<td>{fmt(base_hours)}</td>'
        f'<td><span class="badge ok">medible</span></td>'
        f'</tr>'
    )
    for step in steps:
        php_ver = html.escape(str(step.get("php", "?")))
        measurable = step.get("measurable", True)
        if measurable:
            delta = step.get("delta_hours")
            cumul = step.get("cumulative")
            delta_str = fmt(delta) if delta is not None else "—"
            cumul_str = fmt(cumul) if cumul is not None else "—"
            medible_cell = '<span class="badge ok">medible</span>'
        else:
            delta_str = '<span class="php-ladder-nomeasure">no medible (tooling ausente)</span>'
            cumul_str = '<span class="php-ladder-nomeasure">—</span>'
            medible_cell = '<span class="badge warn">no medible</span>'
        rows.append(
            f'<tr>'
            f'<td>PHP {php_ver}</td>'
            f'<td>{delta_str}</td>'
            f'<td>{cumul_str}</td>'
            f'<td>{medible_cell}</td>'
            f'</tr>'
        )

    body = "\n        ".join(rows)
    rec = ladder.get("recommended_php")
    rec_html = ""
    if rec:
        rec_e = html.escape(str(rec))
        if rec != ladder.get("base_php"):
            rec_html = (f'<p class="php-ladder-rec">✅ <strong>Recomendado: apuntar a PHP {rec_e}</strong> — '
                        f'su costo marginal sobre el objetivo base es bajo y Magento lo soporta, '
                        f'conviene aprovechar este upgrade para llegar a la versión más nueva soportada.</p>')
        else:
            rec_html = (f'<p class="php-ladder-rec">Recomendado mantener PHP {rec_e} — subir un minor más no es '
                        f'medible (tooling/Magento aún no lo soportan) o excede el umbral de esfuerzo razonable.</p>')
    return (
        f'{rec_html}'
        '<table>'
        '<thead><tr>'
        '<th>PHP</th>'
        '<th>Horas marginales</th>'
        '<th>Horas acumuladas</th>'
        '<th>Medible</th>'
        '</tr></thead>'
        f'<tbody>\n        {body}\n      </tbody>'
        '</table>'
    )


# ─── Sección: desglose custom vs terceros ───────────────────────────────────

_CUSTOM_LABEL = {
    "preference":   "Preference (override de clase)",
    "plugin":       "Plugin (before/after/around)",
    "extends":      "Extends (herencia directa)",
    "implements":   "Implements (interfaz)",
    "virtualType":  "Virtual Type (DI alias)",
    "template":     "Template (.phtml override)",
    "layout":       "Layout XML (handle override)",
}


def build_impact_custom_rows(impact_data: dict | None) -> str:
    """Genera filas <tr> con counts del bloque summary.custom."""
    if impact_data is None:
        return '<tr><td colspan="2" style="color: var(--ink-quaternary); font-style: italic;">sin datos</td></tr>'

    custom = impact_data.get("summary", {}).get("custom")
    if not custom:
        # Compatibilidad con formato plano v1: no hay custom sub-dict
        return '<tr><td colspan="2" style="color: var(--ink-quaternary); font-style: italic;">sin datos de desglose custom (formato v1)</td></tr>'

    extends_risk = impact_data.get("summary", {}).get("extends_signature_risk", None)

    rows: list[str] = []
    for key, label in _CUSTOM_LABEL.items():
        count = custom.get(key, 0)
        if count == 0:
            continue
        extra = ""
        if key == "extends" and extends_risk is not None:
            extra = f'<br><small style="color: var(--sev-high);">⚠ {html.escape(str(extends_risk))} con riesgo de firma cambiada</small>'
        rows.append(
            f'<tr><td>{html.escape(label)}{extra}</td><td>{html.escape(str(count))}</td></tr>'
        )

    if not rows:
        rows.append('<tr><td colspan="2" style="color: var(--ink-quaternary); font-style: italic;">Sin relaciones custom registradas.</td></tr>')
    return "\n          ".join(rows)


def build_impact_third_party(impact_data: dict | None) -> str:
    """Genera contenido del panel de terceros."""
    if impact_data is None:
        return '<p style="color: var(--ink-quaternary); font-style: italic;">sin datos</p>'

    tp = impact_data.get("summary", {}).get("third_party")
    if not tp:
        return '<p style="color: var(--ink-quaternary); font-style: italic;">sin datos de terceros (formato v1)</p>'

    count   = tp.get("count", 0)
    vendors = tp.get("vendors", [])
    vendors_str = ", ".join(html.escape(v) for v in vendors) if vendors else "—"

    return (
        f'<p><strong>{count}</strong> extensión(es) de terceros detectadas.</p>'
        f'<div class="vendor-list">{vendors_str}</div>'
        f'<p style="font-size: 12px; color: var(--ink-tertiary); margin-top: 8px;">'
        f'El esfuerzo por extensiones de terceros = verificar si el proveedor publicó una release compatible con la versión objetivo; '
        f'no implica migración manual del código del vendor.</p>'
    )


# ─── Renderer principal ──────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Renderiza el reporte de estimación de upgrade Magento 2."
    )
    ap.add_argument("--report-dir", required=True, type=Path,
                    help="Directorio con los artefactos del skill (pert-estimation.json, signals.json, etc.)")
    ap.add_argument("--template", required=True, type=Path,
                    help="Ruta al template estimate-report.html")
    ap.add_argument("--out", required=True, type=Path,
                    help="Ruta de salida del reporte HTML renderizado")
    args = ap.parse_args()

    report_dir: Path = args.report_dir
    template_path: Path = args.template
    out_path: Path = args.out

    # ── Cargar artefactos ──────────────────────────────────────────────────
    pert_json_path = report_dir / "pert-estimation.json"
    pert_html_path = report_dir / "pert-estimation.html"
    signals_path   = report_dir / "signals.json"
    impact_path    = report_dir / "extension-impact-deep.json"

    if not pert_json_path.exists():
        print(f"[error] pert-estimation.json no encontrado en {report_dir}", file=sys.stderr)
        return 1
    if not pert_html_path.exists():
        print(f"[error] pert-estimation.html no encontrado en {report_dir}", file=sys.stderr)
        return 1
    if not signals_path.exists():
        print(f"[error] signals.json no encontrado en {report_dir}", file=sys.stderr)
        return 1

    pert_data   = json.loads(pert_json_path.read_text(encoding="utf-8"))
    pert_html   = pert_html_path.read_text(encoding="utf-8")
    signals     = json.loads(signals_path.read_text(encoding="utf-8"))
    impact_data = load_json(impact_path)

    if impact_data is None:
        print(f"[warn] extension-impact-deep.json no encontrado — sección de impacto mostrará 'sin datos'", file=sys.stderr)

    # ── Construir valores de los placeholders ──────────────────────────────
    meta = build_meta(pert_data)
    placeholders: dict[str, str] = {}
    placeholders.update(meta)
    placeholders["MODULES_CHANGED"]    = build_modules_changed(signals)
    placeholders["HEADLINE_ESTIMATE"]  = build_headline_estimate(pert_data)
    placeholders["AUTOMATION_TABLE"]   = build_automation_table(signals)
    placeholders["UCT_FINDINGS"]        = build_uct_findings(signals)
    placeholders["IMPACT_SUMMARY"]      = build_impact_summary(impact_data)
    placeholders["IMPACT_ROWS"]         = build_impact_rows(impact_data)
    placeholders["IMPACT_CUSTOM_ROWS"]  = build_impact_custom_rows(impact_data)
    placeholders["IMPACT_THIRD_PARTY"]  = build_impact_third_party(impact_data)
    placeholders["PHP_LADDER"]          = build_php_ladder(pert_data)
    # ESTIMATION_SECTION: HTML de confianza propio — NO se escapa
    placeholders["ESTIMATION_SECTION"] = pert_html

    # ── Sustituir en el template ───────────────────────────────────────────
    template = template_path.read_text(encoding="utf-8")
    rendered = template
    for key, value in placeholders.items():
        rendered = rendered.replace("{{" + key + "}}", value)

    # Detectar placeholders sin rellenar
    unfilled = re.findall(r"\{\{[A-Z_]+\}\}", rendered)
    if unfilled:
        print(f"[error] Placeholders sin rellenar: {sorted(set(unfilled))}", file=sys.stderr)
        return 1

    # ── Escribir salida ────────────────────────────────────────────────────
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")

    size_kb = out_path.stat().st_size / 1000
    print(f"[render-estimate] → {out_path} ({size_kb:.1f} KB, {len(placeholders)} placeholders)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
