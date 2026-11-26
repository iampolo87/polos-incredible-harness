<?php
/**
 * Dump app/etc/env.php (a PHP array) to JSON so the Python audit can read it
 * without a fragile PHP-array regex parser. PHP is authoritative here.
 *
 * On Adobe Commerce Cloud, env.php is usually a small stub — the real config
 * is generated at deploy from .magento.env.yaml variables. The config audit
 * treats env.php-located settings as "deferred" in that case.
 *
 * Usage: php dump-envphp.php [path/to/app/etc/env.php]
 */
$path = $argv[1] ?? 'app/etc/env.php';
if (!is_file($path)) {
    fwrite(STDERR, "dump-envphp: file not found: $path\n");
    exit(1);
}
$config = require $path;
if (!is_array($config)) {
    fwrite(STDERR, "dump-envphp: env.php did not return an array\n");
    exit(1);
}
echo json_encode($config, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES) . "\n";
