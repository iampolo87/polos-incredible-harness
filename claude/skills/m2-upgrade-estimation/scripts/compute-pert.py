#!/usr/bin/env python3
"""
Statistical PERT estimation for a Magento 2 *version upgrade* effort.

Reads three-point estimates per phase from a JSON file (produced by
build-pert-input.py) and emits PERT confidence intervals in senior-dev hours.

Each phase carries two triples:
  - manual:    O / M / P            (no automation tooling)
  - automated: auto_O / auto_M / auto_P  (after Rector / UCT / phpcs auto-fixes)

Per-phase expected value E = (O + 4M + P) / 6
Per-phase standard deviation σ = (P − O) / 6
Total E = Σ E_i              Total σ = √(Σ σ_i²)   (assumes phase independence)

Confidence intervals (one-tailed upper bound, normal approximation):
  70% → E + 0.524σ   80% → E + 0.842σ   90% → E + 1.282σ   95% → E + 1.645σ
"X% chance the actual effort is ≤ this value."

Usage:
  compute-pert.py --input pert-input.json [--out-dir DIR]
Outputs <out-dir>/pert-estimation.json and pert-estimation.html
(default out-dir = the input file's directory).
"""

import argparse
import json
import math
from pathlib import Path

Z_SCORES = {"70%": 0.524, "80%": 0.842, "90%": 1.282, "95%": 1.645}

AUTO_LABEL = "Asistido por automatización"


def pert(O: float, M: float, P: float) -> tuple[float, float]:
    E = (O + 4 * M + P) / 6
    sigma = (P - O) / 6
    return E, sigma


def aggregate(rows: list[tuple]) -> dict:
    """rows = list of (label, O, M, P) — returns {'rows','E_total','sigma_total','variance_total'}"""
    detail = []
    total_E = 0.0
    total_var = 0.0
    for label, O, M, P in rows:
        E, s = pert(O, M, P)
        detail.append({"label": label, "O": O, "M": M, "P": P, "E": E, "sigma": s, "variance": s * s})
        total_E += E
        total_var += s * s
    return {"rows": detail, "E_total": total_E, "sigma_total": math.sqrt(total_var), "variance_total": total_var}


def ci(E: float, sigma: float) -> dict[str, float]:
    return {lvl: E + z * sigma for lvl, z in Z_SCORES.items()}


def ceil_days(hours: float) -> int:
    return math.ceil(hours / 8)


def fmt(x: float) -> str:
    return f"{x:.2f}".rstrip("0").rstrip(".") if x != int(x) else str(int(x))


def load_phases(data: dict) -> dict[str, list[dict]]:
    """Normalise the input 'phases' dict; each phase is a dict with the 7 fields."""
    phases = data["phases"]
    norm: dict[str, list[dict]] = {}
    for side, rows in phases.items():
        norm[side] = [
            {
                "label": p["label"],
                "O": p["O"], "M": p["M"], "P": p["P"],
                "auto_O": p.get("auto_O", p["O"]),
                "auto_M": p.get("auto_M", p["M"]),
                "auto_P": p.get("auto_P", p["P"]),
            }
            for p in rows
        ]
    return norm


def render_results_card(name: str, r: dict) -> str:
    cls = "ai" if AUTO_LABEL in name else "manual"
    cis = ci(r["E_total"], r["sigma_total"])
    return f"""
  <div class="estimation-card {cls}">
    <h3>{name}</h3>
    <div class="total"><span class="label">E (esperado)</span><span><span class="value">{fmt(r['E_total'])}</span><span class="unit">horas</span></span></div>
    <div class="total"><span class="label">σ (desv. estándar)</span><span><span class="value">{fmt(r['sigma_total'])}</span><span class="unit">horas</span></span></div>
    <div class="total"><span class="label">Person-days @ E</span><span><span class="value">{ceil_days(r['E_total'])}</span><span class="unit">días</span></span></div>
    <table style="font-size:11px; margin-top:8px;">
      <thead><tr><th>CI</th><th>Horas</th><th>Días (ceil)</th></tr></thead>
      <tbody>
        <tr><td>70%</td><td>{fmt(cis['70%'])}</td><td>{ceil_days(cis['70%'])}</td></tr>
        <tr><td>80%</td><td>{fmt(cis['80%'])}</td><td>{ceil_days(cis['80%'])}</td></tr>
        <tr><td>90%</td><td>{fmt(cis['90%'])}</td><td>{ceil_days(cis['90%'])}</td></tr>
        <tr><td>95%</td><td>{fmt(cis['95%'])}</td><td>{ceil_days(cis['95%'])}</td></tr>
      </tbody>
    </table>
  </div>"""


def build_html(meta: dict, phases: dict[str, list[dict]], results: dict[str, dict]) -> str:
    parts: list[str] = []
    parts.append('<section id="estimation">')
    parts.append('  <h2>Estimación de esfuerzo — Statistical PERT</h2>')
    cv = meta.get("current_version", "?")
    tv = meta.get("target_version", "?")
    parts.append(f'  <p>Upgrade <strong>{cv} → {tv}</strong> (PHP {meta.get("current_php","?")} → {meta.get("target_php","?")}, edición {meta.get("edition","?")}). '
                 'Se usa <strong>PERT estadístico</strong> en horas de desarrollador senior. Por cada fase damos un <strong>triple estimado</strong> — Optimista (O), Más probable (M), Pesimista (P) — y calculamos:</p>')
    parts.append('  <ul style="font-family: var(--mono); font-size: 13px; background: var(--bg); padding: 12px 24px; border-radius: 4px;">')
    parts.append('    <li><strong>E (esperado)</strong> = (O + 4M + P) / 6 — promedio ponderado, sesgado hacia M</li>')
    parts.append('    <li><strong>σ (desviación estándar)</strong> = (P − O) / 6 — espalda de la distribución beta-PERT</li>')
    parts.append('    <li><strong>E total</strong> = Σ E<sub>i</sub> (suma de fases)</li>')
    parts.append('    <li><strong>σ total</strong> = √(Σ σ<sub>i</sub>²) (asumiendo independencia entre fases)</li>')
    parts.append('    <li><strong>Intervalo de confianza X% (una cola, upper bound)</strong> = E + z<sub>X</sub> · σ — probabilidad X% de que el esfuerzo real sea ≤ ese valor</li>')
    parts.append('    <li>z-scores: 70% → 0.524 · 80% → 0.842 · 90% → 1.282 · 95% → 1.645</li>')
    parts.append('  </ul>')

    parts.append('  <h3>Resumen</h3>')
    parts.append('  <div class="estimation-grid">')
    for name, r in results.items():
        parts.append(render_results_card(name, r))
    parts.append('  </div>')

    manual_total_E = sum(r["E_total"] for n, r in results.items() if AUTO_LABEL not in n)
    auto_total_E = sum(r["E_total"] for n, r in results.items() if AUTO_LABEL in n)
    saving = manual_total_E - auto_total_E
    saving_pct = (saving / manual_total_E * 100) if manual_total_E else 0.0
    parts.append('  <div class="estimation-savings">')
    parts.append(f'    <strong>Lectura ejecutiva:</strong> con tooling de automatización (Rector, UCT, phpcs) se proyecta un esperado E = <strong>{fmt(auto_total_E)} horas</strong> ({ceil_days(auto_total_E)} días) vs sin automatización E = <strong>{fmt(manual_total_E)} horas</strong> ({ceil_days(manual_total_E)} días). Ahorro proyectado: <strong>{fmt(saving)}h (~{saving_pct:.0f}%)</strong>. Para una fecha con 90% de probabilidad de cumplir, usar el CI 90% de cada cuadro (no el E pelado).')
    parts.append('  </div>')

    for side in phases.keys():
        parts.append(f'  <h3>{side} — detalle por fase</h3>')
        parts.append('  <table>')
        parts.append('    <thead>')
        parts.append('      <tr><th rowspan="2">Fase</th><th colspan="5">Sin automatización (horas)</th><th colspan="5">Con automatización (horas)</th></tr>')
        parts.append('      <tr><th>O</th><th>M</th><th>P</th><th>E</th><th>σ</th><th>O</th><th>M</th><th>P</th><th>E</th><th>σ</th></tr>')
        parts.append('    </thead>')
        parts.append('    <tbody>')
        manual_r = results[f"{side} (Manual)"]
        auto_r = results[f"{side} ({AUTO_LABEL})"]
        for m, a in zip(manual_r["rows"], auto_r["rows"]):
            parts.append(
                f"      <tr><td>{m['label']}</td>"
                f"<td>{fmt(m['O'])}</td><td>{fmt(m['M'])}</td><td>{fmt(m['P'])}</td><td><strong>{fmt(m['E'])}</strong></td><td>{fmt(m['sigma'])}</td>"
                f"<td>{fmt(a['O'])}</td><td>{fmt(a['M'])}</td><td>{fmt(a['P'])}</td><td><strong>{fmt(a['E'])}</strong></td><td>{fmt(a['sigma'])}</td></tr>"
            )
        parts.append('    </tbody>')
        parts.append('    <tfoot>')
        parts.append(
            f"      <tr style='background: var(--bg);'><td><strong>Total</strong></td>"
            f"<td>{fmt(sum(r['O'] for r in manual_r['rows']))}</td><td>{fmt(sum(r['M'] for r in manual_r['rows']))}</td><td>{fmt(sum(r['P'] for r in manual_r['rows']))}</td>"
            f"<td><strong>{fmt(manual_r['E_total'])}</strong></td><td>σ<sub>tot</sub> = {fmt(manual_r['sigma_total'])}</td>"
            f"<td>{fmt(sum(r['O'] for r in auto_r['rows']))}</td>"
            f"<td>{fmt(sum(r['M'] for r in auto_r['rows']))}</td><td>{fmt(sum(r['P'] for r in auto_r['rows']))}</td>"
            f"<td><strong>{fmt(auto_r['E_total'])}</strong></td><td>σ<sub>tot</sub> = {fmt(auto_r['sigma_total'])}</td></tr>"
        )
        parts.append('    </tfoot>')
        parts.append('  </table>')

    parts.append('  <div class="callout">')
    parts.append('    <strong>Cómo leer PERT vs ROM:</strong> PERT da una <em>distribución</em>, no un número. Para comprometer una fecha con 90% de probabilidad usá el CI 90%; para una fecha agresiva (más riesgo) el CI 70%. El E es el promedio matemático, sirve para presupuestar pero NO para prometer.')
    parts.append('  </div>')

    parts.append('  <div class="caveats">')
    parts.append('    <strong>Leer antes de citar estos números:</strong>')
    parts.append('    <ul>')
    parts.append('      <li>±30% ROM. El método asume independencia entre fases (σ<sub>tot</sub> = √Σσ²); fases correlacionadas hacen que el RSS subestime la incertidumbre real.</li>')
    parts.append('      <li>La aproximación normal de los CIs requiere ≥ 5 fases para que el TCL aplique limpio; los lados con menos fases (QA) están al límite y sus CI 90/95% pueden estar levemente sesgados.</li>')
    parts.append('      <li>Asume <strong>1 dev + 1 QA dedicados</strong>; ley de Brooks aplica si escalás.</li>')
    parts.append('      <li>El track "con automatización" asume <strong>cobertura medida</strong> de Rector/UCT/phpcs sobre este código; herramientas no instaladas o reglas que no aplican reducen el ahorro real.</li>')
    parts.append('      <li>Excluye approvals de stakeholders, ventanas de change-management, monitoreo post-deploy, descubrimiento de regresión (bugs que QA manda al dev = iteración aparte) e integraciones externas que requieran re-verificación.</li>')
    parts.append('    </ul>')
    parts.append('  </div>')
    parts.append('</section>')
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description="PERT estimation for a Magento 2 version upgrade.")
    ap.add_argument("--input", required=True, type=Path, help="pert-input.json")
    ap.add_argument("--out-dir", type=Path, default=None, help="output dir (default: input dir)")
    args = ap.parse_args()

    data = json.loads(args.input.read_text())
    meta = data.get("meta", {})
    phases = load_phases(data)
    out_dir = args.out_dir or args.input.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, dict] = {}
    for side, rows in phases.items():
        manual_rows = [(p["label"], p["O"], p["M"], p["P"]) for p in rows]
        auto_rows = [(p["label"], p["auto_O"], p["auto_M"], p["auto_P"]) for p in rows]
        results[f"{side} (Manual)"] = aggregate(manual_rows)
        results[f"{side} ({AUTO_LABEL})"] = aggregate(auto_rows)

    for name, r in results.items():
        cis = ci(r["E_total"], r["sigma_total"])
        print(f"\n{name}\n  E = {r['E_total']:6.2f}h, σ = {r['sigma_total']:5.2f}h")
        for lvl, val in cis.items():
            print(f"  CI {lvl}: {val:6.2f}h ({ceil_days(val):2d} días)")

    out_json = out_dir / "pert-estimation.json"
    payload = {
        "meta": meta,
        "phases": phases,
        "results": {
            name: {
                "E_total": r["E_total"],
                "sigma_total": r["sigma_total"],
                "rows": r["rows"],
                "ci": ci(r["E_total"], r["sigma_total"]),
                "ci_days": {lvl: ceil_days(val) for lvl, val in ci(r["E_total"], r["sigma_total"]).items()},
                "E_days": ceil_days(r["E_total"]),
            }
            for name, r in results.items()
        },
    }
    if "php_ladder" in data:
        payload["php_ladder"] = data["php_ladder"]
    out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\n[json] {out_json}")

    out_html = out_dir / "pert-estimation.html"
    out_html.write_text(build_html(meta, phases, results))
    print(f"[html] {out_html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
