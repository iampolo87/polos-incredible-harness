#!/usr/bin/env python3
"""TDD for render-client-estimate.py: a plain-Spanish, non-technical client estimate
with approximate hours per work area. No PERT/σ/tool jargon."""
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLIENT = HERE.parent / "scripts" / "render-client-estimate.py"
COMPUTE = HERE.parent / "scripts" / "compute-pert.py"
PERT_IN = HERE / "fixtures" / "pert-input.sample.json"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        rd = Path(tmp)
        subprocess.run([sys.executable, str(COMPUTE), "--input", str(PERT_IN), "--out-dir", str(rd)], check=True)
        # render-client reads pert-input.json + pert-estimation.json from report-dir
        (rd / "pert-input.json").write_text(PERT_IN.read_text())
        out = rd / "estimacion-cliente.html"
        r = subprocess.run([sys.executable, str(CLIENT), "--report-dir", str(rd), "--out", str(out)],
                           capture_output=True, text=True)
        assert r.returncode == 0, f"client render failed:\n{r.stderr}"
        h = out.read_text()

        # Spanish, client-facing scope
        assert "Estimación" in h and "2.4.4" in h and "2.4.7-p3" in h, "scope/title missing"
        # work-area buckets in plain language (not phase labels / no jargon)
        assert "Pruebas" in h or "control de calidad" in h.lower(), "QA bucket missing"
        assert "hora" in h.lower(), "hours not shown"
        # a total + a day figure
        assert "Total" in h or "total" in h, "total missing"
        assert "día" in h.lower(), "days figure missing"
        # PHP recommendation in plain language
        assert "8.4" in h, "PHP recommendation missing"
        # NO technical jargon leaking to the client
        for jargon in ("σ", "PERT", "rector", "Rector", "UCT", "PHPStan", "auto_M", "signature_risk"):
            assert jargon not in h, f"technical jargon leaked to client view: {jargon}"
        # self-contained
        assert "<script src" not in h.lower() and "http://" not in h and "https://" not in h, "not self-contained"
        assert "{{" not in h, "unfilled placeholder"

        # default includes the QA area row
        assert "<strong>Pruebas y control de calidad</strong>" in h, "QA area row missing by default"

        # --exclude-areas qa: QA area row gone, hours drop, QA moved to 'no incluye'
        out2 = rd / "estimacion-cliente-noqa.html"
        r2 = subprocess.run([sys.executable, str(CLIENT), "--report-dir", str(rd),
                             "--out", str(out2), "--exclude-areas", "qa"],
                            capture_output=True, text=True)
        assert r2.returncode == 0, r2.stderr
        h2 = out2.read_text()
        assert "<strong>Pruebas y control de calidad</strong>" not in h2, "QA still in area table after exclude"
        # the custom bucket should still be there
        assert "Adaptación de personalizaciones a medida" in h2, "custom area wrongly dropped"

    print("test_render_client: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
