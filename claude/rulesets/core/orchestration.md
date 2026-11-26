# Orchestration Reference (main loop only)

> **Policy lives in `routing.md`** (`~/.claude/rulesets/core/routing.md`) — read that one file at
> session start. This file is the reference behind it: model/backend facts, MCP routing tables,
> M2 subagent map, memory. Consult sections on demand; nothing here is a startup mandate.
>
> **Why separate from CLAUDE.md.** `~/.claude/CLAUDE.md` is auto-injected into every custom subagent
> spawn. Everything here is main-loop only, so shipping it there paid ~3k tokens per spawn for nothing.
> Referenced by plain path, deliberately not `@`-imported (an import is inlined into CLAUDE.md).

## Communication Mode

Caveman mode (full) by default, delivered by the caveman plugin's `SessionStart` hook. Do not also set
`outputStyle: caveman` in settings: it duplicates the hook payload.
Deactivate only on "stop caveman" / "normal mode". Language: English always (CLAUDE.md).

## Skills — on demand

Invoke a skill when its trigger matches the actual request or the user names it.
Auto-trigger `systematic-debugging` on bugs, `test-driven-development` inside implementation,
and `verification-before-completion` before claiming done; `routing.md` governs workflow scope.
OpenSpec: `/opsx:*` when the user asks or `routing.md § 2` selects Spec.
Project opsx files carry managed headers (`~/.claude/tools/opsx-patch.sh`, idempotent — re-run after
`openspec update`): apply → `opsx-apply`; propose/explore → recon via `opsx-recon`; propose →
"implement-continues" rule (standalone `/opsx:propose` stays planning-only).

## Model Routing — facts

Aliases resolve to the current model of each tier (`sonnet`, `opus`); the lead model is set in
`settings.json`. Re-probe after a model release. Baseline per role is the table in `routing.md § 6`.

**Effort precedence (docs, CC ≥2.1.292):** `CLAUDE_CODE_EFFORT_LEVEL` env > per-invocation `effort`
param > agent frontmatter `effort` > session's active effort.
Session effort = `--effort` flag > `modelSettings[<lead model>].effortLevel` > global `effortLevel`
(`high`). `/effort` sets the session and saves it. The `Agent` tool has an `effort` param (pass it only
when a plan's `Exec:` line, a skill, or the user asks; by policy not on pinned custom agents — the agent
name must carry the tier); `Workflow`'s `agent()` has one too. Without it, built-ins (`Plan`, `general-purpose`, `Explore`) carry no frontmatter and
inherit the session effort. Haiku has no `effort` capability — haiku agents cost nothing extra at
any inherited level, so `Explore`, `cavecrew-*`, `magento-*-analyst` are non-issues.

**Custom agents (all pin `effort:`; keep it that way):**
- `implementer` sonnet/medium, `maxTurns: 80`, no browser, no `Agent` — one unit ≤ one module.
  With `model: "haiku"` for transcription units (exact code in the spec).
- `implementer-deep` opus/high — foundational, subtle invariants, security paths; one-line reason in the brief.
  Never `implementer` + `model: "opus"` (that is Opus at medium).
- `reviewer` opus/high, read-only — consequential review when judgment-review is not invoked.
- `ui-verifier` sonnet/low, `maxTurns: 30`, read-only — one page or flow per dispatch, after the change is in the working tree.
- `judgment-judge-opus` opus/medium, `judgment-judge-sonnet` sonnet/low, `judgment-fixer` sonnet/low —
  pinned adversarial-judge contract; model-class diversity required. Do not override.
- `cavecrew-builder` sonnet/low lives in the caveman plugin cache — re-check after plugin updates.

**Built-ins:** `Plan` → pass `model: "opus"` (planning quality drops on sonnet); ordinary planning
stays inline with the lead. `general-purpose` → `model: "sonnet"` for routine work; a one-line reason
in the prompt when you pass opus. `Explore` → `model: "haiku"` (the `explore_model` rule of
`claude-policy` enforces).

**Do not shadow `Explore`** with `~/.claude/agents/Explore.md`: it replaces the tuned built-in prompt
for zero savings. The agent registry loads at session start; new agent files need a new session.

### Cross-Backend Routing — Codex / Antigravity

Three backends via herdr-core (`hc`): Claude Code (primary, abundant quota), Antigravity (`agy`, not metered
against Codex), Codex CLI (**metered, small plan**; the review model is `model` in `~/.codex/config.toml`).
Claude does everything by default; buy only model diversity from Codex.

```
Claude Code implements, explores, iterates
  └─ Codex review model     → independent review of completed diffs
       └─ Codex top model   → escalation only
```

A Codex pane loads its own instruction hierarchy (`~/.codex/AGENTS.md`, rulesets, skills, agents) but
not this conversation, Claude's MCP set, claude-mem or cavecrew personas; `.claude/CLAUDE.md` reaches
it only via the explicit compatibility read in `~/.codex/AGENTS.md`. Brief the diff, scope and finding.

- **Review model (template `cdx-sol`)** — routine cross-family review of a completed, consequential diff
  (`routing.md § 5`). Diff + requirements only.
- **Top model** — escalation only: the review model and Claude disagree on a finding that matters;
  stuck root cause; security/architecture decisions; long one-shot deliverables (`m2-upgrade-estimation`,
  advisories, `pathfinder`, multi-phase `writing-plans`). Budget a few per week, full brief, one shot.
  Never: main-loop orchestration, recon, mechanical edits, routine review, `Workflow` fan-outs, iteration.
- **Any other Codex model — never unless the user names the model in that request.**
  > **The verdict stands on QUOTA, and is not open for re-derivation:** a large diff on the wrong model
  > consumes a small Codex plan in minutes. No autonomous substitution, no quiet downgrade — if the
  > intended model is unavailable, say so and stop.
- **No fallback.** Quota exhausted → report and stop.

Dispatch goes through the `herd-fleet` skill: one line naming backend/model/why; no separate approval
gate beyond the task's authorization for Codex spend.

### Delegation transport — native subagents are the default

| Work | Transport |
|---|---|
| Small lookup, or an edit tightly coupled to what you are doing | main agent, directly |
| Independent discovery across files | `Explore` — name the constraints in its brief (it skips CLAUDE.md) |
| Bounded implementation | `implementer` / `implementer-deep`, explicit file ownership |
| Review within the same provider | `reviewer`, `general-purpose` sonnet (blind brief), judgment-review |
| Cross-provider review or second opinion | herdr (`agy`, `cdx`) |
| Work needing ongoing human observation or terminal interaction | herdr |

Three qualifications: **delegate an outcome, not a step**; **a summary is a navigation aid, not
implementation context** (require file:line, scope searched, checks run, unresolved uncertainty; the
implementing agent reads the source itself before consequential edits); **a separate process is not an
independent reviewer** — independence comes from a clean brief, ideally a different model family.

### Delegation thresholds — advisory

Main-loop context persists; subagent context is transient. Prefer `Explore` for orientation-only
sweeps across many files or naming conventions where you need the conclusion, not the dumps. Read
inline when you will act on the content next. **Oversized result recovery:** a search that already
succeeded is done — do not re-run it through Explore; narrow the *next* read instead.

### Runaway lessons

Open-ended `general-purpose` "implement Task N" agents run to hundreds of turns, with a browser and
dozens of screenshots each, at an inherited effort nobody chose. Rules kept:
- One brief = one page / one module; split before dispatch. Cost per agent is quadratic in turns.
- Implementation → `implementer` (`maxTurns`, no browser). Browser → `ui-verifier`, after the change is in the working tree.
  Snapshot/`evaluate_script` first; screenshots ≤5 per dispatch; never `Read` a PNG in the main thread.
- `autoCompactWindow` in settings is the safety net under `maxTurns`.
- Cold resume rewrites the whole cache: finish and `/clear` before a break >1h.
- Re-audit base context per call when adding plugins or MCP servers.

## Worktree + Scheduling Pointers

Parallel or risky work: `isolation: "worktree"`. Polling:
`/loop <interval> <command>`; cron: `/schedule`.

## M2 Subagent Routing

If the project's `.claude/agents` links to a `magento-agents` checkout, use its `AGENTS-INDEX.md`
for the active agents (upgrade specialist, code reviewer, issue debugger).
Ordinary implementation uses the main agent or bounded implementers; read-only discovery uses
`Explore`. Route by the work, not by technology labels.

## Memory (claude-mem)

Search past work: `claude-mem:mem-search` or `mcp__plugin_claude-mem_mcp-search__search`. Fetch by id:
`get_observations`. Capture is passive via hooks.

## MCP Auto-Use Rules

**Scope policy** — servers global by default; tool definitions are deferred, but each server's tool names,
its server instructions and its connection at startup still cost every session. Move a server that one
project uses to that project's scope. Per-project values via `direnv` `.envrc` (mode 600, git-excluded);
launch from a direnv-loaded shell. Disable per project via `/mcp` (persists to
`projects.<path>.disabledMcpServers`). Never write API keys into a project `.mcp.json`.

**Context7** — `resolve-library-id` then `query-docs` for library/API docs. Auto-invoke.

**Chrome DevTools** — navigate → wait_for → take_snapshot → interact via UIDs. Prefer snapshot over
screenshot; `includeSnapshot: false` on input actions unless the updated state is needed.

**m2graph** — Magento 2 DI graph over the *merged* config (disabled modules, XML comments, areas,
interface inheritance, load order). `m2_status` first in an unfamiliar repo. **Use instead of grep/Explore:**

| Question | Tool |
|----------|------|
| "what plugins intercept X" | `m2_plugins` (pass `area`) |
| "which class wins for interface/type Y" | `m2_preference` |
| "what observers listen to event Z" | `m2_observers` |
| "what does plugin P intercept, and where" | `m2_intercepts` |
| "resolve virtualType V" / "what's built on T" | `m2_virtualtype` |
| "who owns class C, is it enabled" | `m2_class` |

grep on `di.xml` returns wrong answers: it names a disabled module's preference as the winner and a
commented-out plugin as live. Still grep/Explore for plugin bodies, layout XML,
`db_schema.xml`, `system.xml`, templates, JS. All m2graph tools inline (<30 lines).

### MCP result handling — shape first, delegate an outcome only when useful

1. **Bound the query** (rules below). Most calls then fit inline.
2. **Inline** when you act on the result next, or it is small: `evaluate_script` with a shaped return,
   `click`/`fill`/`navigate`/`wait_for`, `describe-table`, `list-*`, aggregated NRQL, JQL with
   `maxResults ≤ 5` and explicit fields, Confluence search titles/excerpts.
3. **Delegate** (haiku for extraction, sonnet for synthesis) when the *outcome* is worth isolating —
   e.g. "find the UIDs for the checkout form" from a full `take_snapshot`, "summarize this 40-comment
   Jira thread", "which of these 200 network requests failed", `performance_analyze_insight`.
   Template: "Call `<tool>` with `<params>`. Return ONLY `<fields>`, ≤30 lines, `[truncated: N more]` if cut."
4. Screenshots go through `ui-verifier` (≈1.5k tokens each, persist in context; ≤5 per dispatch).

### MCP Query-Shape Rules

**NRQL** — `LIMIT N` (≤100) or an aggregate (`count`, `average`, `percentile`, `FACET`, `TIMESERIES`);
default `SINCE 1 hour ago`; prefer `FACET` over raw rows; never `SELECT *` on event tables.
**MariaDB** — `LIMIT N` on any non-aggregate `SELECT`; list columns, no `SELECT *` on production
schemas; `EXPLAIN` before large analytical queries.
**Atlassian** — `maxResults`/`limit` ≤10 and explicit `fields` on every search/get; Confluence bodies only
when the title clearly matches; read-only unless the task asks for a write. Tools are deferred: load via
ToolSearch (`"+atlassian jira confluence"`), user-scope server name is `atlassian`.
**Chrome DevTools** — `evaluate_script` returning a JSON summary over `take_snapshot` when the selector
is known; perf flow: `performance_start_trace` → scenario → `performance_stop_trace` → delegate
`performance_analyze_insight`.
