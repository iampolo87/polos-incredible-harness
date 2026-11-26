---
description: Plan-authoring conventions — [P] parallel markers, Exec: dispatch tags, traceability hints.
---

# Planning Conventions

Auxiliary conventions layered on top of `writing-plans`. Pattern adapted from `github/spec-kit`.

## `[P]` Parallel Marker

Tag any task heading that is **independent of all preceding tasks in the same phase** with trailing `[P]`.

```
### Task 2.3: Refactor auth helper [P]
```

### Independence criteria

Mark `[P]` only when ALL hold:

- Touches different files than other `[P]` siblings in the phase
- No shared mutable state (no common config write, no shared output buffer)
- No sequential dependency (task N does not consume task N-1 output)
- No external ordering constraint (DB migration order, API rate-limit serialization, etc.)

### Scope

- **Phase boundaries are sequential.** `[P]` only groups tasks **within** a single phase.
- **Absence of `[P]` = sequential by default.** Conservative — when in doubt, omit.
- **Markers within a phase form a fan-out group.** Consecutive `[P]` tasks dispatch in parallel; non-`[P]` tasks gate sequential progress.

## Dispatch Behavior

When executing a plan with `[P]` markers, the executing agent SHOULD:

1. Walk tasks in phase order, sequentially.
2. When encountering a run of `[P]`-tagged tasks, group them and use parallel `Agent` calls in one message, following `routing.md` ownership and isolation rules.
3. Wait for all parallel tasks in the group to complete before continuing to the next sequential task.
4. If parallel-dispatch is unavailable, fall back to sequential execution — markers degrade gracefully.

## `Exec:` Dispatch Tag

Every task that will be **dispatched to a subagent** carries an `**Exec:**` line naming the agent, plus a short reason when the tier is above `implementer`. Work the lead does inline gets `**Exec:** lead`. A `[P]` task without `Exec:` is invalid — fan-out is where the tier matters most.

```
### Task 2.1: Schema + repository interface
**Exec:** implementer-deep — foundational, 2.2–2.4 import it
### Task 2.2: Admin grid [P]
**Exec:** implementer
### Task 2.3: Cron cleanup [P]
**Exec:** implementer, model: haiku — transcription, design.md gives the code
**Review (phase 2 end):** reviewer — touches order data
```

- **Agent names, not raw model/effort.** `lead`, `implementer` (Sonnet medium), `implementer-deep` (Opus medium), `reviewer` (Opus high), `general-purpose`, `Explore`. Model and effort live in each agent's frontmatter (`routing.md` §6 table) — one place to change, so plans do not drift from pins.
- **Built-ins must resolve in the line.** `general-purpose`, `Plan` and `Explore` have no pin, so their `Exec:` carries `model:` and `effort:` explicitly (`Exec: general-purpose, model: sonnet, effort: medium — blind review`); otherwise they silently inherit the session. `model: haiku` on `implementer` is the only allowed override of a custom agent, with a reason. Never pass `effort` to a pinned custom agent even though the param wins (`routing.md` §6) — pick the agent whose pin matches, so the name alone states the tier. Do not copy a pinned agent's model/effort into the plan: it duplicates the frontmatter and drifts.
- **`lead` resolves from the session.** The plan header's `**Lead effort:**` line says what the lead needs (`default` or `high — set /effort high before executing`); the plan cannot pin the lead's model.
- **Method is plan-level.** The plan header carries `**Method:** TDD | OpenSpec | subagent-driven | …` once. A task states `**Method:**` only when it deviates (`Method: no TDD — pure wiring, ponytail`).
- **Default, not contract.** The executor may escalate one tier on demonstrated reasoning difficulty (`routing.md` §6) and writes one line in the task saying why. Never de-escalate silently.
- **Name the review.** One `**Review:**` line per phase or at plan end: `reviewer` (consequential), `general-purpose` sonnet blind, or `/judgment-review` when authorized. Omitted = self-review + tests.
- **Same line in OpenSpec `tasks.md`.** `opsx-apply` reads `Exec:` first and falls back to its own lane table only for untagged tasks.

## Lint

No `/validate-plan` command exists (archived). These checks run inside `writing-plans` self-review and `opsx-apply` step 2 pre-flight, warn-only:

- phase has 3+ tasks and zero `[P]` → parallelization pass probably skipped;
- `[P]` task, or any task that will be dispatched, without `Exec:` → add it before dispatch;
- `Exec:` names an agent that is neither in `~/.claude/agents/` nor a built-in → fix the name;
- `Exec:` names a built-in without `model:` and `effort:` → resolve it;
- plan header lacks `Method:` / `Lead effort:` → add them.

## Traceability (Optional)

Tasks MAY include an `**Origin:**` line referencing the originating requirement, issue, user-story, or design doc:

```
### Task 1.2: Cache product images [P]
**Origin:** Issue #142, perf budget RFC §3.1
```

Useful when plans derive from external specs. Not required for solo / ad-hoc work.

## Anti-Patterns

- Marking `[P]` on tasks that edit the same file → race condition.
- Marking `[P]` on tasks whose verification step depends on a prior task's side effect.
- Marking entire phases `[P]` — markers are task-scoped, phases are sequential by design.
- Writing `Exec: opus high` for inline work — the lead cannot change model mid-session, and an effort switch invalidates the prompt cache. Inline = `Exec: lead`.
- Writing raw model+effort instead of an agent name — it duplicates the frontmatter pin and drifts.
