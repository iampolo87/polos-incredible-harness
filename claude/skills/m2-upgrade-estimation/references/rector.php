<?php

declare(strict_types=1);

use Rector\Config\RectorConfig;
use Rector\Php\PhpVersionResolver\ComposerJsonPhpVersionResolver;
use Rector\Set\ValueObject\LevelSetList;
use Rector\Set\ValueObject\SetList;
use Rector\Exception\Configuration\InvalidConfigurationException;

return static function (RectorConfig $rectorConfig): void {
    // 1. Import official Magento coding standard base (if available)
    $magentoStandardPath = __DIR__ . '/vendor/magento/magento-coding-standard/rector.php';
    if (file_exists($magentoStandardPath)) {
        $magentoConfig = require $magentoStandardPath;
        $magentoConfig($rectorConfig);
    }

    // 2. Paths — only existing directories
    $directories = [
        __DIR__ . '/app/code',
        __DIR__ . '/app/design',
    ];
    $rectorConfig->paths(array_filter($directories, 'is_dir'));

    // 3. Skip — directories and rules that must not be processed
    $rectorConfig->skip([
        __DIR__ . '/vendor',
        __DIR__ . '/generated',
        __DIR__ . '/var',
        __DIR__ . '/pub',
        __DIR__ . '/app/code/*/*/vendor',

        // Rules that break Magento DI (Proxies, Factories, ObjectManager)
        \Rector\Php81\Rector\Property\ReadOnlyPropertyRector::class,
        \Rector\Php82\Rector\Class_\ReadOnlyClassRector::class,

        // Magento needs DocBlocks for code generation and DI type resolution
        \Rector\DeadCode\Rector\ClassMethod\RemoveUselessParamTagRector::class,
        \Rector\DeadCode\Rector\ClassMethod\RemoveUselessReturnTagRector::class,
        \Rector\DeadCode\Rector\Node\RemoveNonExistingVarAnnotationRector::class,

        // Too aggressive for mixed Magento codebases
        \Rector\Php80\Rector\FunctionLike\MixedTypeRector::class,

        // PHP 8.3 — too noisy on Magento's deep inheritance chains
        \Rector\Php83\Rector\ClassMethod\AddOverrideAttributeToOverriddenMethodsRector::class,

        // Skip void return on Setup Patches (breaks legacy patches)
        \Rector\TypeDeclaration\Rector\ClassMethod\AddVoidReturnTypeWhereNoReturnRector::class => [
            __DIR__ . '/app/code/*/*/Setup/Patch/*',
        ],
    ]);

    // 4. Resolve PHP version: env override > composer.json > fallback
    //    Usage: RECTOR_PHP_VERSION=83 vendor/bin/rector process app/code
    $phpVersionMap = [
        '80' => LevelSetList::UP_TO_PHP_80,
        '81' => LevelSetList::UP_TO_PHP_81,
        '82' => LevelSetList::UP_TO_PHP_82,
        '83' => LevelSetList::UP_TO_PHP_83,
        '84' => LevelSetList::UP_TO_PHP_84,
    ];

    $envVersion = getenv('RECTOR_PHP_VERSION') ?: null;
    if ($envVersion && isset($phpVersionMap[$envVersion])) {
        $phpLevelSets = [$phpVersionMap[$envVersion]];
    } else {
        try {
            $projectPhpVersion = ComposerJsonPhpVersionResolver::resolveFromCwdOrFail();
            $phpLevelSets = \Rector\Configuration\PhpLevelSetResolver::resolveFromPhpVersion($projectPhpVersion);
        } catch (InvalidConfigurationException) {
            $phpLevelSets = [LevelSetList::UP_TO_PHP_83];
        }
    }

    // 5. Rule sets — PHP level + code quality improvements
    $rectorConfig->sets([
        ...$phpLevelSets,
        SetList::DEAD_CODE,
        SetList::CODE_QUALITY,
        SetList::TYPE_DECLARATION,
    ]);

    // 6. Performance
    $rectorConfig->importNames();
    $rectorConfig->parallel();
};
