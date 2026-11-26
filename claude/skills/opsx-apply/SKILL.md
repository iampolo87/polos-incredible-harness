---
name: opsx-apply
description: Hybrid OpenSpec apply. Use instead of openspec-apply-change / /opsx:apply whenever the user wants to implement, continue, or work through tasks of an OpenSpec change. Main agent implements coupled or small units itself; substantial independent units go to implementer agents tiered by model/effort (haiku / sonnet-medium / opus-high), in parallel when file ownership is disjoint. Review at coherent completion, stronger on foundational/security units. Triggers - "apply the change", "implement <change>", "continue the change", "/opsx-apply".
---

Implement tasks from an OpenSpec change with the execution discipline in
`~/.claude/rulesets/core/routing.md`, not opsx's loop. Supersedes the project-local
`openspec-apply-change` skill; same CLI, different loop.

## 1. Select change + load manifest

```bash
openspec list --json                                   # only if name ambiguous
openspec instructions apply --change "<name>" --json   # contextFiles, tasks, progress, state
```

- `state: blocked` → say which artifact is missing, suggest `/opsx:propose` / `/opsx:continue`, stop.
- `state: all_done` → suggest `/opsx:archive`, stop.
- Read `tasks.md`; read `design.md` when you will implement inline or need to split units. Delegated
  workers read design/specs in their own context.
- On `main`/`master` and git changes authorized: `git checkout -b opsx/<name>` first; otherwise work in the
  tree and say so. Worktrees only when parallel workers overlap.
- `CHECKPOINT=$(git rev-parse HEAD)`.

## 2. Plan units + lanes (one Bash batch: task text + `grep -ln`/`ls` to estimate files)

Group tasks into **units** (one module or one coherent outcome each), in dependency order. Then lane:

| Unit shape | Lane | Model / effort |
|---|---|---|
| Docs, config, wiring; small or tightly coupled to what you are already holding | **inline** (main agent) | lead |
| Transcription — design.md gives the exact code, 1–2 files, no decisions left | `implementer` + `model: "haiku"` | Haiku (effort-blind) |
| Substantial independent unit — normal feature/bugfix work | `implementer` | Sonnet / medium |
| **Foundational** (schema, interface, base class, anything ≥2 later units import), subtle cross-file invariants, security-sensitive paths | `implementer-deep`, or inline with the lead | Opus / medium, or lead |

When `tasks.md` carries `**Exec:**` lines (`planning-conventions.md`), they are the lane; use this table
only for untagged tasks, and warn once if a `[P]` task lacks `Exec:` or names an unknown agent. Tier is
fixed by frontmatter: never pass `model: "opus"` or `effort` to `implementer` — use `implementer-deep`.
Escalate one tier only on demonstrated difficulty and write why next to the task. When unsure between
haiku and sonnet, pick sonnet.

Announce once, before the first dispatch (one sentence, user can override):
"Units: U1 inline, U2+U3 parallel sonnet (files: …/…), U4 implementer-deep (foundational → reviewer after)."

## 3a. Inline lane

Per task in `tasks.md` order: implement → narrowest proof (`php -l`, tests for the task, build once at
the end; `setup:di:compile` only if DI changed) → flip `- [ ]` to `- [x]` → one Conventional Commit
when the user/task authorized commits (say so in the route sentence); otherwise leave the diff and report it.
TDD for behavior; `ponytail:` no TDD for pure wiring/config — say so in the commit body.

## 3b. Delegated lane

**Parallel is allowed** when units are independent: one message, one `Agent` call per unit, each brief
naming the files that worker owns. Coordinator (you) owns `tasks.md` and all commits; workers leave
changes uncommitted in a shared checkout, or commit only inside their own worktree
(`isolation: "worktree"`). Dependent units run after their prerequisite is `DONE`. Brief:

```
Change: <name>  (openspec/changes/<name>/)
Tier: <haiku|sonnet|opus> — <one-line reason; required for opus>
Files you own: <explicit list>; do not edit others — report NEEDS_CONTEXT instead.
Read first: design.md, then specs/<cap>/spec.md for the capabilities below. proposal.md only if
design.md leaves a question open. Do not survey the repo beyond these files and what tests point at.
Tasks (from tasks.md, these only): <verbatim task lines>
Contract: public signatures, return types, DTO/array shapes MUST match design.md — verify before
reporting. Flag any mismatch as BLOCKED, do not improvise.
Project context: <paste `context` from the instructions JSON, trimmed>
Git: <"leave changes uncommitted; I commit" | "commit in your worktree, one Conventional Commit per task">
Done = tests green for your tasks. Report ≤15 lines: status DONE|PARTIAL|BLOCKED, files changed,
test command + result, concerns.
```

After each unit returns:
1. `DONE` → coordinator runs the unit's tests, flips `- [x]`, commits if authorized (subject + ≤2 body lines).
   Foundational/security unit, or a `**Review:**` tag in `tasks.md` naming this unit/phase boundary →
   run that review now (`reviewer` Opus high by default, blind: design excerpt + `git log --patch
   $CHECKPOINT..HEAD`); fix confirmed findings; reset `CHECKPOINT`. A planned `Review:` is never
   skipped as "ordinary".
2. `PARTIAL` → one re-dispatch with its "remaining steps", one tier up (haiku → sonnet → `implementer-deep`).
   Second PARTIAL → stop, report.
3. `BLOCKED` / `NEEDS_CONTEXT` → stop, show the conflict, offer `/opsx:update`. Never patch design in
   the worker's head.
4. Contract changed mid-way → `SendMessage` the affected running worker; otherwise no chatter.

## 4. Finish

1. Run the change's full relevant test subset once over the branch.
2. Review at completion: first every `**Review:**` tag in `tasks.md` not yet executed, with the agent it
   names. Then proportionate: ordinary change → self-review + tests. Consequential (touches
   security paths, data integrity, shared contracts, or is going to main) → `reviewer` over
   `git log --patch <branch-base>..HEAD` if not already reviewed; `/judgment-review` or Sol via
   `herd-fleet` only when the user asks or the task authorized it. Announce backend/model/why in one line.
3. Show `N/M tasks complete` from `openspec instructions apply --change "<name>" --json`.
4. If all done: suggest `/opsx:archive`. Do not archive or merge unprompted.

## Guardrails

- Coordinator owns `tasks.md`, integration and git. No concurrent commits or index operations in one checkout.
- Pass the tier explicitly (subagent type + `model` for haiku); never rely on inheritance.
- No browser from implementers. `ui-verifier` when the change touches checkout/payment/auth flows or the
  user asks — one page per dispatch. Tests are the default proof.
- Keep opsx's pause rules: unclear task, design issue, error → stop and ask; do not loop.
