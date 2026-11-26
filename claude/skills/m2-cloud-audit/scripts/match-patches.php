<?php
/**
 * Enumerate every Magento Quality Patch that applies to a project's EXACT
 * installed package versions, by matching the QPT catalog against composer.lock
 * with Composer\Semver\Semver — the same resolver Composer itself uses.
 *
 * WHY a PHP bridge and not `vendor/bin/magento-patches status`: that binary
 * segfaults in some environments (full Symfony console bootstrap). This script
 * touches only the catalog JSON + composer/semver, so it is safe and fast.
 *
 * The "-pN" patch suffix on Magento versions (e.g. 2.4.5-p16) breaks naive
 * string/numeric comparison; composer/semver normalizes it correctly. Never
 * reimplement this matching in another language.
 *
 * Usage:
 *   php match-patches.php --lock composer.lock \
 *       --catalog vendor/magento/quality-patches/support-patches.json \
 *       [--community vendor/magento/quality-patches/community-patches.json] \
 *       [--autoload vendor/autoload.php]
 * Emits matched-patches.json to stdout.
 */

function arg(string $name, ?string $default = null): ?string {
    global $argv;
    foreach ($argv as $a) {
        if (strpos($a, "--$name=") === 0) {
            return substr($a, strlen("--$name="));
        }
    }
    foreach ($argv as $i => $a) {
        if ($a === "--$name" && isset($argv[$i + 1])) {
            return $argv[$i + 1];
        }
    }
    return $default;
}

function fail(string $msg): void {
    fwrite(STDERR, "match-patches: $msg\n");
    exit(1);
}

$lockPath = arg('lock');
if (!$lockPath || !is_file($lockPath)) {
    fail("--lock composer.lock is required and must exist");
}
$catalogPath = arg('catalog');
if (!$catalogPath || !is_file($catalogPath)) {
    fail("--catalog support-patches.json is required and must exist");
}
$communityPath = arg('community');

// Locate composer autoload (for Composer\Semver\Semver).
$autoload = arg('autoload');
if (!$autoload) {
    $autoload = dirname($lockPath) . '/vendor/autoload.php';
}
if (!is_file($autoload)) {
    fail("autoload not found at $autoload (need composer/semver). "
        . "Pass --autoload explicitly.");
}
require $autoload;
if (!class_exists(\Composer\Semver\Semver::class)) {
    fail("Composer\\Semver\\Semver not available — is composer/semver installed?");
}
use Composer\Semver\Semver;

// Build installed package -> version map from composer.lock.
$lock = json_decode(file_get_contents($lockPath), true);
if (!is_array($lock)) {
    fail("could not parse composer.lock");
}
$installed = [];
foreach (['packages', 'packages-dev'] as $section) {
    foreach ($lock[$section] ?? [] as $pkg) {
        if (isset($pkg['name'], $pkg['version'])) {
            $installed[$pkg['name']] = ltrim($pkg['version'], 'v');
        }
    }
}

$projectVersion = $installed['magento/magento2-base'] ?? null;
$edition = (isset($installed['magento/product-enterprise-edition'])
    || isset($installed['magento/magento2-ee-base']))
    ? 'enterprise' : 'community';

/**
 * Match one catalog file. A patch is applicable if ANY installed package
 * satisfies ANY of that patch's package-arm constraints (edition/multi-pkg
 * alternatives). Records the first matching arm.
 */
function matchCatalog(array $catalog, array $installed, string $sourceLabel,
                      array &$applicable, array &$errors): int {
    $skipped = 0;
    foreach ($catalog as $id => $data) {
        $packages = $data['packages'] ?? [];
        $matched = null;
        foreach ($packages as $pkgName => $constraints) {
            if (!isset($installed[$pkgName])) {
                continue;
            }
            $version = $installed[$pkgName];
            foreach ($constraints as $constraint => $meta) {
                try {
                    $ok = Semver::satisfies($version, (string)$constraint);
                } catch (\Throwable $e) {
                    $errors[] = [
                        'id' => $id, 'package' => $pkgName,
                        'constraint' => (string)$constraint,
                        'reason' => $e->getMessage(),
                    ];
                    continue;
                }
                if ($ok) {
                    $matched = [
                        'matched_package' => $pkgName,
                        'matched_constraint' => (string)$constraint,
                        'matched_version' => $version,
                        'file' => $meta['file'] ?? null,
                        'requires' => array_values($meta['require'] ?? []),
                    ];
                    break 2;
                }
            }
        }
        if ($matched === null) {
            // not installed at a matching version (or installed-but-no-match)
            if (empty(array_intersect(array_keys($packages), array_keys($installed)))) {
                $skipped++;
            }
            continue;
        }
        $applicable[] = array_merge([
            'id' => $id,
            'title' => $data['title'] ?? '',
            'categories' => array_values($data['categories'] ?? []),
            'source' => $sourceLabel,
        ], $matched);
    }
    return $skipped;
}

$applicable = [];
$errors = [];
$skipped = 0;

$support = json_decode(file_get_contents($catalogPath), true) ?? [];
$skipped += matchCatalog($support, $installed, 'support', $applicable, $errors);

if ($communityPath && is_file($communityPath)) {
    $community = json_decode(file_get_contents($communityPath), true) ?? [];
    $skipped += matchCatalog($community, $installed, 'community', $applicable, $errors);
}

// stable order by id
usort($applicable, fn($a, $b) => strcmp($a['id'], $b['id']));

echo json_encode([
    'project_version' => $projectVersion,
    'edition' => $edition,
    'installed_count' => count($installed),
    'applicable' => $applicable,
    'skipped_no_install' => $skipped,
    'errors' => $errors,
], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES) . "\n";
