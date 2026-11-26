# Routing Policy (main loop) — the one authoritative execution policy

Read once per session, before the first spawn or code edit. Everything here overrides older
gates in `orchestration.md`, `CLAUDE.md`, skills and hooks; those files now point here. Skills
are tools you select, never startup mandates. Reply in English.

## 1. Scope assessment — one sentence, no ceremony

Do a bounded investigation (read what the request names, one targeted search, `m2graph` for M2 DI),
then state the route in one sentence: workflow level, planning depth, tests, delegation, model/effort.
No router agent, no mandatory planning skill, no classification step. Example:
"Direct: two-file bugfix in the token repo, failing test first, inline, Opus medium."

Evidence budget: one read batch (≤3 calls, ~10k tokens). If understanding needs more than that or
>~5 sequential lookups, one `Explore` (haiku) with a ≤2k-token `path:line` handoff — never for reading
before an inline write.
Clarify only material *product* ambiguity (scope, observable behavior, compatibility, acceptance).
Technical uncertainty is investigated, not asked.

Turn endings: when the next step is obvious, reversible and inside the authorized scope, do it
instead of ending with "Want me to…?". Ask only for product decisions, destructive or outward-facing
actions, or scope expansion.

## 2. Workflow levels — pick the lightest that holds

| Level | When | Artifact |
|---|---|---|
| **Direct** | Change is understood and bounded | none (the diff, and the commit message when a commit is authorized, are the record) |
| **Brief** | Needs acceptance criteria, approach, dependencies, progress or verification written down; or another session could not safely resume from the original request and current diff alone | one concise existing artifact (`tasks.md`, ticket, PR body) or an external brief, plus a compact work-state pointer |
| **Spec** | Durable behavior contract reused across components, people or sessions; or user asks for OpenSpec | OpenSpec change via `/opsx:propose` → `opsx-apply` |
| **Plan** | Sequencing, migration, staged release, rollback or dependency complexity | implementation plan (`writing-plans` / `claude-mem:make-plan`) then execute |

Not triggers: `openspec/config.yaml` present, line count, file count, ambiguity alone. Explicit
`/opsx:*`, `/writing-plans`, `/make-plan`, brainstorming requests are honored as asked. A route may
grow when evidence changes — add the artifact, keep completed work.

**Tracking and recovery (Brief and above).** Reuse an existing Spec or Plan instead of creating another
document. Without an approved project artifact, use `~/.claude/odd/<repo>/<feature>.md` — never
`tasks/<feature>.md` inside a client repo, never the harness-owned `~/.claude/tasks/`. Preserve material
user wording, decisions, checks and next steps. Research/review-only requests create no artifacts unless
the user asks for saved output or tracking.

1. Before tracked implementation, identify repository, branch, baseline, artifact and actual memory scope; announce the artifact once.
2. On recovery, inspect injected state; read the exact list if incomplete. Select only work the current request continues, never the newest item automatically.
3. Reconcile artifact, branch, diff and observed checks before editing; restate the task in ≤10 bullets after compaction.
4. Give workers artifact/section references, allowed files and checks; reviewers receive requirements and candidate without implementer conclusions.
5. Update state/artifact at meaningful boundaries and accepted corrections; reopen only invalidated tasks and preserve valid work.
6. Keep checkpoints short: artifact locator, branch/baseline, last verified candidate, blocker, next step; no document mirrors, secrets or raw dumps.
7. Close task entries and the list only after observed completion; a checkpoint never proves the current checkout still matches it.
8. If memory is unavailable or differently scoped, use the artifact and disclose pending updates; never invent success or silently duplicate state.

**Work-state scope.** claude-mem keys state by its MCP server's `cwd`; shell `cd` does not move it, so
prefer starting tracked sessions in the target repository. Name lists `odd/<repo>/<feature>`, where `<repo>`
is the parent of `git -C <checkout> rev-parse --path-format=absolute --git-common-dir`, relative to
`~/projects`, with `/` and `.` replaced by `-` (same as the MemPalace wing rule): linked worktrees share the
key, nested repos keep their full relative path. If the layout does not permit this, resolve the identity
explicitly instead of guessing. Simultaneous features need distinct identities. Umbrella session
(`~/projects`): namespacing prevents collisions but not the shared bucket or the 3,000-char startup cap —
record `memory_cwd`, read the exact list and validate its repo. A later session with another scope uses the
external artifact if the list is unavailable; reconcile before any deliberate migration.
List fields: `status`, `repository`, `memory_cwd`, `branch`, `document`, `baseline`, `next_step`, `blocker`
(`null` clears); task entries use `task` + `status` (`todo|doing|done|dropped`); `fields` JSON ≤ 2,000 chars.
`S#`/`T#` IDs only when the document already uses them. Implementation agents cannot call
`work_state_write`; the main agent owns shared progress.

## 3. Testing — independent of level

- Reproducible bug or business behavior: failing test first, then the fix (`test-driven-development`).
- Existing regression/integration suites stay in the loop; run the relevant subset before claiming done.
- UI change: browser proof when layout or flow is the question (`ui-verifier`, one page per dispatch).
- Mechanical edits: proportionate check (`php -l`, build, grep for stragglers).
- Never skipped: validation at trust boundaries, data-loss handling, security, accessibility, platform rules.
- `verification-before-completion` before any "done".

## 4. Delegation — outcomes, not steps

Main agent implements tightly coupled or small work itself. Delegate when one of these holds:
- a substantial *independent* outcome (a module, a component, a migration script);
- context-heavy bounded investigation (`Explore` haiku, `opsx-recon`, `cavecrew-investigator`);
- repetitive batches (N similar files);
- independent review (blind brief: requirements + diff, never the implementer's conclusions).

Not reasons to delegate: a grep touching >2 files, a writer touching application logic, a rule saying
"main never codes", an MCP result that might exceed 50 lines. Shape the query first (bounded
`LIMIT`, explicit fields, selector); delegate only when the *outcome* is worth isolating.
Workers own implementation, tests and fixes through completion and report
`DONE | PARTIAL | BLOCKED | NEEDS_CONTEXT` with files changed and check outcomes. Workers do not commit
unless their brief says so.

**Git.** Commits, pushes and PRs happen only when the user or the task authorized them (CLAUDE.md
§ Commits format applies). "Done" is a verified diff, not a commit.

**Concurrency.** Independent units run in parallel (one message, several `Agent` calls) with explicit
file ownership per worker: before any writer spawn, derive a nonempty `Allowed edit surfaces` list of
narrow repository-relative paths/globs — never `.`, bare repo root, or absolute paths; never ask the user
to author them. Coordinator owns shared task/progress files (`tasks.md`) and all git
integration. Workers never commit or touch the index concurrently in one shared checkout: workers leave
changes uncommitted for the coordinator, or each gets a worktree (`isolation: "worktree"`) and commits
there only when its brief says so.
Overlapping edits → worktrees or sequential.

**Communication.** Named subagents may `SendMessage` each other; use it only for concrete dependencies:
"contract changed", "prerequisite ready", "finding invalidates your assumption", blockers, outcomes.
Independent reviewers stay blind until their initial findings are in.
Resuming a parked subagent (`SendMessage` after its hand-back) is cheap only while its prompt cache is warm:
1h for `implementer` / `implementer-deep` (frontmatter `cacheTtl`), 5 minutes for every other agent. Past that,
the resume re-writes the whole inherited context at write price — spawn a fresh agent with a narrow brief instead. Never enable broad cross-session inbound
acceptance globally and never message sessions unrelated to the task. Herdr (`hc`) delegates only for another
backend (Codex/Antigravity review, second opinion) or a session the user wants to watch; announce
backend/model/why in one line, no extra approval gate beyond the task's authorization.

## 5. Review — proportionate, at coherent boundaries

- Risk line: close every code change, inline or delegated, with `Risk: item N (reason)` or `Risk: none`,
  where N is one of (1) irreversible data effects, (2) security, (3) consumed contracts, (4) concurrency,
  (5) delivery/environment, (6) no test would catch a regression. Any item → independent review below.
- Ordinary change: self-review + tests. Independent review when the change is consequential or the
  user asks. No automatic review every N files or lines; no fixed line-cap fragmentation.
- Consequential = security-sensitive paths, data integrity, compatibility/shared contracts, pre-merge to main.
  Stronger checks there: `reviewer` (Opus high, read-only) or `/judgment-review` (pinned judges), plus
  Sol via herdr when a cross-family read is wanted and the task authorizes Codex spend.
- `judgment-review` and `m2-review` keep their own contracts when invoked.
- Every review cites the exact revision or candidate, the commands run with outcomes, and unresolved uncertainty.
- Correction rounds: fix confirmed blockers in one batch, recheck affected checks, allow one targeted follow-up
  for a persisting blocker, then report the unresolved proof. Never claim completion over a known blocker;
  never auto-launch expanding full-review sweeps.
- Re-review of a correction round (round 2+): one reviewer, scoped to the delta since the previous candidate, Sonnet
  `general-purpose` unless the fix touched a consequential path. Dual blind reviewers only on round 1.
- Default off: RDD machinery, receipt services, multi-judge consensus.

## 6. Model and effort baseline

| Role | Model / effort | Mechanism |
|---|---|---|
| Lead (this machine) | Fable 5.1 **medium** (`settings.json` `model: "fable"`; Opus 5.5 medium when the session is switched to Opus); `/effort high` at session start for hard architecture/investigation — a mid-session effort switch invalidates the prompt cache | `settings.json` `model` + `modelSettings["claude-fable-5-1"]` (and `["claude-opus-5-5"]`) |
| Ordinary planning | inline with the lead | — |
| Implementation | `implementer` = Sonnet medium | frontmatter pin |
| Demanding implementation | `implementer-deep` = Opus medium (state why in the brief) | frontmatter pin |
| Mechanical, tightly specified; cheap verification | `implementer` + `model: "haiku"`, `Explore` haiku | haiku is effort-blind |
| Ordinary independent review | `general-purpose` sonnet, blind brief | inherits session effort |
| Consequential review | `reviewer` = Opus high, read-only | frontmatter pin |
| Adversarial judges | `judgment-judge-opus` opus medium, `judgment-judge-sonnet` sonnet low, `judgment-fixer` sonnet low | frontmatter pins — do not override |

Effort precedence (docs, ≥2.1.292, installed 2.1.314): see the ordered list below. The `Agent`
tool has an `effort` param, to be passed only when the user, a plan's `Exec:` line, or a skill asks for
it (ignored for `fork`); without it, built-ins (`general-purpose`, `Plan`, `Explore`) inherit the session's
active effort — so a nameless Opus spawn under an Opus-medium lead is medium, never "Opus high".
Documented precedence (sub-agents docs, ≥2.1.292): `CLAUDE_CODE_EFFORT_LEVEL` env > per-invocation
`effort` param > frontmatter `effort` > session effort. Policy, not a limitation: never pass `effort` to a
pinned custom agent — pick the agent whose pin matches, so the agent name alone tells the reader the
tier. Plans name the agent per task (`planning-conventions.md`, `Exec:` tag).
Global `effortLevel` is `high` as the *fallback* for models without a `modelSettings` entry; it is not a
cap — a session override (`/effort xhigh`, `--effort`) is what nameless spawns inherit, so check the
session's active effort before a `general-purpose`/`Plan` spawn matters.
Every custom sonnet/opus agent declares `effort:`. Escalate on demonstrated reasoning difficulty,
not on a failed test or missing credentials.

## 7. Scenario matrix (static reference)

| Scenario | Route |
|---|---|
| Typo, config, one-liner | Direct, inline, proportionate check; commit only when the task/user authorizes it |
| Reproducible bug, ≤ a few files | Direct, `systematic-debugging`, failing test first, inline |
| Ordinary feature, one module | Direct or Brief; inline or one `implementer`; tests; self-review |
| Migration / auth / payments change | Plan or Spec; `implementer-deep` for the core; `reviewer` or judgment-review |
| User says `/opsx:propose` | Spec; propose only, stop (planning boundary) |
| User says "implement X" and Spec was chosen | propose → validate → `opsx-apply` in the same session |
| Independent parallel components | Brief; N workers with file ownership; coordinator integrates |
| Missing product information | ask once, then proceed under stated assumption where safe |
