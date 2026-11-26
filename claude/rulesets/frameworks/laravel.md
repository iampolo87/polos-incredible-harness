# Laravel: Specific Rules & Gotchas

## 1. Dependency Injection & Service Container  
- Use the Laravel service container for injecting dependencies rather than relying excessively on facades or static methods in business logic.  
- Keep logic out of controllers: Controllers should orchestrate, Services should contain business logic, Repositories (if used) handle data access.

## 2. Eloquent & Database Performance  
- Avoid N+1 query patterns: use `with()` to eager load relations when needed.  
- Define indexes in migrations for columns you query/filter/sort by frequently.  
- Use caching (Redis/Cache) for expensive queries or otherwise repeated data fetches.  
- When dataset becomes large, consider partitioning/archiving strategies or use read replicas.

## 3. Modern PHP Features & Version Compatibility  
- Use PHP typed properties, union types, attributes, property promotion etc when your PHP version allows.  
- Use Laravel features that align with modern PHP (e.g., Job type hints, event/listeners with attributes).  
- Keep your Laravel version maintained; use supported features and avoid deprecated APIs.

## 4. Code Quality & Testing  
- Use PHPUnit or Pest for unit and integration tests; coverage should focus on business logic.  
- Keep controller methods small and readable. Services should be unit test friendly (inject dependencies, avoid global state).  
- Use static analysers (PHPStan, Psalm) to enforce types, detect dead code, unused dependencies.

## 5. Architecture & Maintainability  
- Use “thin” controllers and route definitions; apply middleware, policies, form-requests for validation.  
- Prefer domain-driven design when business logic grows: domain services, aggregates, value objects.  
- Use events/dispatch for side-effects rather than embedding logic deep inside models.

## 6. Deployment, Performance & Scaling  
- Use queue workers (jobs) for long running tasks; avoid blocking HTTP requests.  
- Use caching layers, separation of read/write when scale demands it.  
- Monitor query logs, slow queries, memory usage, CPU usage in production.  
- Use environment config (`.env`) properly; sensitive credentials should not be hardcoded.
