#!/usr/bin/env python3
"""TDD for parse-rector.py and parse-uct.py — counts + maintained-commercial
vendor exclusion (--exclude-vendors). Orphan/agency modules are NOT excluded."""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RECTOR = HERE.parent / "scripts" / "parse-rector.py"
UCT = HERE.parent / "scripts" / "parse-uct.py"
F_RECTOR = HERE / "fixtures" / "rector.sample.json"
F_UCT = HERE / "fixtures" / "uct.sample.json"


def run_json(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    assert r.returncode == 0, f"failed {cmd}:\n{r.stderr}"
    return json.loads(r.stdout)


def main() -> int:
    # --- rector, no exclusion: Vendor(2 files) + Amasty(1 file) ---
    rec = run_json([sys.executable, str(RECTOR), "--input", str(F_RECTOR)])
    assert rec["files_changed"] == 3, rec
    bs = rec["by_ruleset"]
    assert bs["PHP_LEVEL"] == 2 and bs["DEAD_CODE"] == 1 and bs["CODE_QUALITY"] == 1 and bs["TYPE_DECLARATION"] == 1, bs

    # rector excluding amasty (commercial) -> only Vendor counts; TypeDecl (Amasty) drops
    recx = run_json([sys.executable, str(RECTOR), "--input", str(F_RECTOR), "--exclude-vendors", "amasty,weltpixel"])
    assert recx["files_changed"] == 2, recx
    assert recx["by_ruleset"]["TYPE_DECLARATION"] == 0, recx
    assert recx["by_ruleset"]["PHP_LEVEL"] == 2, recx

    # --- uct, no exclusion: 4 issues (crit1, err2, warn1) ---
    uct = run_json([sys.executable, str(UCT), "--input", str(F_UCT), "--autofix", "8"])
    assert uct["findings"] == 4, uct
    assert uct["autofix"] == 8, uct
    assert uct["by_severity"] == {"critical": 1, "error": 2, "warning": 1}, uct["by_severity"]

    # uct excluding amasty -> 3 issues (crit1, err1, warn1)
    uctx = run_json([sys.executable, str(UCT), "--input", str(F_UCT), "--exclude-vendors", "amasty"])
    assert uctx["findings"] == 3, uctx
    assert uctx["by_severity"] == {"critical": 1, "error": 1, "warning": 1}, uctx["by_severity"]

    # sample of kept findings, severity-sorted (critical first), with message/file/line
    sample = uctx["sample"]
    assert len(sample) == 3, sample
    assert sample[0]["level"] == "CRITICAL", sample[0]
    assert "Vendor" in sample[0]["file"] and "Amasty" not in str(sample), sample
    assert sample[0]["line"] == 5 and sample[0]["message"], sample[0]

    # upgrade-delta vs pre-existing split: only "Removed API call" (CRITICAL) is delta;
    # the non-API error + deprecated warning are pre-existing (exist on current version too)
    assert uctx["upgrade_delta"]["findings"] == 1, uctx["upgrade_delta"]
    assert uctx["upgrade_delta"]["by_severity"]["critical"] == 1, uctx["upgrade_delta"]
    assert uctx["preexisting"]["findings"] == 2, uctx["preexisting"]

    print("test_parsers: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
