#!/usr/bin/env python3
"""
Map measured upgrade signals (signals.json) -> PERT phase input (pert-input.json).

v2 model — owner-aware. Only CUSTOM-owner findings count as migration effort;
third-party vendor extensions get a flat per-vendor "verify the vendor ships a
target-compatible release" phase, NOT per-finding hours. Generic `extends` is
cheap (verify/recompile) unless the parent's signature actually changed
(`extends_signature_risk`, measured by the scanner). Core review scales by the
modules custom code actually overlaps, not every changed core module.

Each phase has a most-likely manual effort M (senior-dev hours), an O/P band
(O = 0.6·M, P = 1.8·M), and an automation coverage `cov ∈ [0,1]` (auto = ×(1−cov)).

It also computes a PHP version LADDER: base hours at the target PHP plus the
marginal delta of going further (8.4, 8.5, ...), measured from per-level phpcs
violation counts and Rector auto-fix coverage.

These coefficients are SEED DEFAULTS — recalibrate after a real upgrade and bump
the skill version. See references/estimation-framework.md (keep in sync).

Usage:
  build-pert-input.py --signals signals.json --out pert-input.json
"""

import argparse
import json
import math
from pathlib import Path

# --- ROM band width (O/P as multiples of the most-likely M) ------------------
OM_LO = 0.6
OM_HI = 1.8

# --- per-finding manual effort, CUSTOM owner only (senior-dev hours) ---------
H_PREFERENCE = 4.0        # custom preference fully replaces a (changed) core class
H_PLUGIN = 1.5            # custom plugin around a changed method
H_EXTENDS_SAFE = 0.5      # custom extends a changed module, parent signature UNCHANGED → verify/recompile
H_EXTENDS_SIGRISK = 2.0   # custom extends and the parent signature DID change → real refactor
H_IMPLEMENTS = 0.5        # custom implements a changed interface (verify)
H_VIRTUALTYPE = 0.5
H_TEMPLATE = 1.0          # custom template override on a changed template
H_LAYOUT = 1.0            # custom layout override on a changed layout
H_TP_VENDOR = 4.0         # flat: verify ONE third-party vendor ships a target release + bump

# --- other phases ------------------------------------------------------------
H_PER_OVERLAP_MODULE = 0.3   # core-diff review, per module custom code overlaps
H_PER_PHPCOMPAT = 0.25       # PHP-version incompatibility fix
H_PER_MODERNIZATION = 0.1    # code-quality / dead-code / type-decl change
H_PHP_LADDER = 0.05          # review/validate one rector-auto-applied PHP change at a level
PHP_REC_THRESHOLD = 16.0     # recommend going to a higher PHP if its marginal over base ≤ this (h)
H_PER_UCT_FINDING = 0.5      # deprecated/removed-API fix (flat fallback, no severity)
# UCT severity-weighted (CRITICAL = real removal, ERROR = non-API/likely break,
# WARNING = deprecated-but-works). "non-API" errors are often low-risk, hence light.
H_UCT_CRITICAL = 1.0
H_UCT_ERROR = 0.2
H_UCT_WARNING = 0.05
H_PER_PHPSTAN = 0.1          # fix one upgrade-introduced PHPStan error (delta vs baseline)
H_PER_EXT_CONFLICT = 1.5     # composer extension version conflict
H_PER_AREA = 1.5             # QA regression per functional area
H_PER_PAYMENT = 3.0          # QA regression per payment method

SETUP_M = 3.0
DB_MIGRATION_M = 4.0
COMPILE_DEPLOY_M = 4.0
SMOKE_M = 6.0

COV_COMPOSER = 0.10
COV_CORE_REVIEW = 0.05
COV_CUSTOM_MIGRATION = 0.10
COV_TP_VERIFY = 0.0
COV_MODERNIZATION = 0.80
COV_PHPSTAN = 0.20           # some PHPStan fixes ride along with Rector / are mechanical


def safe_div(a, b):
    return a / b if b else 0.0


def triple(M, cov):
    M = round(M, 2)
    cov = max(0.0, min(1.0, cov))
    return {
        "O": round(OM_LO * M, 2),
        "M": M,
        "P": round(OM_HI * M, 2),
        "auto_O": round(OM_LO * M * (1 - cov), 2),
        "auto_M": round(M * (1 - cov), 2),
        "auto_P": round(OM_HI * M * (1 - cov), 2),
        "coverage": round(cov, 4),
    }


def phase(label, M, cov, prov=None):
    p = {"label": label, **triple(M, cov)}
    if prov:
        p["automation"] = prov
    return p


def build_dev(s, meta):
    ci = s.get("custom_impact", {})
    rector = s.get("rector", {}).get("by_ruleset", {})
    uct = s.get("uct", {})
    phpcompat = s.get("phpcompat", {})
    composer = s.get("composer", {})

    preference = ci.get("preference", 0)
    plugin = ci.get("plugin", 0)
    extends = ci.get("extends", 0)
    implements = ci.get("implements", 0)
    vtype = ci.get("virtualType", 0)
    template = ci.get("template", 0)
    layout = ci.get("layout", 0)
    sigrisk = ci.get("extends_signature_risk", 0)
    extends_safe = max(0, extends - sigrisk)
    overlap = ci.get("overlap_modules", 0)
    tp_vendors = ci.get("third_party_vendors", 0)

    custom_M = (
        H_PREFERENCE * preference
        + H_PLUGIN * plugin
        + H_EXTENDS_SAFE * extends_safe
        + H_EXTENDS_SIGRISK * sigrisk
        + H_IMPLEMENTS * implements
        + H_VIRTUALTYPE * vtype
        + H_TEMPLATE * template
        + H_LAYOUT * layout
    )

    uct_findings = uct.get("findings", 0)
    cov_deprecated = safe_div(uct.get("autofix", 0), uct_findings)
    # Count ONLY upgrade-delta findings (API removed/changed in the target). Pre-existing
    # non-API/@deprecated/style findings exist on the CURRENT version too — they are tech
    # debt, not upgrade-introduced work, so they contribute 0 upgrade hours (surfaced
    # separately in the report). Falls back to total by_severity for older signal files.
    uct_delta = uct.get("upgrade_delta", {}).get("by_severity")
    uct_preexisting = uct.get("preexisting", {}).get("findings", 0)
    uct_sev = uct_delta if uct_delta is not None else uct.get("by_severity", {})
    if uct_sev:
        uct_M = (H_UCT_CRITICAL * uct_sev.get("critical", 0)
                 + H_UCT_ERROR * uct_sev.get("error", 0)
                 + H_UCT_WARNING * uct_sev.get("warning", 0))
    else:
        uct_M = H_PER_UCT_FINDING * uct_findings
    # PHPCompatibility (stable 9.x) predates PHP 8.3+ and is often unavailable, so
    # when it reports nothing fall back to Rector's PHP_LEVEL count as the change
    # count — those changes are Rector-auto-fixable (coverage ≈ 1).
    rector_php = rector.get("PHP_LEVEL", 0)
    phpcompat_violations = phpcompat.get("violations", 0) or rector_php
    cov_phpcompat = min(1.0, safe_div(rector_php, phpcompat_violations))
    modern_count = rector.get("CODE_QUALITY", 0) + rector.get("DEAD_CODE", 0) + rector.get("TYPE_DECLARATION", 0)
    ext_conflicts = composer.get("extension_conflicts", 0)

    # PHPStan: only the DELTA introduced by the upgrade is real effort. Without a
    # baseline (errors on the CURRENT version) the raw count conflates pre-existing
    # debt, so we contribute 0h and flag it — the count is still surfaced.
    phpstan = s.get("phpstan", {})
    ps_errors = phpstan.get("errors", 0)
    ps_baseline = phpstan.get("baseline_errors")  # None when not measured
    if ps_baseline is None:
        ps_upgrade = 0
        ps_prov = {"tool": "phpstan", "errors": ps_errors, "baseline": None,
                   "note": "sin baseline — informativo, no suma horas; correr PHPStan contra la versión actual para el delta real"}
    else:
        ps_upgrade = max(0, ps_errors - ps_baseline)
        ps_prov = {"tool": "phpstan", "errors": ps_errors, "baseline": ps_baseline, "upgrade_errors": ps_upgrade}

    return [
        phase("Setup (worktree, snapshot, deps)", SETUP_M, 0.0),
        phase("Composer + conflictos de extensiones", 1.0 + H_PER_EXT_CONFLICT * ext_conflicts, COV_COMPOSER,
              {"ext_conflicts": ext_conflicts}),
        phase("Revisión del diff de core", H_PER_OVERLAP_MODULE * overlap, COV_CORE_REVIEW,
              {"overlap_modules": overlap}),
        phase("Migración de código custom", custom_M, COV_CUSTOM_MIGRATION,
              {"preference": preference, "plugin": plugin, "extends_safe": extends_safe,
               "extends_signature_risk": sigrisk, "implements": implements,
               "virtualType": vtype, "template": template, "layout": layout}),
        phase("Validación de extensiones de terceros", H_TP_VENDOR * tp_vendors, COV_TP_VERIFY,
              {"third_party_vendors": tp_vendors}),
        phase("Corrección de API deprecada", uct_M, cov_deprecated,
              {"tool": "uct", "upgrade_delta_findings": uct.get("upgrade_delta", {}).get("findings", 0),
               "preexisting_debt_findings": uct_preexisting, "total_found": uct_findings,
               "note": "solo cuenta API removida/cambiada en la versión objetivo; lo no-API/@deprecated es deuda pre-existente (0h de upgrade)"}),
        phase(f"Compatibilidad PHP ({meta.get('current_php','?')} → {meta.get('target_php','?')})",
              H_PER_PHPCOMPAT * phpcompat_violations, cov_phpcompat,
              {"tool": "rector+phpcs", "found": phpcompat_violations, "autofix": rector.get("PHP_LEVEL", 0)}),
        phase("Modernización (code quality / dead code / tipos)", H_PER_MODERNIZATION * modern_count, COV_MODERNIZATION,
              {"tool": "rector", "found": modern_count}),
        phase("Resolución de errores estáticos (PHPStan)", H_PER_PHPSTAN * ps_upgrade, COV_PHPSTAN, ps_prov),
        phase("Migración de schema/datos de BD", DB_MIGRATION_M, 0.0),
        phase("di:compile + smoke + dry-run de deploy", COMPILE_DEPLOY_M, 0.0),
    ]


def build_qa(s):
    modules = s.get("core_diff", {}).get("modules_changed", 0)
    critica = s.get("custom_impact", {}).get("preference", 0)
    qa = s.get("qa", {})
    areas = qa.get("areas") or min(20, max(5, math.ceil(modules / 12)))
    payment_methods = qa.get("payment_methods", 3)
    return [
        phase("Smoke pass completo", SMOKE_M, 0.0),
        phase("Regresión por área", H_PER_AREA * areas, 0.0, {"areas": areas}),
        phase("Regresión de pasarelas de pago", H_PER_PAYMENT * payment_methods, 0.0,
              {"payment_methods": payment_methods}),
        phase("Verificación de critical-path", 2.0 + 0.5 * critica, 0.0, {"preferences": critica}),
    ]


def compute_php_ladder(s):
    """Base hours at the target PHP plus the marginal delta of each higher level.

    `phpcompat` per level = count of PHP-version changes at/up-to that level (from
    Rector's version sets, which know modern PHP; PHPCompatibility-stable does not).
    Those changes are Rector-auto-applied, so the ladder hours represent REVIEW /
    validation effort (H_PHP_LADDER each), not hand-writing — hence it does not
    vanish under automation. The ladder is informational: it is NOT summed into the
    PERT total (the migration itself lives in the Compatibilidad PHP phase)."""
    ladder = s.get("php_ladder")
    if not ladder:
        return None
    ladder = sorted(ladder, key=lambda x: x.get("php", ""))
    base = ladder[0]
    base_changes = base.get("phpcompat", 0)
    base_hours = round(base_changes * H_PHP_LADDER, 2)

    steps = []
    prev = base
    cumulative = base_hours
    for lvl in ladder[1:]:
        if not lvl.get("measurable", False):
            steps.append({"php": lvl["php"], "delta_hours": None, "cumulative": None, "measurable": False})
            continue
        marginal = max(0, lvl.get("phpcompat", 0) - prev.get("phpcompat", 0))
        delta = round(marginal * H_PHP_LADDER, 2)
        cumulative = round(cumulative + delta, 2)
        steps.append({"php": lvl["php"], "delta_hours": delta, "cumulative": cumulative,
                      "marginal_changes": marginal, "measurable": True})
        prev = lvl

    # Recommend the highest contiguous measurable level whose marginal cost over
    # the base target stays within the threshold — i.e. "free-ish to go further".
    recommended = base["php"]
    for st in steps:
        if st["measurable"] and (st["cumulative"] - base_hours) <= PHP_REC_THRESHOLD:
            recommended = st["php"]
        else:
            break
    return {"base_php": base["php"], "base_hours": base_hours, "base_changes": base_changes,
            "recommended_php": recommended, "steps": steps}


def main() -> int:
    ap = argparse.ArgumentParser(description="Build PERT input from measured upgrade signals.")
    ap.add_argument("--signals", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    s = json.loads(args.signals.read_text())
    out = {
        "meta": s.get("meta", {}),
        "phases": {"Developer": build_dev(s, s.get("meta", {})), "QA": build_qa(s)},
    }
    ladder = compute_php_ladder(s)
    if ladder:
        out["php_ladder"] = ladder

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"[pert-input] {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
