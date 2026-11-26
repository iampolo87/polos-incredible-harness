# Config audit spec

How `parse-config-gaps.py` diffs the curated catalog against a project, and how
to keep the catalog fresh.

## Catalog: `references/config-recommendations.json`

Curated-core set of recommended-but-not-default Adobe Commerce Cloud settings.
**SWAT does not surface these** — that is the reason this catalog exists. Each
entry:

| field | meaning |
|-------|---------|
| `setting` | exact key name |
| `recommended_value` / `default` | the recommendation and the platform default |
| `location` | `services.yaml` \| `.magento.env.yaml` \| `env.php` \| `php.ini` |
| `path` | location-relative key path to read (flat `[key]` for ini) |
| `match` | `present` \| `equals` \| `contains` \| `version_gte` |
| `applies_to` | `{service, min_version, magento_min, environment}` gate |
| `severity` / `category` | for ranking + grouping |
| `rationale` / `source_url` | one-line why + Adobe doc link |
| `snippet` | paste-ready, location-specific fix text |

## Per-location reading

- `services.yaml`, `.magento.env.yaml` → `_miniyaml.py` (vendored read-only YAML
  subset; never writes these files).
- `php.ini` / `.user.ini` → flat `key = value` line reader (`configparser` is too
  strict for Magento's bare `.user.ini`).
- `env.php` → `dump-envphp.php` emits JSON (PHP is authoritative; no regex).
  On Cloud env.php is a deploy-generated stub; `run-audit.sh` only dumps it when
  it exceeds ~1.5 KB. Otherwise env.php-located settings are reported `deferred`,
  pointing at the equivalent `.magento.env.yaml` deploy variable.

## Status semantics

`ok` · `missing` (file present, key absent) · `suboptimal` (present, wrong value
— captures `current_value`) · `na` (applies_to gate excludes) · `no_file`
(location file absent, e.g. non-Cloud) · `deferred` (env.php Cloud stub).

## Service EOL: `references/service-eol.json`

Per-service EOL dates (`YYYY-MM`) + `recommended_floor`. `parse-service-versions.py`
flags `eol` (EOL date ≤ `--as-of`) or `below_recommended` (below floor, not EOL).

## Refresh procedure (the hand-maintained hotspot)

1. Re-read the Adobe service-config docs (MySQL/PHP/OpenSearch/Redis/Varnish) and
   the `.magento.env.yaml` variables reference for new recommendations.
2. Update vendor EOL dates in `service-eol.json` against MariaDB/OpenSearch/Redis/
   RabbitMQ/PHP schedules.
3. Bump `catalog_version` + `last_reviewed` in BOTH JSON files (printed in the
   report so reviewers see freshness).
4. Add a fixture case in `tests/` for any new `match`/`location` shape.
5. Bump `metadata.version` in `SKILL.md`.

Keep the curated core **high-confidence and low-false-positive**. Settings that
need per-project judgement (SCD_MATRIX shape, max_concurrency tuning) belong in a
separate advisory tier, not the auto-diff core.
