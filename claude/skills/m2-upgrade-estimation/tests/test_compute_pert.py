#!/usr/bin/env python3
"""TDD for compute-pert.py: PHASES read from JSON, math intact, automation labels."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "compute-pert.py"
FIXTURE = HERE / "fixtures" / "pert-input.sample.json"


def approx(a: float, b: float, tol: float = 1e-3) -> bool:
    return abs(a - b) <= tol


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--input", str(FIXTURE), "--out-dir", str(out)],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"script failed:\n{r.stderr}"

        data = json.loads((out / "pert-estimation.json").read_text())
        res = data["results"]

        # Manual dev: O=10,M=20,P=60 -> E=(10+80+60)/6=25, sigma=(60-10)/6=8.3333
        dev_m = res["Developer (Manual)"]
        assert approx(dev_m["E_total"], 25.0), dev_m["E_total"]
        assert approx(dev_m["sigma_total"], 50 / 6), dev_m["sigma_total"]
        # CI 90% = E + 1.282*sigma
        assert approx(dev_m["ci"]["90%"], 25 + 1.282 * (50 / 6)), dev_m["ci"]["90%"]

        # Automation-assisted dev: O=4,M=8,P=24 -> E=10, sigma=20/6
        dev_a = res["Developer (Asistido por automatización)"]
        assert approx(dev_a["E_total"], 10.0), dev_a["E_total"]
        assert approx(dev_a["sigma_total"], 20 / 6), dev_a["sigma_total"]

        # QA manual: O=2,M=4,P=12 -> E=5
        assert approx(res["QA (Manual)"]["E_total"], 5.0)

        # meta carried through
        assert data["meta"]["target_version"] == "2.4.7-p3"

        # php_ladder passed through from input unchanged
        assert data.get("php_ladder", {}).get("base_php") == "8.3", data.get("php_ladder")

        # HTML emitted, automation-labelled, valid section
        html = (out / "pert-estimation.html").read_text()
        assert 'id="estimation"' in html
        assert "automatización" in html
        assert "IA" not in html.replace("automatización", ""), "stray 'IA' label remains"

    print("test_compute_pert: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
