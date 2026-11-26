#!/usr/bin/env python3
"""
Render a CLIENT-facing estimate (estimacion-cliente.html) — plain Spanish, no
technical jargon, approximate hours per work area. For sending to the client/sponsor.

Groups the internal PERT phases into a handful of business-language buckets and shows
rounded "≈ N h" per bucket plus a total in hours and days. Reuses the analysis the
skill already produced — reads pert-input.json (per-phase hours) + pert-estimation.json
(meta, totals, recommended PHP) from --report-dir.

Usage: render-client-estimate.py --report-dir DIR --out estimacion-cliente.html
"""

import argparse
import html
import json
import math
from pathlib import Path

# (key, client title, plain description, "qué incluye" bullet) — ordered as shown.
BUCKETS = [
    ("custom",   "Adaptación de personalizaciones a medida",
     "Ajustar el código hecho a medida para que siga funcionando en la nueva versión.",
     "Adaptar las personalizaciones y la tienda a la nueva versión."),
    ("ajustes",  "Ajustes por cambios internos de Magento",
     "Resolver los puntos donde Magento cambió su funcionamiento interno.",
     "Resolver los cambios internos de Magento que afectan a la tienda."),
    ("php",      "Actualización de PHP y modernización del código",
     "Llevar el código a la nueva versión de PHP. Gran parte se hace con herramientas automáticas.",
     "Actualizar PHP y modernizar el código (en gran parte automatizado)."),
    ("terceros", "Verificación de extensiones de proveedores",
     "Confirmar y actualizar las extensiones compradas a proveedores externos.",
     "Verificar y actualizar las extensiones de proveedores."),
    ("prep",     "Preparación, base de datos y puesta en producción",
     "Montar el entorno, migrar la base de datos y desplegar de forma segura.",
     "Preparar el entorno, migrar la base de datos y desplegar a producción."),
    ("qa",       "Pruebas y control de calidad",
     "Probar el sitio completo y verificar que todo funcione antes de salir a producción.",
     "Pruebas completas y control de calidad antes de salir a producción."),
]


def bucket_of(label: str) -> str:
    l = label.lower()
    if any(k in l for k in ("setup", "composer", "schema", "di:compile", "deploy")):
        return "prep"
    if "código custom" in l:
        return "custom"
    if "terceros" in l:
        return "terceros"
    if "php" in l or "moderniz" in l:
        return "php"
    if "deprecada" in l or "diff de core" in l or "phpstan" in l:
        return "ajustes"
    return "qa"


def round_h(x: float) -> int:
    if x <= 0:
        return 0
    if x < 10:
        return max(1, round(x))
    return int(round(x / 5.0) * 5)


def main() -> int:
    ap = argparse.ArgumentParser(description="Render a plain-Spanish client estimate.")
    ap.add_argument("--report-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--exclude-areas", default="",
                    help="CSV of bucket keys to drop from the estimate (custom,ajustes,php,terceros,prep,qa)")
    args = ap.parse_args()
    rd = args.report_dir
    exclude = {k.strip().lower() for k in args.exclude_areas.split(",") if k.strip()}

    pin = json.loads((rd / "pert-input.json").read_text())
    est = json.loads((rd / "pert-estimation.json").read_text()) if (rd / "pert-estimation.json").exists() else {}
    meta = pin.get("meta", est.get("meta", {}))
    cur, tgt = meta.get("current_version", "?"), meta.get("target_version", "?")
    rec_php = est.get("php_ladder", {}).get("recommended_php", meta.get("target_php", "?"))

    # sum auto (con automatización) and manual hours per bucket
    auto = {b[0]: 0.0 for b in BUCKETS}
    manual = {b[0]: 0.0 for b in BUCKETS}
    for side in pin.get("phases", {}).values():
        for p in side:
            b = bucket_of(p["label"])
            auto[b] += p.get("auto_M", p["M"])
            manual[b] += p["M"]

    total_auto = sum(v for k, v in auto.items() if k not in exclude)
    total_manual = sum(v for k, v in manual.items() if k not in exclude)
    days_auto = math.ceil(total_auto / 8)
    days_manual = math.ceil(total_manual / 8)

    rows, incluye, no_incluye_extra = [], [], []
    for key, title, desc, inc in BUCKETS:
        if key in exclude:
            no_incluye_extra.append(inc)
            continue
        if round_h(auto[key]) == 0 and round_h(manual[key]) == 0:
            continue
        rows.append(
            f'<tr><td><strong>{html.escape(title)}</strong><br>'
            f'<span class="desc">{html.escape(desc)}</span></td>'
            f'<td class="h">≈ {round_h(auto[key])} h</td></tr>'
        )
        incluye.append(inc)
    rows_html = "\n      ".join(rows)
    incluye_html = "\n    ".join(f"<li>{html.escape(t)}</li>" for t in incluye)
    no_incluye_html = "\n    ".join(
        [f"<li>{html.escape(t)}</li>" for t in no_incluye_extra] + [
            "<li>Nuevas funcionalidades o rediseños.</li>",
            "<li>Aprobaciones, ventanas de despliegue y capacitación.</li>",
            "<li>Tareas de los proveedores externos sobre sus propias extensiones.</li>",
        ])

    doc = f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Estimación de actualización — Magento {html.escape(cur)} → {html.escape(tgt)}</title>
<style>
  :root {{ --paper:#faf8f1; --ink:#23303a; --soft:#6b7680; --navy:#1e3a5f; --accent:#b8662e; --line:#e7e0d3; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--paper); color:var(--ink);
    font:16px/1.6 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; }}
  .wrap {{ max-width:760px; margin:0 auto; padding:48px 24px 64px; }}
  h1 {{ font-size:26px; color:var(--navy); margin:0 0 4px; }}
  .sub {{ color:var(--soft); margin:0 0 28px; }}
  h2 {{ font-size:18px; color:var(--navy); margin:34px 0 10px; }}
  table {{ width:100%; border-collapse:collapse; margin:8px 0 4px; }}
  td {{ padding:14px 12px; border-bottom:1px solid var(--line); vertical-align:top; }}
  td.h {{ text-align:right; white-space:nowrap; font-weight:700; color:var(--accent); font-size:17px; width:120px; }}
  .desc {{ color:var(--soft); font-size:14px; }}
  .total {{ background:var(--navy); color:#fff; border-radius:10px; padding:20px 24px; margin:18px 0; }}
  .total .big {{ font-size:30px; font-weight:700; }}
  .total .alt {{ color:#cdd8e4; font-size:14px; margin-top:6px; }}
  .note {{ background:#fff; border:1px solid var(--line); border-left:4px solid var(--accent);
    border-radius:8px; padding:14px 18px; margin:16px 0; font-size:14.5px; }}
  ul {{ margin:6px 0; padding-left:20px; }} li {{ margin:3px 0; }}
  .foot {{ color:var(--soft); font-size:12.5px; margin-top:36px; border-top:1px solid var(--line); padding-top:14px; }}
  @media print {{ body {{ background:#fff; }} .wrap {{ padding:0; }} }}
</style></head>
<body><div class="wrap">
  <h1>Estimación de actualización de la tienda</h1>
  <p class="sub">Magento <strong>{html.escape(cur)}</strong> → <strong>{html.escape(tgt)}</strong>
     · PHP recomendado: <strong>{html.escape(str(rec_php))}</strong></p>

  <p>Esta es una estimación de esfuerzo para actualizar la tienda a la última versión soportada de Magento.
     Las horas son aproximadas e incluyen el uso de herramientas de automatización que reducen el trabajo manual.</p>

  <h2>Trabajo estimado por área</h2>
  <table><tbody>
      {rows_html}
  </tbody></table>

  <div class="total">
    <div>Esfuerzo total estimado</div>
    <div class="big">≈ {round_h(total_auto)} horas &nbsp;·&nbsp; ~{days_auto} días de trabajo</div>
    <div class="alt">Sin herramientas de automatización sería ≈ {round_h(total_manual)} horas (~{days_manual} días).</div>
  </div>

  <div class="note">
    <strong>Recomendación:</strong> actualizar a <strong>PHP {html.escape(str(rec_php))}</strong> en la misma tarea —
    es la versión más nueva soportada por Magento y no agrega esfuerzo significativo.
  </div>

  <h2>Qué incluye</h2>
  <ul>
    {incluye_html}
  </ul>
  <h2>Qué no incluye</h2>
  <ul>
    {no_incluye_html}
  </ul>

  <p class="foot">Estimación aproximada (margen ±30%). Asume un equipo de 1 desarrollador y 1 QA dedicados.
     Las horas pueden variar según hallazgos durante la ejecución.</p>
</div></body></html>"""
    args.out.write_text(doc)
    print(f"[client-estimate] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
