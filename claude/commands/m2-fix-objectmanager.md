---
description: Detect direct ObjectManager usage in Magento 2 code and refactor to constructor DI. Verifies candidate types inline before refactoring.
argument-hint: "[target-path] [--dry-run] [--no-m2-agents]"
allowed-tools: [Read, Edit, Write, Bash, Grep, Glob]
---

# Fix ObjectManager Anti-Pattern

Find direct ObjectManager usage in `$ARGUMENTS` (target path, default `app/code/`) and refactor each occurrence to proper constructor dependency injection.

## Args

- First arg = target path. Default `app/code/`.
- `--dry-run` = list hits only, no edits.
- `--no-m2-agents` = accepted for compatibility; classification always runs inline.

## Procedure

### 1. Detection

Run grep for the four real ObjectManager call shapes:

```bash
grep -rnE \
  "ObjectManager::getInstance\(\)|->get\(([\\'\"\\\\]|[A-Z][A-Za-z0-9_\\\\]+::class)|->create\(([\\'\"\\\\]|[A-Z][A-Za-z0-9_\\\\]+::class)" \
  --include='*.php' <target-path>
```

Covers:
- `ObjectManager::getInstance()` static fetch
- `->get(Class::class)` and `->get('Class\\Name')` on any variable
- `->create(Class::class)` and `->create('Class\\Name')` on any variable
- Common vars: `$objectManager`, `$this->_objectManager`, `$this->objectManager`

### 2. False-positive filter

The broad `->get(` / `->create(` patterns match non-OM calls (collection filters, factory methods, registry lookups). **NEVER auto-edit on raw grep output.**

For each hit:
1. Read the surrounding code and trace the receiver's declared or assigned type. Expand the
   context when needed; a method named `get` or `create` alone does not prove ObjectManager use.
2. Record the file:line, whether the receiver is an ObjectManager, the dependency class or
   interface, and any intentional-use or uncertainty reason. Exclude unrelated calls.
3. Present confirmed candidates and unresolved cases. Apply refactors within the user's existing
   authorization; ask only for an unresolved classification or authorization that is absent.

No specialist agent is required. `--dry-run` stops after reporting candidates.

### 3. Refactor per confirmed hit

Invoke `test-driven-development`:

1. Write failing test capturing current behavior.
2. Refactor:
   - Add constructor parameter with PHP type (use the concrete class or interface).
   - Update parent `::__construct()` chain.
   - Register in `di.xml` if a virtualType or preference is needed.
   - Replace ObjectManager call with `$this->injectedDep`.
3. Run unit tests; confirm green.

### 4. After all hits processed

- Run module's full unit test suite.
- Report: changed files count, dropped ObjectManager count, any skipped hits + reason.

## Note on `\Magento\Framework\App\ObjectManager\NoninterceptableInterface`

Some legacy Magento classes legitimately use ObjectManager (factories, bootstrap code, certain plugins). If the file implements `NoninterceptableInterface` or sits in `dev/`/`pub/`/`setup/`, flag as "intentional usage" and skip with a comment.
