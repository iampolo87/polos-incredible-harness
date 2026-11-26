# Estimation framework — coefficients & automation coverage

This document is the human-readable spec that `scripts/build-pert-input.py`
implements. **Keep them in sync**: if you change a number here, change it in the
script (and vice-versa), then re-run the tests.

## Model

Each phase has a most-likely manual effort `M` (senior-dev hours) derived from a
**measured count**, plus an optimistic/pessimistic band:

```
O = 0.6 · M        P = 1.8 · M
```

The automation track scales the whole triple by measured coverage `cov ∈ [0,1]`:

```
auto_O = O · (1 − cov)   auto_M = M · (1 − cov)   auto_P = P · (1 − cov)
```

`compute-pert.py` then computes `E = (O + 4M + P)/6`, `σ = (P − O)/6`, totals,
and the confidence intervals. See that script's header for the CI math.

## Coefficients (seed defaults — recalibrate after real runs)

**Owner-aware:** only `owner == "custom"` findings drive migration hours.
Third-party vendor extensions (Amasty, WeltPixel, …) get a flat per-vendor verify
cost — you validate the vendor ships a target-compatible release, you don't migrate
their code. Generic `extends` is cheap unless the parent's *signature* changed
(`extends_signature_risk`, measured from the diff hunks).

`Migración de código custom` most-likely M (all counts custom-owner only):

```
M = 4·preference + 1.5·plugin + 0.5·extends_safe + 2·extends_signature_risk
    + 0.5·implements + 0.5·virtualType + 1·template + 1·layout
where extends_safe = extends − extends_signature_risk
```

| Phase | Most-likely M | Coverage `cov` |
|-------|---------------|----------------|
| Setup (worktree, snapshot, deps) | 3 h fixed | 0 |
| Composer + conflictos de extensiones | `1 + 1.5 · ext_conflicts` | 0.10 |
| Revisión del diff de core | `0.3 · overlap_modules` | 0.05 |
| Migración de código custom | *(formula above)* | 0.10 |
| Validación de extensiones de terceros | `4 · third_party_vendors` | 0 |
| Corrección de API deprecada | `1.0·uct_critical + 0.2·uct_error + 0.05·uct_warning` (severity-weighted; flat `0.5·findings` only if no `by_severity`) | **measured** = `uct_autofix / uct_findings` |
| Compatibilidad PHP | `0.25 · phpcompat_violations` | **measured** = `min(1, rector_PHP_LEVEL / phpcompat_violations)` |
| Modernización (quality/dead/types) | `0.1 · rector(CODE_QUALITY+DEAD_CODE+TYPE_DECLARATION)` | 0.80 |
| Resolución de errores estáticos (PHPStan) | `0.1 · max(0, errors − baseline_errors)`; **0h if no baseline** | 0.20 |
| Migración de schema/datos de BD | 4 h fixed | 0 |
| di:compile + smoke + dry-run deploy | 4 h fixed | 0 |
| **QA** Smoke pass | 6 h fixed | 0 |
| **QA** Regresión por área | `1.5 · areas` | 0 |
| **QA** Regresión de pasarelas | `3 · payment_methods` (default 3) | 0 |
| **QA** Verificación critical-path | `2 + 0.5 · preference` | 0 |

`areas` defaults to `min(20, max(5, ceil(modules_changed/12)))` when not in
`signals.qa.areas`. `overlap_modules` = distinct Magento modules referenced by
custom findings (NOT all changed core modules — that over-counts review effort).

## PHP version ladder

From `signals.php_ladder` (phpcs PHPCompatibility violations per PHP level):

```
base_hours = phpcompat(target) · 0.25 · (1 − rector_PHP_LEVEL/phpcompat(target))
per higher level i (measurable only):
  delta_i = max(0, phpcompat(i) − phpcompat(i−1)) · 0.25 · (1 − rector_autofix_i/phpcompat(i))
  cumulative_i = base_hours + Σ delta
```

Per-level `phpcompat` counts come from **Rector version-sets** (Rector knows modern
PHP; PHPCompatibility-stable does not). A level beyond Rector's known sets (>8.4 in
rector 1.x) or unsupported by Magento is `measurable:false` ("no medible"), not zero.
`recommended_php` = the highest measurable level whose marginal over base ≤ 16h — i.e.
"cheap to go further, so target it" (e.g. 8.4 when its marginal is ~0).

## Vendor scoping

Tool counts (Rector, UCT) and the custom-impact summary exclude **only maintained-
commercial vendors** (denylist: amasty, weltpixel, mirasvit, mageworx, mageplaza,
webkul, aheadworks, bss, magezon, magictoolbox, klevu — they ship target-compatible
releases). Client code AND orphaned/agency/bespoke modules (no maintained release) are
**counted as migration effort**. Default is conservative: unknown vendor ⇒ counted.
Excluded vendors only incur the flat per-vendor "verify release" cost.

## Why these coverages

- **Deprecated-API** and **PHP-compat** coverage are *measured*, not guessed — the
  whole point of running UCT + Rector. Tools absent → coverage 0, manual track stands.
- **Modernization** (0.80): Rector applies these wholesale; the dev only reviews.
- **Custom-code migration** (0.10): refactoring around a changed signature is manual.
- **Composer** (0.10): the tool surfaces conflicts but a human resolves them.
- **Third-party verify** (0): a per-vendor manual check; no automation credit.
- **PHPStan** (0.20): only the upgrade-introduced *delta* (`errors − baseline_errors`)
  is real work — the raw count includes pre-existing type/debt noise unrelated to the
  upgrade. No baseline ⇒ 0h (surfaced as a flagged risk, never silently inflated).
  Get a baseline by running PHPStan on the un-upgraded checkout.

## Dimension sanity-check (adapted from jira-estimate)

Before trusting the number, score the upgrade on five dimensions (1–5; high =
more effort/risk) and confirm the PERT total is in the same ballpark:

1. **Scope clarity** — is the target version/PHP fixed and known?
2. **Surface area** — `modules_changed` + custom_impact.total.
3. **Risk** — payment/checkout, B2B, external integrations touched?
4. **Test cost** — number of functional areas needing regression.
5. **Unknowns** — undocumented customizations, vendored libs, missing tests.

If the PERT E and the dimension intuition disagree by >2×, investigate before
quoting. Optionally run the `--judge` cross-check (two blind estimators).

## Recalibration

After a real upgrade, log **actual** dev + QA hours per phase. Compute the ratio
`actual / M` per phase and nudge the coefficients toward reality. Bump the skill
`metadata.version` on each calibration so estimates are traceable to a model
revision.
