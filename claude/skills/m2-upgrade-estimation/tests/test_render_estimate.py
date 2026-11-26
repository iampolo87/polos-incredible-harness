#!/usr/bin/env python3
"""TDD para render-estimate.py: template relleno correctamente con artefactos reales."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE    = Path(__file__).resolve().parent
SKILL   = HERE.parent
SCRIPTS = SKILL / "scripts"

COMPUTE_PERT = SCRIPTS / "compute-pert.py"
RENDER       = SCRIPTS / "render-estimate.py"
TEMPLATE     = SKILL / "templates" / "estimate-report.html"

FIXTURE_PERT    = HERE / "fixtures" / "pert-input.sample.json"
FIXTURE_SIGNALS = HERE / "fixtures" / "signals.sample.json"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        report_dir = Path(tmp)

        # ── 1. Generar pert-estimation.{json,html} con compute-pert.py ───────
        r = subprocess.run(
            [sys.executable, str(COMPUTE_PERT),
             "--input", str(FIXTURE_PERT),
             "--out-dir", str(report_dir)],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"compute-pert.py falló:\n{r.stderr}"
        assert (report_dir / "pert-estimation.json").exists(), "pert-estimation.json no generado"
        assert (report_dir / "pert-estimation.html").exists(), "pert-estimation.html no generado"

        # Verificar que php_ladder fue propagado por compute-pert.py
        pert_json = json.loads((report_dir / "pert-estimation.json").read_text())
        assert "php_ladder" in pert_json, "php_ladder no propagado en pert-estimation.json"
        assert pert_json["php_ladder"]["base_php"] == "8.3"

        # ── 2. Copiar signals.json al report-dir ──────────────────────────────
        shutil.copy(FIXTURE_SIGNALS, report_dir / "signals.json")

        # ── 3. Escribir extension-impact-deep.json v2 (nested summary) ────────
        impact = {
            "summary": {
                "custom": {
                    "preference": 5,
                    "plugin": 12,
                    "extends": 3,
                    "implements": 1,
                    "virtualType": 2,
                    "template": 8,
                    "layout": 4,
                },
                "third_party": {
                    "count": 3,
                    "vendors": ["amasty", "mirasvit", "klevu"],
                },
                "extends_signature_risk": 2,
                "overlap_modules": 7,
                "total": 35,
            },
            "findings": [
                {
                    "severidad": "Crítica",
                    "relationship": "Preference",
                    "custom_file": "app/code/Custom/Module/Model/Product.php",
                    "magento_target": "vendor/magento/module-catalog/Model/Product.php",
                },
                {
                    "severidad": "alta",
                    "relationship": "Plugin",
                    "custom_file": "app/code/Custom/Checkout/Plugin/Quote.php",
                    "magento_target": "vendor/magento/module-quote/Model/Quote.php",
                },
            ],
        }
        (report_dir / "extension-impact-deep.json").write_text(
            json.dumps(impact, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # ── 4. Ejecutar render-estimate.py ────────────────────────────────────
        out_html = report_dir / "estimate-report.html"
        r2 = subprocess.run(
            [sys.executable, str(RENDER),
             "--report-dir", str(report_dir),
             "--template",   str(TEMPLATE),
             "--out",        str(out_html)],
            capture_output=True, text=True,
        )
        assert r2.returncode == 0, f"render-estimate.py falló:\n{r2.stderr}\n{r2.stdout}"
        assert out_html.exists(), "El archivo de salida no fue creado"

        content = out_html.read_text(encoding="utf-8")

        # ── 5. Assertions sobre el HTML resultante ────────────────────────────

        # Versiones del fixture pert-input.sample.json
        assert "2.4.4" in content,      "Versión actual (2.4.4) no encontrada en el reporte"
        assert "2.4.7-p3" in content,   "Versión objetivo (2.4.7-p3) no encontrada en el reporte"

        # Sección de automatización
        assert "Cobertura de automatización" in content, "Sección 'Cobertura de automatización' no encontrada"

        # Sección PERT inyectada (pert-estimation.html tiene id="estimation")
        assert 'id="estimation"' in content, "Sección id='estimation' del PERT no inyectada"

        # Sección de supuestos
        assert "Supuestos" in content, "Sección 'Supuestos' no encontrada"

        # ── Nueva sección: escalera PHP ───────────────────────────────────────
        assert "Escalera de versiones PHP" in content, "Sección 'Escalera de versiones PHP' no encontrada"
        assert "8.3" in content, "PHP base (8.3) no encontrado en el reporte"
        assert "8.4" in content, "PHP step (8.4) no encontrado en la escalera"
        # La fila 8.4 debe mostrar horas marginales
        assert "6.25" in content or "6,25" in content, "Horas marginales de PHP 8.4 no encontradas"
        # La fila 8.5 debe indicar 'no medible'
        assert "no medible" in content, "Celda 'no medible' para PHP 8.5 no encontrada"
        # Recomendación de versión PHP (8.4 marginal-barato sobre el base)
        assert "Recomendado" in content and "PHP 8.4" in content, "Recomendación de PHP no renderizada"
        assert "8.5" in content, "PHP step (8.5) no encontrado en el reporte"

        # ── Desglose owner-split ──────────────────────────────────────────────
        assert "amasty" in content,  "Vendor 'amasty' no encontrado en terceros"
        assert "mirasvit" in content, "Vendor 'mirasvit' no encontrado en terceros"
        assert "klevu" in content,   "Vendor 'klevu' no encontrado en terceros"

        # Relaciones custom en la tabla de desglose
        assert "Preference" in content, "Relación 'Preference' del impact no encontrada"
        assert "Plugin" in content,     "Relación 'Plugin' no encontrada"

        # Severidad crítica renderizada
        assert "critica" in content.lower() or "crítica" in content.lower(), \
            "Severidad crítica no renderizada"

        # Summary chips derive severity from the v2 nested custom counts:
        # crítica=preference(5), alta=plugin+extends+impl+vtype(18), media=tmpl+layout(12)
        assert '<span class="count">5</span> <span>Crítica' in content, "crítica chip count wrong (v2 nested)"
        assert '<span class="count">18</span> <span>Alta' in content, "alta chip count wrong (v2 nested)"
        assert '<span class="count">12</span> <span>Media' in content, "media chip count wrong (v2 nested)"

        # Accent-folding: a "Crítica" (accented) finding must still resolve to the
        # ascii css classes — no empty sev- class, colored badge + ribbon present.
        assert 'class="sev-"' not in content, "crítica row got an empty severity class (accent bug)"
        assert "sev-critica" in content, "crítica row missing sev-critica ribbon class"
        assert "badge critical" in content, "crítica badge missing color class"

        # ── Hallazgos UCT (API deprecada/removida) listados, no solo el conteo ──
        assert "API deprecada" in content or "UCT" in content, "Sección de hallazgos UCT ausente"
        assert "removed method Magento\\Foo\\Bar::baz" in content or "removed method" in content, \
            "Mensaje de hallazgo UCT no renderizado"
        assert "app/code/Vendor/Mod/Baz.php" in content, "Archivo de hallazgo UCT no renderizado"

        # ── Sin placeholders sin rellenar ─────────────────────────────────────
        import re
        unfilled = re.findall(r"\{\{[A-Z_]+\}\}", content)
        assert not unfilled, f"Placeholders sin rellenar: {sorted(set(unfilled))}"

        # ── Auto-contenido — sin recursos externos ────────────────────────────
        content_lower = content.lower()
        assert "<script src" not in content_lower, \
            "Encontrado <script src — recurso externo no permitido"
        content_no_comments = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
        content_no_comments_lower = content_no_comments.lower()
        assert "http://" not in content_no_comments_lower, \
            "Encontrada URL http:// en el HTML (sin contar comentarios)"
        assert "https://" not in content_no_comments_lower, \
            "Encontrada URL https:// en el HTML (sin contar comentarios)"

    print("test_render_estimate: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
