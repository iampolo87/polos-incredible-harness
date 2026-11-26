# Code Review Severity & Response Template

## Severity Levels

🔴 **CRITICAL** — fix immediately:
- Security vulnerabilities
- Data loss/corruption risk
- Breaking production functionality
- Direct ObjectManager usage (Magento 2)

🟠 **HIGH** — fix before deploy:
- Performance bottlenecks (N+1, missing indexes)
- Missing error handling
- Deprecated patterns that break on upgrade
- Poor architectural decisions

🟡 **MEDIUM** — fix soon:
- Code smells
- Missing type hints / return types
- Suboptimal patterns
- Missing tests for complex logic

🟢 **LOW** — nice to have:
- Style issues
- Minor optimizations
- Doc improvements

## Response Template

**New code:**
1. State assumptions about requirements/env.
2. Highlight rule deviations with justification.
3. Note perf/scalability for non-trivial code.
4. Suggest test coverage for complex logic.

**Code review:**
1. List violations by severity (CRITICAL → LOW).
2. Explain WHY each matters.
3. Provide refactored alternative for HIGH+ issues.
