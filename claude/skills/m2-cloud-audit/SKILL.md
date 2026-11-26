---
name: m2-cloud-audit
description: >
  Audit a Magento 2 / Adobe Commerce Cloud project for recommended-but-not-applied
  things that no single tool surfaces together: (1) Quality patches from the
  installed magento/quality-patches catalog that apply to the project's exact
  versions but are not in its declared-applied set, (2) recommended-but-not-default
  infra/service config settings (e.g. MariaDB optimizer_switch=rowid_filter=off,
  opcache sizing, Redis L2 cache) that SWAT does NOT report, and (3) services
  running EOL or below-recommended versions. Produces one self-contained English
  HTML report. Read-only — it recommends, it applies nothing.
  Trigger: when reviewing a Commerce Cloud project's health, asking "which
  quality patches are we missing", "what DB/PHP/Redis configs should we set",
  "are we on EOL services", or auditing config/patch drift before a release.
license: Apache-2.0
trigger: "magento cloud audit, quality patch gap, which patches missing, ACSD patch audit, optimizer_switch rowid_filter, recommended magento config not applied, opcache sizing magento, EOL services magento, services.yaml mariadb opensearch redis version, config drift audit, magento.env.yaml recommendations"
metadata:
  author: polo
  version: "0.1.0"
---

# m2-cloud-audit

Finds three classes of silent gap in a Magento 2 **Cloud** project and merges
them into one HTML report. Built as a sibling of `m2-upgrade-estimation`
(stdlib-only Python + thin PHP bridges, self-contained HTML output).

## Why this exists

- **Quality patches** — Adobe ships ~830 patches via `magento/quality-patches`;
  projects opt into a handful. The rest (real perf/cache/checkout fixes) are
  invisible unless you enumerate the catalog against your exact versions.
- **Config recommendations** — settings Adobe documents as recommended but does
  not apply by default (MariaDB `optimizer_switch`, opcache sizing, Redis L2,
  slave connections). **SWAT does not surface these** — they live scattered
  across Experience League docs. This skill keeps a curated catalog of them.
- **Service versions** — Cloud `services.yaml` often pins EOL MariaDB/OpenSearch/
  Redis long after support ends.

## Hard constraints

- **Never run `vendor/bin/magento-patches`** — it segfaults in some environments
  (full Symfony console bootstrap). Patch enumeration goes through
  `match-patches.php`, which only touches the catalog JSON + the installed
  `composer/semver` (`Composer\Semver\Semver::satisfies`). The `-pN` patch
  suffix on Magento versions breaks naive comparison; never reimplement matching
  outside composer/semver.
- **Patch detection is declarative**, not content-verified. A patch listed in
  `QUALITY_PATCHES` / `m2-hotfixes/` / `composer.json extra.patches` is treated
  as applied even if it silently failed at build time. The report states this.
- **Read-only.** Emits recommendations + paste-ready snippets; applies nothing.

## Run it

```
scripts/run-audit.sh --project /path/to/project [--name NAME] [--out DIR] [--date YYYY-MM-DD]
```

Defaults: `--project` = cwd, `--name` = project dirname, `--date` = today,
`--out` = `<project>/docs/cloud-audit/<date>/`. Output: `audit.html` plus all
intermediate JSONs (re-renderable / auditable).

## Workflow (phases)

0. **Prerequisites** — `php` + `python3` on PATH, `composer.lock` present.
   Detect Cloud via `.magento/services.yaml`. Never call `magento-patches`.
1. **Match patches** — `match-patches.php --lock composer.lock --catalog
   vendor/magento/quality-patches/support-patches.json --community ...` →
   `matched-patches.json` (applicable patches + project version/edition).
2. **Applied set** — `collect-applied-set.py` unions `.magento.env.yaml`
   `build.QUALITY_PATCHES`, `m2-hotfixes/*.patch` filenames, and
   `composer.json extra.patches` → `applied-set.json`.
3. **Patch gaps** — `parse-patch-gaps.py` (applicable − applied, tier-ranked
   by category) → `patch-gaps.json`.
4. **Config gaps** — `dump-envphp.php` (only if env.php is non-stub), then
   `parse-config-gaps.py` diffs `references/config-recommendations.json` against
   `services.yaml` / `.magento.env.yaml` / php.ini / env.php → `config-gaps.json`.
5. **Service versions** — `parse-service-versions.py` vs
   `references/service-eol.json` → `service-gaps.json`.
6. **Merge** — `build-audit-input.py` → `audit-input.json` (render contract +
   scorecards).
7. **Render** — `render-audit.py` fills `templates/audit-report.html` →
   `audit.html` (self-contained, English).
8. **Present** — open / hand off `audit.html`; intermediate JSONs sit beside it.

## Maintenance

- **Patch catalog** self-updates: it is read live from `vendor/magento/quality-patches`,
  which refreshes on `composer update`.
- **Config + EOL catalogs** are hand-maintained (`references/config-recommendations.json`,
  `references/service-eol.json`). Each carries `catalog_version` + `last_reviewed`,
  printed in the report so staleness is visible. Refresh procedure:
  `references/config-audit-spec.md`.
- Bump `metadata.version` when a catalog is revised or a script behavior changes.

## Rules

- ALWAYS keep the declarative-detection caveat in the report.
- ALWAYS print catalog version + review date (staleness visibility).
- NEVER call `vendor/bin/magento-patches`.
- NEVER claim a config gap for an env.php-located setting when env.php is a
  Cloud stub — report it as `deferred` and point at the deploy variable.
- Degrade gracefully on non-Cloud projects: patch + service sections still run
  from `composer.lock`/catalog; config section marks affected entries `no_file`.

## Tests

`tests/run.sh` runs every `test_*.py` (stdlib-only, plain asserts). The Python
suite is fed PHP-output fixtures so it needs no PHP. See
`references/patch-matching-spec.md` for the matcher contract.
