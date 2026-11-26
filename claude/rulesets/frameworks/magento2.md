# Magento 2: Specific Rules & Gotchas

## 1. Dependency Injection & Core Services  
- Never use `\Magento\Framework\ObjectManager` directly in constructors or business logic. Always inject dependencies via constructor.  
- When you need UI logic, prefer **ViewModels** over embedding logic in Blocks/templates.  
- Use Service Contracts (interfaces under the `Api/` folder) for module boundaries instead of concrete models.

## 2. Controller & Deprecation Practices  
- Prioritise using modern approaches: implement interfaces in controller actions (e.g., `\Magento\Framework\App\Action\HttpGetActionInterface`, `HttpPostActionInterface`) instead of extending the deprecated `\Magento\Framework\App\Action\Action` class.
- Avoid using deprecated classes and methods (for example, `\Magento\Framework\App\Action\Action`, the global `Registry` class, usage of `load/save/delete` on AbstractModel, etc.).  
- Avoid adding 'setup_version' in module.xml files

## 3. Configuration & Credentials  
- Use credentials/config defined in `app/etc/env.php` for database or external service connections — do not hardcode or assume environment defaults.  
- Ensure configuration values are accessed via proper ScopeConfig/DI rather than static config reads.

## 4. Cacheability & Performance  
- Avoid blocks/pages with `cacheable="false"` unless absolutely required; document why if you do.  
- Leverage private content, HTTP Context variables, and ESI for dynamic parts of page caching.  
- Be cautious with EAV attributes: each attribute adds overhead — use flat tables or aggregated tables when high scale.  
- Use indexes on key tables; for large catalogs consider large table partitioning or optimized storage.

## 5. Schema & Database  
- Use declarative schema (`db_schema.xml`) rather than direct SQL schema scripts when possible.  
- Avoid large unindexed tables; long joins across EAV can severely degrade performance.  
- For B2B/Enterprise scale, design for large data volumes: retention policies, archiving, partitioning.

## 6. Core Modification & Extension  
- Avoid overriding core classes directly; prefer Plugins / Observers / Extension Attributes.  
- Document any purposeful “hack” or override that deviates from Magento standard — these become maintenance hotspots.  
- When adding heavy customizations, evaluate the upgrade path for future Magento versions.

## 7. Modern PHP & Magento Version Features  
- Use PHP features supported by your Magento version: typed properties, union types, attributes for DI.  
- Maintain compatibility with Magento patch releases; avoid relying on unsupported internal APIs.  
- Use strict types, typed return values, property promotion when possible.

## 8. Testability & Quality
- Use integration tests for modules that affect critical flows (checkout, customer login, pricing).
- Ensure your customizations do not break full-page caching or render uncacheable blocks unless necessary.
- Monitor production logs for heavy queries, slow page loads, high CPU usage.

## 9. Collection Performance
- Always use `setPageSize(1)` before `getFirstItem()` — without it, the entire collection loads into memory before returning the first record.
- Use `addFieldToSelect()` to limit columns when you don't need all fields.
- Prefer `getSize()` over `count()` for counting — `getSize()` uses SQL COUNT, `count()` loads all records.
- Use `setPageSize()` + `setCurPage()` for pagination instead of loading full collections.

## 10. Session & Heavy Dependency Performance
- Use Proxy classes for `CheckoutSession`, `CustomerSession`, `CatalogSession` and any dependency not always used in every code path.
- **Proxy classes must be declared in `di.xml`, never directly in PHP code**:
  - ✅ In `di.xml`: `<argument name="checkoutSession" xsi:type="object">Magento\Checkout\Model\Session\Proxy</argument>`
  - ✅ In PHP: type-hint the original class/interface (`Session $checkoutSession`)
  - ❌ Never type-hint the Proxy class directly in constructors (`Session\Proxy $checkoutSession`)
  - ❌ Never instantiate Proxy classes via ObjectManager
- This rule applies to all lazy-loading patterns: Proxies, Factories (when overriding), and Virtual Types — always configure in `di.xml`.

## 11. Repository & Model Performance
- Use `getList()` with SearchCriteria instead of collections when working with Service Contracts.
- Avoid `load()` inside loops — batch load with collections or `getList()`.
- Use `getById()` instead of `load()` when working with repositories.

## 12. Database Query Performance
- Avoid `afterLoad()` plugins on collections used in listings — use `afterGetList()` on repositories instead.
- Index custom table columns used in `addFieldToFilter()` or `setOrder()`.
