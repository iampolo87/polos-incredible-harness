# Patch matching spec

How `match-patches.php` + `parse-patch-gaps.py` enumerate the quality-patch gap.

## Why not `vendor/bin/magento-patches`

It segfaults in some environments (full Symfony console bootstrap; observed
`exit=139`, core dump). The matcher instead reads the catalog JSON directly and
resolves version constraints with the installed `composer/semver` — the exact
engine Composer itself uses. A thin script that only `require`s
`vendor/autoload.php` does not trigger the segfault.

## Catalog source

- `vendor/magento/quality-patches/support-patches.json` (~832 patches)
- `vendor/magento/quality-patches/community-patches.json` (~5)

Schema per id:

```json
"ACSD-53636": {
  "categories": ["Catalog/Product", "Price/Tax"],
  "title": "...",
  "packages": {
    "magento/magento2-base": {
      ">=2.4.3 <2.4.5": { "file": "os/ACSD-53636_2.4.4.patch", "require": ["MDVA-41061-V4"] }
    }
  }
}
```

## The `-pN` pitfall

Magento versions carry a patch suffix (`2.4.5-p16`). Naive string/numeric
comparison gets ranges wrong — e.g. `2.4.5-p16` must NOT satisfy `>=2.4.3 <2.4.5`
(so ACSD-53636's 2.4.4-only arm correctly does NOT apply to a 2.4.5-p16 install).
`Composer\Semver\Semver::satisfies($version, $constraint)` handles `-pN`, `||`,
and `>=…<…` compounds correctly. **Never reimplement this in Python.**

## Applicability rule

A patch is applicable if **any** installed package (from `composer.lock`
`packages` + `packages-dev`) satisfies **any** of that patch's package-arm
constraints. This handles edition alternatives (`magento2-base` vs
`magento2-ee-base`) and multi-package patches. The first matching arm is
recorded (package, constraint, `.patch` file, `require` prerequisites).
Unparseable constraints go to `errors[]`, never silently dropped.

## Applied set (declarative)

`collect-applied-set.py` unions three declared sources:

1. `.magento.env.yaml` → `stage.build.QUALITY_PATCHES`
2. `m2-hotfixes/*.patch` filenames (ids parsed via
   `(ACSD|MDVA|MC|MCLOUD|MCP|AC|B2B|VULN)-\d+`)
3. `composer.json` → `extra.patches` (also surfaced as `manual_patches`)

**Limitation:** this is *declared*-applied, not file-content-verified. A patch
that failed to apply at build still appears applied. The report shows a caveat.

## Gap + tiering

`gap = applicable − applied_catalog_ids`. Each gap patch gets a tier from its
categories (highest-priority category wins):

- **T1** Performance · Cache · Catalog Search
- **T2** Order/Checkout · Shopping Cart · Payments · Price/Tax · Inventory
- **T3** Cron · Admin · Customer · Catalog/Product · Web API · GraphQL · B2B
- **T4** Content · Emails · Import/Export · Reports · Shipping · Other

`requires_unapplied` flags prerequisite patch ids that are themselves still
unapplied (apply those first).
