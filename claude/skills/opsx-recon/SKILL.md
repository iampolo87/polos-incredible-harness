---
name: opsx-recon
description: Codebase recon for OpenSpec propose/explore, delegated to a Haiku Explore agent so the main thread writes artifacts from a file:line map instead of surveying the code itself. Invoked by the patched /opsx:propose and /opsx:explore when the recon is context-heavy; also use before drafting any OpenSpec artifact that needs broad codebase facts.
---

Delegate context-heavy surveys (many files, naming conventions, unknown entry points). Targeted reads of files you already know stay inline — this skill is for the sweep, not a ban on reading code.

## 1. Frame the questions (main thread, no tool calls)

From the user's request (and the change name, if any) write 3–6 concrete questions the artifacts
need answered: where the behaviour lives today, entry points, affected modules/classes, existing
tests, config/schema touched, conventions to follow. Skip any question the conversation already answers.

**Magento 2:** DI questions (plugins, preferences, observers, virtualTypes, class ownership) go to
`m2graph` inline, not to Explore — grep on di.xml gives wrong answers.

## 2. Dispatch — one `Agent(subagent_type: "Explore", model: "haiku")`, all questions in one brief

```
Recon for an OpenSpec change: <one-line request>.
Answer each question with file:line references. Scope: <dirs worth searching; exclude vendor/,
generated/, node_modules/ unless a question needs them>.
Questions:
1. …
Return ≤40 lines: per question — answer, file:line refs, confidence. Then "Searched:" (dirs/patterns
actually covered) and "Unresolved:" (what you could not establish). No code dumps beyond 3-line excerpts.
```

Independent question groups over disjoint areas may go to 2 Explore agents in parallel, one message.

## 3. Use the map

- Draft proposal/design/specs/tasks from the recon result. File paths in `tasks.md` come from it.
- `tasks.md` tasks carry `[P]` and `**Exec:**` per `planning-conventions.md` (agent name, `lead` for inline; `Review:` per phase when consequential). `opsx-apply` reads them.
- Targeted `Read` inline where a design decision hinges on exact code (a signature, an invariant).
  Another broad sweep → one follow-up Explore with the specific open question.
- Carry "Unresolved" items into design.md Open Questions instead of guessing.
