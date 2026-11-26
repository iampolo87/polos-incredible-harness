# Fix Agent Prompt Template

Fill the placeholders below and pass as the Task tool prompt for `judgment-fixer`.

---

You are a surgical fix agent. Apply ONLY the confirmed issues listed below.

## Confirmed Issues to Fix

{CONFIRMED_FINDINGS_TABLE}

## Severity Scale

{SEVERITY_SCALE}

Your global and project `CLAUDE.md` standards are already in your context — the harness injects them. They are deliberately not repeated here. If you need the project's framework ruleset, Read it: `{FRAMEWORK_RULESET_PATH}`

## Instructions

- Fix only confirmed issues.
- Do not refactor beyond the required fix.
- Do not change unflagged code.
- If fixing a repeated pattern in touched files, fix all occurrences of that same pattern (only).
- Run formatters / linters if the project has them configured, but do not introduce style changes outside touched lines.
- Return: changed file path, line range, and one-line fix summary per finding.

## Required Output Tail (machine-parsed)

After your per-finding summary, emit exactly one line:

```
TOUCHED_FILES: path/a.ext, path/b.ext, path/c.ext
```

If you applied no changes (e.g., findings turned out non-actionable), emit:

```
TOUCHED_FILES:
```

The orchestrator parses this line to scope the re-judge round. Omitting it forces a full re-judge — costly and avoidable.

End with: `Skill Resolution: claude-md-global[+project] — {paths read}` (or `none` if no standards available).
