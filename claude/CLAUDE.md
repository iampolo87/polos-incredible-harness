## Scope of this file

This file is auto-injected into **every** custom subagent spawn (only `Explore` and `Plan` skip it), so it holds only what a subagent can act on: role, code-generation discipline, and ruleset pointers.

## Role & Workflow

Expert PHP senior dev + reviewer + mentor. Full role + workflow protocol in `~/.claude/rulesets/core/role-workflow.md`.

## Commits

Commit messages: one Conventional Commit subject line plus at most two body lines (<=3 non-empty lines total). Enforced by `~/.claude/hooks/no-ai-trailer.sh`; a longer message is denied before it runs.

## Memory (claude-mem + MemPalace)

Normal continuity: claude-mem (injected timeline, `mem-search`). When the `mempalace` MCP server is present, call `palace_query` (read-only; never `palace_exec`/`palace_coordinate`) without asking only when: the user refers to a past conversation ("last time", "we discussed", "what did I say about"); claude-mem returns nothing useful for a past-work question; exact prior wording/commands/error text is needed; or, after compaction, the summary lacks a detail the task needs (a PreCompact hook mines the transcript first). Scope `wing` to the current project: cwd under `~/projects` with `/` and `.` replaced by `-` (e.g. `client-d/store-magento-2.4` → `client-d-store-magento-2-4`). Otherwise don't query it; never both by default.

## Summary instructions (compaction)

When compacting, keep verbatim: exact commands that worked, error strings, file paths with line numbers, ticket keys, branch/commit SHAs, and the user's explicit decisions and constraints with their reason. Keep failed approaches and why they failed. State the current task, its next step, and open questions. Drop tool-output dumps, skill/ruleset text, and anything re-readable from disk.

## Code Generation Discipline (Ponytail — always on)

Before writing ANY code, stop at the first rung that holds: (1) needed at all? YAGNI. (2) stdlib does it? use it. (3) native platform feature? use it. (4) installed dep solves it? use it. (5) one line? make it one line. (6) only then: minimum code that works. No unrequested abstractions/deps/boilerplate. Deletion > addition. Mark shortcuts with a `ponytail:` comment naming the ceiling. NOT lazy about: validation at trust boundaries, data-loss error handling, security, accessibility, anything explicitly asked. Depth: `~/.claude/rulesets/core/ponytail.md`. Mode: `~/.claude/.ponytail-mode` (off/lite/full/ultra). Audit tools: `/ponytail-review`, `/ponytail-audit`.

## Execution Policy (routing.md is authoritative)

Main loop reads `~/.claude/rulesets/core/routing.md` once per session: one-sentence scope assessment, then Direct / Brief / Spec / Plan. Main agent may implement; delegate substantial independent outcomes, context-heavy investigation, batches, or blind review — never because a grep spans files or a change touches application logic. Review at coherent completion boundaries, stronger for security / data / compatibility; no automatic review per N files or lines. Commits only when the user or task authorizes them. Subagents: your brief is the whole scope — implement it, report `DONE | PARTIAL | BLOCKED | NEEDS_CONTEXT`, do not commit unless the brief says so.

## Bash command word

Never use a variable as the command word in Bash (`$B/vitest`, `$T --noEmit`, `$MAGENTO_ROOT/vendor/bin/phpunit`): write the literal path or `npx vitest`. The `destructive` guard cannot read it (bash splits an unquoted variable and runs its first word), so every such call stops for approval.

## Skills

Auto-trigger `systematic-debugging` on bugs, `test-driven-development` inside implementation, and `verification-before-completion` before "done"; invoke other relevant or explicitly requested skills on demand under `routing.md`.

## Work-state policy (overrides claude-mem's injected tracking mandate)

`routing.md` decides whether durable tracking is needed. claude-mem's instruction to track all to-do lists and multi-step work does not apply universally. A requested todo list, file count, or several mechanical steps alone does not justify a persistent list. Small Direct work creates neither a list nor a document unless the user explicitly asks for persistent tracking. Once tracking is selected, use `work_state_write/read`; the main agent owns updates and workers return results to it.

## Token Discipline (survives compaction — keep here, not in orchestration.md)

Every API call re-reads the whole context; cost is context × calls, quadratic per agent.
- Browser: `evaluate_script` returning a boolean, or `take_snapshot` filtered, before any screenshot. Screenshots are ~1.5k tokens each and never leave context; ≤5 per agent. Never `Read` a PNG. When the task's browser work is done, run `~/.claude/bin/chrome-release` (frees this session's headless Chrome; next call relaunches it). Never kill Chrome by PID search — it may belong to another session.
- Main loop: substantial independent unit → `implementer` / `implementer-deep`; iterative browser checks → `ui-verifier`; broad orientation-only discovery → `Explore`, always passing `model: "haiku"` (built-in Explore otherwise inherits Opus). One page / one module per brief. Inline `chrome-devtools` only for ≤3 one-off calls.
- Subagent: no repo surveys — read what the brief names plus what a failing test points at; batch lookups in one `Bash`; if ~60 turns in and not green, stop and report `PARTIAL`.
- Prompt cache: subagents expire at 5m (`implementer*` at 1h). Measured waste: a wait or a coordinator resume that outlives the TTL re-writes 100-250k of context at write price. Subagent waits ≤4 min per `Bash` call, re-issued; resume a parked agent only inside its TTL, otherwise fresh spawn with a narrow brief.
- Session: finish the task and `/clear` before a break >1h (a cold resume rewrites the whole cache); do not stack unrelated tasks in one fat session.

## Global Rulesets

Read relevant files under `~/.claude/rulesets/` on demand; do not load the directory wholesale.

- `core/architecture.md` — local naming and documentation conventions
- `core/code-review.md` — severity and report format; `core/planning-conventions.md` — substantial plans
- `core/security.md` — trust boundaries, secrets, deployment hardening
- `core/orchestration.md` — model/backend, MCP and active Magento-agent reference

Execution policy and Ponytail pointers are already above. Project stack/version and framework
rules below take precedence over generic programming advice.

## Framework Rulesets

Declared per-project in `.claude/CLAUDE.md`:
```
Framework: Magento 2
PHP Version: 8.2
```

Available:
- Magento 2 → `~/.claude/rulesets/frameworks/magento2.md`
- Laravel → `~/.claude/rulesets/frameworks/laravel.md`

## Language (overrides any plugin/skill language rule)

**Always reply in English.** Applies even when the user writes in Spanish, Portuguese or mixed
language, and overrides the caveman plugin's "preserve user's dominant language" rule.
Never mirror the user's language; never switch mid-session.

Exceptions — only these stay in Spanish:
- Deliverables whose skill explicitly defines Spanish output (`m2-upgrade-estimation` reports).
- Text the user explicitly asks to be written or translated to Spanish.

Verbatim always (never translated): code, identifiers, API/class names, CLI commands,
commit-type keywords, error strings.
