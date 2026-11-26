#!/usr/bin/env python3
"""TDD for build-pert-input.py (v2): owner-aware per-relationship coefficients,
third-party verify phase, overlap-based core review, and PHP ladder deltas.
Chain-compatible with compute-pert.py."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE.parent / "scripts" / "build-pert-input.py"
COMPUTE = HERE.parent / "scripts" / "compute-pert.py"
SIGNALS = HERE / "fixtures" / "signals.sample.json"


def approx(a, b, tol=1e-2):
    return a is not None and abs(a - b) <= tol


def phase(rows, label):
    for r in rows:
        if r["label"] == label:
            return r
    raise AssertionError(f"phase not found: {label}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "pert-input.json"
        r = subprocess.run(
            [sys.executable, str(BUILD), "--signals", str(SIGNALS), "--out", str(out)],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, f"build failed:\n{r.stderr}"
        data = json.loads(out.read_text())
        dev = data["phases"]["Developer"]
        qa = data["phases"]["QA"]

        # custom migration (owner=custom only, per-relationship):
        # 4*pref(3) + 1.5*plugin(10) + 0.5*extends_safe(40-8=32) + 2*sigrisk(8)
        # + 0.5*impl(2) + 0.5*vtype(4) + 1*(tmpl5+layout3)
        # = 12 + 15 + 16 + 16 + 1 + 2 + 8 = 70
        cm = phase(dev, "Migración de código custom")
        assert approx(cm["M"], 70.0), cm["M"]

        # third-party verify: 5 vendors * 4h = 20
        tp = phase(dev, "Validación de extensiones de terceros")
        assert approx(tp["M"], 20.0), tp["M"]

        # core review scales by overlap_modules (25), NOT modules_changed (120): 0.3*25 = 7.5
        cr = phase(dev, "Revisión del diff de core")
        assert approx(cr["M"], 7.5), cr["M"]

        # deprecated API: counts ONLY upgrade-delta (removed/changed in target), NOT
        # pre-existing non-API/deprecated debt. delta by_severity 5/15/0 ->
        # 1.0*5 + 0.2*15 + 0.05*0 = 8.0; cov=autofix12/findings60=0.2 -> auto_M=6.4
        da = phase(dev, "Corrección de API deprecada")
        assert approx(da["M"], 8.0), da["M"]
        assert approx(da["auto_M"], 8.0 * 0.8), da["auto_M"]

        # php-compat: 0.25*120=30; cov min(1,50/120) -> auto_M=30*(1-50/120)
        pc = phase(dev, "Compatibilidad PHP (8.1 → 8.3)")
        assert approx(pc["M"], 30.0) and approx(pc["auto_M"], 30 * (1 - 50 / 120)), pc

        # QA area regression unchanged: 1.5 * areas(derived from modules/12 -> min20,max5 => 10)
        ar = phase(qa, "Regresión por área")
        assert approx(ar["M"], 15.0), ar["M"]

        # PHPStan phase: sample has errors=40 and NO baseline -> 0h (informational only)
        ps = phase(dev, "Resolución de errores estáticos (PHPStan)")
        assert approx(ps["M"], 0.0), ps["M"]
        assert ps["automation"]["baseline"] is None, ps["automation"]

        # --- PHP ladder (review-coefficient model: 0.05h per rector PHP change) ---
        ladder = data["php_ladder"]
        assert ladder["base_php"] == "8.3", ladder
        # base = 120 * 0.05 = 6.0
        assert approx(ladder["base_hours"], 6.0), ladder["base_hours"]
        steps = {s["php"]: s for s in ladder["steps"]}
        # 8.4: marginal=160-120=40 -> 40*0.05=2.0 ; cumulative 8.0
        assert approx(steps["8.4"]["delta_hours"], 2.0), steps["8.4"]
        assert approx(steps["8.4"]["cumulative"], 8.0), steps["8.4"]
        # 8.5 not measurable
        assert steps["8.5"]["measurable"] is False, steps["8.5"]
        assert steps["8.5"]["delta_hours"] is None, steps["8.5"]
        # recommend the highest measurable level whose marginal over base is cheap:
        # 8.4 adds only 2h over base → recommend 8.4 (not the unmeasurable 8.5)
        assert ladder.get("recommended_php") == "8.4", ladder.get("recommended_php")

        # invariants
        for side in data["phases"].values():
            for p in side:
                for k in ("O", "M", "P", "auto_O", "auto_M", "auto_P"):
                    assert isinstance(p[k], (int, float)), (p["label"], k)
                assert p["O"] <= p["M"] <= p["P"], p["label"]
                assert p["auto_M"] <= p["M"] + 1e-9, p["label"]

        # CHAIN: compute-pert consumes it and passes php_ladder through
        c = subprocess.run(
            [sys.executable, str(COMPUTE), "--input", str(out), "--out-dir", str(tmp)],
            capture_output=True, text=True,
        )
        assert c.returncode == 0, f"compute chain failed:\n{c.stderr}"
        est = json.loads((Path(tmp) / "pert-estimation.json").read_text())
        assert "php_ladder" in est, "compute-pert must pass php_ladder through"
        assert est["php_ladder"]["base_php"] == "8.3"

        # PHPStan WITH baseline -> delta hours: errors 40, baseline 10 -> 30 * 0.1 = 3.0
        sig2 = json.loads(SIGNALS.read_text())
        sig2["phpstan"] = {"errors": 40, "baseline_errors": 10}
        s2 = Path(tmp) / "signals2.json"; s2.write_text(json.dumps(sig2))
        o2 = Path(tmp) / "pert-input2.json"
        r2 = subprocess.run([sys.executable, str(BUILD), "--signals", str(s2), "--out", str(o2)],
                            capture_output=True, text=True)
        assert r2.returncode == 0, r2.stderr
        ps2 = phase(json.loads(o2.read_text())["phases"]["Developer"], "Resolución de errores estáticos (PHPStan)")
        assert approx(ps2["M"], 3.0), ps2["M"]
        assert ps2["automation"]["upgrade_errors"] == 30, ps2["automation"]

        # PHP-compat fallback: PHPCompatibility unavailable (violations=0) -> use rector
        # PHP_LEVEL as the change count. rector PHP_LEVEL=200 -> M=0.25*200=50, cov=1.0.
        sig3 = json.loads(SIGNALS.read_text())
        sig3["phpcompat"] = {"violations": 0}
        sig3["rector"]["by_ruleset"]["PHP_LEVEL"] = 200
        s3 = Path(tmp) / "signals3.json"; s3.write_text(json.dumps(sig3))
        o3 = Path(tmp) / "pert-input3.json"
        subprocess.run([sys.executable, str(BUILD), "--signals", str(s3), "--out", str(o3)], check=True)
        pc3 = phase(json.loads(o3.read_text())["phases"]["Developer"], "Compatibilidad PHP (8.1 → 8.3)")
        assert approx(pc3["M"], 50.0), pc3["M"]
        assert approx(pc3["auto_M"], 0.0), pc3["auto_M"]

    print("test_build_pert_input: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
