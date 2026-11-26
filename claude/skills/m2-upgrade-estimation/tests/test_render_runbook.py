#!/usr/bin/env python3
"""TDD for render-runbook.py: turns the measured analysis into an actionable,
ordered Markdown upgrade runbook (a dev/agent reference to DO the upgrade)."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNBOOK = HERE.parent / "scripts" / "render-runbook.py"
COMPUTE = HERE.parent / "scripts" / "compute-pert.py"
SIGNALS = HERE / "fixtures" / "signals.sample.json"
PERT_IN = HERE / "fixtures" / "pert-input.sample.json"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        rd = Path(tmp)
        # produce pert-estimation.json (carries meta + php_ladder.recommended_php)
        subprocess.run([sys.executable, str(COMPUTE), "--input", str(PERT_IN), "--out-dir", str(rd)], check=True)
        (rd / "signals.json").write_text(SIGNALS.read_text())
        # impact findings: a signature-risk extends + a preference + a third-party one
        impact = {
            "summary": {
                "custom": {"preference": 1, "plugin": 1, "extends": 1, "implements": 0,
                           "virtualType": 0, "template": 0, "layout": 0},
                "third_party": {"count": 2, "vendors": ["amasty", "weltpixel"]},
                "extends_signature_risk": 1, "overlap_modules": 3, "total": 5,
            },
            "findings": [
                {"relationship": "extends", "owner": "custom", "signature_risk": True,
                 "custom_file": "app/code/Vendor/Foo/Model/Bar.php",
                 "magento_target": "Magento\\Catalog\\Model\\Product", "vendor": "Vendor"},
                {"relationship": "preference", "owner": "custom", "signature_risk": False,
                 "custom_file": "app/code/Vendor/Foo/etc/di.xml",
                 "magento_target": "Magento\\Customer\\Model\\X", "vendor": "Vendor"},
                {"relationship": "plugin", "owner": "third-party", "signature_risk": False,
                 "custom_file": "app/code/Amasty/Z/etc/di.xml", "magento_target": "Magento\\Y", "vendor": "Amasty"},
            ],
        }
        (rd / "extension-impact-deep.json").write_text(json.dumps(impact))

        out = rd / "UPGRADE-RUNBOOK.md"
        r = subprocess.run([sys.executable, str(RUNBOOK), "--report-dir", str(rd), "--out", str(out)],
                           capture_output=True, text=True)
        assert r.returncode == 0, f"runbook failed:\n{r.stderr}"
        md = out.read_text()

        # scope + recommendation
        assert "2.4.4" in md and "2.4.7-p3" in md, "versions missing"
        assert "8.4" in md, "recommended PHP missing"
        # ordered phases / automation
        assert "Rector" in md and "RECTOR_PHP_VERSION" in md, "rector step missing"
        # the signature-risk extends MUST appear as an actionable checklist item, flagged priority
        assert "app/code/Vendor/Foo/Model/Bar.php" in md, "sig-risk extends not listed"
        assert "Magento\\Catalog\\Model\\Product" in md, "magento target not listed"
        assert "- [ ]" in md, "no checklist items"
        # third-party verify step lists the commercial vendor
        assert "amasty" in md.lower() or "weltpixel" in md.lower(), "third-party verify missing"
        # third-party finding must NOT be in the migration checklist (owner=third-party)
        assert "app/code/Amasty/Z/etc/di.xml" not in md, "third-party finding wrongly in migration list"
        # pre-existing UCT debt surfaced as optional appendix (not upgrade work)
        assert "deuda" in md.lower() or "pre-exist" in md.lower(), "tech-debt appendix missing"

    print("test_render_runbook: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
