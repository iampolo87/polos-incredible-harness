---
name: m2-upgrade-estimation
description: 'Estimate the effort (in senior-dev hours, with PERT confidence intervals)
  of upgrading a Magento 2 store from one version to another. Uses the most accurate
  diff-based method — materialize the target version in a git worktree, diff core,
  scan custom-code impact — and runs automation tools (Rector, Adobe UCT, PHPStan)
  to measure how much manual work they remove, discounting the estimate accordingly.
  Produces a self-contained HTML report (Spanish). Trigger: When scoping/quoting a
  Magento 2 version upgrade (e.g. 2.4.4 → 2.4.7), estimating upgrade hours for a budget
  or Jira epic, or assessing how much Rector/UCT automation will save before committing
  to an upgrade.

  '
license: Apache-2.0
metadata:
  author: polo
  version: 0.5.0
---



# Magento 2 Version-Upgrade Effort Estimation

## Overview

Produces a defensible **senior-dev-hour** estimate for a Magento 2 version upgrade.
Method = *diff-based* (most accurate): materialize the target version, diff the
core, find which custom code is impacted, then run the upgrade-automation tools to
**measure** how much they auto-fix. Effort is modelled with Statistical PERT
(O/M/P → E, σ, CI 70/80/90/95%), with a parallel "with automation" track whose
per-phase discount is the *measured* coverage of Rector/UCT/phpcs — not a guess.

This is the **estimation** counterpart to `magento-security-upgrade` (which targets
-pX security patches and produces a full code-diff report). It reuses that skill's
diff pipeline and PERT engine.

## When to Use

- Scoping / quoting a version upgrade (2.4.4 → 2.4.7, PHP 8.1 → 8.3, etc.).
- Estimating upgrade hours for a budget, SOW, or Jira epic.
- Deciding whether Rector/UCT automation is worth wiring before an upgrade.

**Do NOT use for:** executing the actual upgrade (estimation only); a single -pX
security patch (use `magento-security-upgrade`); non-Magento PHP projects.

## Prerequisites (verify before running)

- `auth.json` present (composer needs Magento repo auth to download the target).
- Git working tree clean (a worktree is created for the target version).
- Python 3.10+ (scripts are stdlib-only).
- **Analysis tools — install STANDALONE, not in the project vendor.** The project's
  Magento autoload (gitignored `app/etc/*` registration files) breaks tools run from
  its `vendor/bin`, and PHPCompatibility conflicts inside the M2 tree. Use a throwaway
  dir and point `--vendor-bin` / `--uct-bin` at it:
  ```bash
  composer --working-dir=/tmp/m2est-tools require rector/rector:^1.2 squizlabs/php_codesniffer --ignore-platform-reqs
  # Adobe UCT (EE-licensed; uses your repo.magento.com keys from auth.json):
  COMPOSER_AUTH="$(cat auth.json)" composer create-project \
    --repository=https://repo.magento.com/ magento/upgrade-compatibility-tool /tmp/m2est-uct --ignore-platform-reqs
  ```
  Each tool is optional; a missing one zero-fills its signal (state which ran in the report).
- **PHPCompatibility is NOT used** — its latest stable (9.3) predates PHP 8.3+. Rector's
  version sets are the PHP signal instead.

## Vendor scoping (IMPORTANT)

Effort is counted for code the **team must migrate**, which is NOT just the client's own
vendor namespace. Only **maintained-commercial** vendors (Amasty, WeltPixel, Mirasvit,
Aheadworks, … — they ship target-compatible releases) are excluded and get a flat
per-vendor "verify release" cost. **Everything else is counted**: client code AND
orphaned / regional-agency / bespoke modules whose original provider will NOT ship a
2.4.x release. Tune the exclusion list with `--third-party-vendors`; never exclude a
vendor unless it reliably ships updates (default is conservative — unknown ⇒ counted).

## End-to-End Workflow (quick reference)

```bash
SKILL=path/to/skills/m2-upgrade-estimation
MAIN="$PWD"                              # main checkout
CUR=2.4.4 ; TGT=2.4.7-p3                 # versions
CPHP=8.1 ; TPHP=8.3 ; EDITION=enterprise
WT="../$(basename "$PWD")-$TGT-estimate"
RD="docs/upgrades/$CUR-to-$TGT"          # analysis dir (ephemeral, inside worktree — heavy raw diffs)
DOCS="$MAIN/docs/upgrades/$CUR-to-$TGT"  # deliverables dir (persists in the project after teardown)
mkdir -p "$DOCS"

# Phase 1 — materialize target + diff core
# 1. snapshot the CURRENT install FIRST, from $MAIN, before anything changes
bash "$SKILL/scripts/snapshot.sh" "/tmp/m2-snap-$CUR"
# 2. materialize the target version in an isolated worktree
git worktree add "$WT" -b "estimate-$TGT"
cp auth.json "$WT/"; cd "$WT"; mkdir -p "$RD/raw"
# --- from here on, CWD = $WT for every command (Phases 2–6 use relative $RD) ---
# 3. bump composer constraint to $TGT (enterprise: product-enterprise-edition), then update
composer update -W --no-scripts --no-progress
# 4. diff current snapshot vs target vendor  -> raw/magento.diff, modules-changed.txt
bash "$SKILL/scripts/diff.sh" "/tmp/m2-snap-$CUR" "$RD"

# Phase 2 — custom-code impact
python3 "$SKILL/scripts/extension-impact-deep.py" \
  --diff "$RD/raw/magento.diff" --app-code "$MAIN/app/code" --app-design "$MAIN/app/design" \
  --out-json "$RD/extension-impact-deep.json"

# Phase 3 — measure automation coverage + PHP ladder -> signals.json
# (install dev tools in the worktree first for real signal: rector/rector,
#  phpcompatibility/php-compatibility, bitexpert/phpstan-magento)
bash "$SKILL/scripts/collect-signals.sh" --report-dir "$RD" --app-code "$MAIN/app/code" \
  --current-version "$CUR" --target-version "$TGT" --current-php "$CPHP" --target-php "$TPHP" \
  --edition "$EDITION" --vendor-bin "$WT/vendor/bin" --uct-bin "$WT/bin/uct" \
  --php-ladder "$TPHP,8.4,8.5" --ext-conflicts 1

# Phase 4 — build PERT input from signals
python3 "$SKILL/scripts/build-pert-input.py" --signals "$RD/signals.json" --out "$RD/pert-input.json"

# Phase 5 — compute PERT estimate
python3 "$SKILL/scripts/compute-pert.py" --input "$RD/pert-input.json" --out-dir "$RD"

# Handoff: copy the lightweight source artifacts into the project's docs dir so it is
# self-contained + re-renderable after the worktree (and its heavy raw/ diffs) is gone.
cp "$RD"/{signals.json,pert-input.json,pert-estimation.json,pert-estimation.html,extension-impact-deep.json} "$DOCS/"

# Phase 6 — render report + runbook INTO the project's docs dir
python3 "$SKILL/scripts/render-estimate.py" --report-dir "$DOCS" \
  --template "$SKILL/templates/estimate-report.html" --out "$DOCS/estimate.html"
python3 "$SKILL/scripts/add-sortable-tables.py" "$DOCS/estimate.html"

# Phase 6b — generate the executable upgrade runbook (Markdown, for the dev/agent)
python3 "$SKILL/scripts/render-runbook.py" --report-dir "$DOCS" --out "$DOCS/UPGRADE-RUNBOOK.md"

# Phase 6c — generate the plain-Spanish CLIENT estimate (non-technical, hours per area)
python3 "$SKILL/scripts/render-client-estimate.py" --report-dir "$DOCS" --out "$DOCS/estimacion-cliente.html"

# Phase 7 — present as a Claude artifact (when running inside Claude)
# estimate.html is self-contained (zero external deps), so it renders directly:
# read $DOCS/estimate.html and emit its full contents as a `text/html` artifact.
# The user gets the interactive report in the artifacts pane. No code change.

# Phase 8 (optional) — teardown. The worktree (heavy raw/ diffs + downloaded vendor)
# is removed; the deliverables in $MAIN/docs/upgrades/... persist and can be committed.
cd "$MAIN"; git worktree remove "$WT"
```

## Phases

**Phase 1 — Materialize + diff.** Creates a worktree, bumps the composer constraint
to the target version, downloads vendor, and diffs `vendor/magento` against a
snapshot of the current install. `snapshot.sh` + `diff.sh` (reused verbatim) emit
`raw/magento.diff`, `raw/composer-lock.diff`, `raw/modules-changed.txt`. Use
`--no-scripts` on the composer update — never run setup hooks here.

**Phase 2 — Custom-code impact (owner-aware).** `extension-impact-deep.py` parses
the diff + scans `app/code` / `app/design` for custom code touching changed core:
preferences, plugins, virtualType, extends/implements, template/layout overrides.
Each finding is tagged `owner` (**custom** vs **third-party** by vendor namespace —
default denylist amasty/weltpixel/mirasvit/…, override with `--client-vendors`).
Generic `extends` is flagged `signature_risk` only when the parent class's *changed
hunks* alter a method/constructor signature (`--diff`-driven) — so routine
inheritance doesn't inflate the estimate. Writes `extension-impact-deep.json` with a
nested `summary` (per-relationship custom counts, third-party vendor list,
`extends_signature_risk`, `overlap_modules`). Custom findings drive migration hours;
third-party only triggers a flat per-vendor "verify compatible release" cost.

**Phase 3 — Measure automation coverage.** `collect-signals.sh` runs the tools and
merges everything into `signals.json`:
- **Rector** dry-run (`RECTOR_PHP_VERSION=<target>`, config = `references/rector.php`) → `parse-rector.py` → rule-set hit counts. Primary PHP-version signal; also the auto-fix coverage. Counts are vendor-scoped (`--exclude-vendors`).
- **Adobe UCT** (`bin/uct upgrade:check … --json-output-path`, EE) → `parse-uct.py` → Magento-API deprecation/removal count, **severity-weighted** (critical 1h / error 0.2h / warning 0.05h — "non-API" errors are noisy/low-risk). Complementary to Rector (catches Magento-API breakage Rector can't). Vendor-scoped.
- **PHPStan** (`bitexpert/phpstan-magento`) → static-error count. Only the **delta** vs a baseline counts: pass `--phpstan-baseline N` (errors on the *current* version); without it the count is surfaced but contributes 0h (raw count conflates pre-existing debt).
- **composer** extension conflicts are not auto-counted — pass `--ext-conflicts N` (count from the Phase 1 `composer update` output) to factor them in.
- **PHP ladder** (`--php-ladder 8.3,8.4,8.5`) — **Rector** version-set change counts per PHP level, so the estimate shows the marginal cost of going further on PHP and a `recommended_php` (highest measurable level whose marginal ≤ threshold). A level beyond Rector's known sets (>8.4 in rector 1.x) or unsupported by Magento is `measurable:false` — never silently zero.
- Every tool is optional; a missing binary zero-fills its section and the estimate falls back to the manual track.

**Phase 4 — Build PERT input.** `build-pert-input.py` maps measured counts to per-phase
O/M/P triples + the **automation coverage** discount, with **owner-aware** coefficients:
preference 4h, plugin 1.5h, safe-extends 0.5h, signature-risk-extends 2h, implements/
virtualType 0.5h, template/layout 1h — all custom-owner only. Third-party extensions get
a separate flat `Validación de extensiones de terceros` phase (n_vendors × 4h). Core
review scales by `overlap_modules` (modules custom code touches), not all changed modules.
A `Resolución de errores estáticos (PHPStan)` phase adds `0.1h × (errors − baseline)` —
0h (informational) when no baseline is supplied.
It also computes the **PHP ladder** (base hours at target + marginal delta per higher
minor). Coefficients documented in `references/estimation-framework.md` — keep in sync.

**Phase 5 — Compute.** `compute-pert.py` emits `pert-estimation.json` + a Spanish
`pert-estimation.html` fragment: E, σ, CI 70/80/90/95% in hours and person-days,
"sin automatización" vs "con automatización", and the projected saving %.

**Phase 6 — Report.** `render-estimate.py` fills `templates/estimate-report.html`
(scope, automation-coverage table, owner-split custom-code impact, the **PHP-version
ladder**, the PERT section, and assumptions/limits), then `add-sortable-tables.py`
injects column sorting. Output: self-contained `estimate.html`.

**Phase 6b — Upgrade runbook.** `render-runbook.py` turns the same measured analysis
into `UPGRADE-RUNBOOK.md` — a phased, ordered checklist a developer (or a Claude Code
agent) follows to *execute* the upgrade: worktree + composer setup with the discovered
blockers, the Rector auto-fix commands, the prioritized custom-migration checklist
(signature-risk extends first, then preferences/plugins/overrides — each with file →
Magento target), the per-vendor third-party verify list, and DB/compile/deploy steps.
Pre-existing UCT debt is an optional appendix, not upgrade work. Reuses the estimate's
artifacts — no extra analysis.

**Phase 6c — Client estimate.** `render-client-estimate.py` emits `estimacion-cliente.html`
— a plain-Spanish, non-technical one-pager that groups the work into ~6 business-language
areas with approximate hours each, a total in hours/days (con vs sin automatización), the
PHP recommendation, and what's in/out of scope. No PERT/σ/tool jargon. For the client/sponsor.

**Phase 7 — Present as a Claude artifact.** When running inside Claude, read
`estimate.html` and emit its full contents as a `text/html` artifact. It is
self-contained (zero external dependencies — exactly what artifacts require), so it
renders interactively in the artifacts pane with no transformation. No code change.

**Phase 8 (optional) — `--judge` cross-check.** Spawn two blind estimator subagents
on the diff + signals; if their hour ranges diverge >2× from the PERT E, flag low
confidence in the report. (See `references/estimation-framework.md`.)

## Outputs

**Persistent — in the project** (`$MAIN/docs/upgrades/<CUR>-to-<TGT>/`, survives teardown, commit-ready):
```
  estimate.html                # technical estimate report (PERT/CI, tool coverage) — internal
  estimacion-cliente.html      # plain-Spanish client estimate, approx hours per area — for the client
  UPGRADE-RUNBOOK.md           # actionable phased checklist to DO the upgrade (dev/agent reference)
  signals.json                 # all measured counts (for re-render / audit)
  pert-input.json              # per-phase O/M/P + automation coverage
  pert-estimation.json/.html   # E, σ, CI 70/80/90/95%
  extension-impact-deep.json   # custom-code impact + summary
  estimate.html.bak.<ts>       # safety backup from add-sortable-tables.py (safe to delete)
```
**Ephemeral — inside the worktree** (removed at teardown; heavy):
```
  raw/{magento.diff, magento.logic.diff, composer-lock.diff, modules-changed.txt, rector-*.json, uct-report.json}
```

## Rules

- **ALWAYS** run the automation tools before quoting — the "con automatización"
  track is only credible when coverage is *measured*. State in the report which
  tools actually ran vs were zero-filled.
- **ALWAYS** quote a confidence interval, not the bare E. For a 90%-confident date
  use CI 90%; E is the budgeting mean, not a commitment.
- **NEVER** run `composer update` without `--no-scripts` in the worktree.
- **NEVER** present the estimate without its caveats (±30% ROM, 1 dev + 1 QA,
  excludes approvals / change windows / regression-discovery iteration).
- The estimate is **uncalibrated** until a real upgrade is logged — record actual
  hours afterward, nudge the coefficients in `references/estimation-framework.md`
  + `build-pert-input.py`, and bump `metadata.version`.

## Reuse provenance

Diff pipeline (`snapshot.sh`, `diff.sh`), PERT engine (`compute-pert.py`),
custom-code scanner (`extension-impact-deep.py`), `_safety.py`, and
`add-sortable-tables.py` are reused/adapted from `magento-security-upgrade`.
`references/rector.php` from `upgrading-php-rector`. Dimension sanity-check and
`--judge` protocol from `jira-estimate`.

## Tests

`python3 tests/run.sh` — unit tests for the PERT math, the signal→PERT mapping
(with automation coverage), and the parsers; plus a render smoke test. All
stdlib-only, no pytest required.
