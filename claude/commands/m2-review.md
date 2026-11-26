---
description: Magento 2-aware adversarial code review. Wraps judgment-review with M2 severity overlay and optional project-subagent dispatch.
argument-hint: "[target-path-or-diff-spec] [--no-m2-agents]"
---

# Magento 2 Code Review

Invoke the `judgment-review` skill on the current diff (or `$ARGUMENTS` if provided) with a Magento 2 severity overlay. Do NOT reimplement the dual-judge flow — wrap it.

## Severity Overlay (pass as judge-prompt addendum)

When evaluating findings, apply these Magento-specific severity rules ON TOP of the base severity scale in `~/.claude/rulesets/core/code-review.md`:

- 🟡 **MEDIUM** (**HIGH** in a plugin or observer) — Direct ObjectManager usage (`ObjectManager::getInstance()`, injected `$objectManager->get()`/`->create()` outside bootstrap)
- 🟠 **HIGH** — Missing constructor DI (using `new` for Magento services, instantiating models directly)
- 🟠 **HIGH** — Missing repository pattern when querying entities (using collection factories where a repository exists)
- 🟠 **HIGH** — Plugin `around` method missing `$proceed()` callthrough
- 🟡 **MEDIUM** — Hardcoded store ID / website ID / scope literals
- 🟡 **MEDIUM** — `load()` on entity instead of repository `get*()`
- 🟡 **MEDIUM** — String FQN (`'Magento\Foo\Bar'`) instead of `Foo\Bar::class`
- 🟢 **LOW** — Missing `declare(strict_types=1)`, missing `readonly`/`final`, missing docblocks

## Procedure

1. Read `~/.claude/rulesets/frameworks/magento2.md` for full M2 ruleset context.
2. Read `~/.claude/rulesets/core/code-review.md` for base severity scale.
2.5. **M2 subagent pre-review pass** — runs only if ALL hold:
   - `<cwd>/.claude/agents/magento-code-reviewer/SKILL.md` exists, AND
   - `--no-m2-agents` NOT in `$ARGUMENTS`, AND
   - **the diff clears the cost gate**: ≥3 files OR ≥150 changed lines OR touches a security-sensitive path. Below that, skip this step — an extra heavy agent on a small diff is not worth it.

   Then dispatch `magento-code-reviewer` for M2 idiom, DI, repository, ObjectManager,
   input validation, ACL, SQLi, file-system and secret-handling findings on the target diff.

   Instruct it to return a **findings table only** (`Severity | File:Line | Description | Fix`), no prose. In step 3, include only that table under an "M2-specific findings" section in the judge-prompt addendum. Do **not** paste the reports verbatim — the addendum is sent to both judges, so every line of prose is paid for twice.
3. Invoke `judgment-review` skill with the severity overlay above included in the judge prompt. If step 2.5 ran, append the "M2-specific findings" section to the addendum.
4. Aggregate findings (judgment-review verdict + M2 subagent findings if applicable); emit final report. Deduplicate findings (same file:line + same issue) — keep the most severe classification.

## Args

- `$ARGUMENTS` = optional path or diff spec, plus optional `--no-m2-agents` flag. If path is empty, default to the current branch diff. `--no-m2-agents` skips step 2.5 and runs legacy judgment-review-only flow.

## Fallback

If `judgment-review` skill API has changed and judge-prompt addendum mechanism doesn't work, wrap at the user-prompt level: invoke `judgment-review` plainly, then post-process its output to re-classify Magento findings per the overlay.
