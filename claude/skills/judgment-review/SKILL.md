---
name: judgment-review
description: "Trigger: judgment review, dual review, adversarial review, juzgar. Run blind dual-judge code review (Sonnet + Opus), optionally a cross-family third judge (Codex Sol) on high-risk targets, fix confirmed issues, then single-judge scoped re-judge. `--single sonnet|opus` runs one judge for plan-execution checkpoints. Use before merge for high-stakes changes."
license: Apache-2.0
metadata:
  author: polo
  inspired-by: gentleman-programming/gentle-ai judgment-day v1.4
  version: "0.4"
---

# Judgment Review

Parallel adversarial code review with model-class diversity. Two blind judges evaluate the same target. Only consensus findings drive auto-fixes. Fixes are surgical and re-verified before terminal state.

## Activation Contract

Load this skill ONLY when the user explicitly asks for "judgment review", "dual review", "adversarial review", "juzgar", or "que lo juzguen". Do NOT auto-invoke from generic review requests — use the `reviewer` agent for an ordinary independent review when one is warranted.

Require an explicit target:
- Specific files (paths)
- Feature or component scope
- Pull request (BASE_SHA..HEAD_SHA range)
- Architecture slice

If target is ambiguous, ask before launching judges. Do not guess.

## Single-judge mode — `--single sonnet|opus`

Cheaper Round 1 for the batching rule in `~/.claude/rulesets/core/orchestration.md` (`### Judgment-Review Cost Gate`, *Batch, never per-task*). Not a default — the caller passes it explicitly:

| Use | Flag |
|---|---|
| Mid-plan checkpoint over accumulated tasks | `--single sonnet` |
| Foundational task (schema / interface / base class) or security-sensitive task, judged alone | `--single opus` |
| Final pre-merge pass | no flag → dual judge |

What changes versus dual mode:
- **Round 1 = one Task call** (`judgment-judge-sonnet` or `judgment-judge-opus`). Self-check line: `Dispatch check: single-judge mode (<model>), one Task call.`
- **No consensus exists**, so the single judge's `CRITICAL` / `WARNING (real)` rows go straight to **Confirmed**. Suspect and Contradiction buckets are unused. The reduced confidence is recorded in the footer: `Mode: single (<model>)`.
- **Multi-commit range → per-commit patches.** In Step 4 use `git log --patch --reverse $BASE_SHA..$HEAD_SHA` instead of a flattened diff, so task boundaries stay visible. Judges tag each finding with the short sha of the commit that introduced it (`File:Line` column becomes `sha File:Line`).
- **≤300 changed lines per judge dispatch.** If `--stat` reports more and the range has >1 commit, split the range at commit boundaries into ≤300-line chunks and launch one judge per chunk in the same message (same model, identical prompt shape, disjoint `{DIFF_BODY}`). Merge the tables before the verdict. Same tokens as one big judge, better per-line attention.
- Everything from the fix gate onward is unchanged: user approval, `judgment-fixer`, scoped sonnet re-judge, iteration cap, stagnation guard.

## Hard Rules

- **Never inline `CLAUDE.md` into agent prompts.** The harness already auto-injects `~/.claude/CLAUDE.md` and `<cwd>/.claude/CLAUDE.md` into every custom subagent (only `Explore` and `Plan` skip it). Re-injecting it as a `Project Standards` block is a pure duplicate — historically ~4k tokens × 3 agents × up to 3 rounds. Instead resolve the **severity scale only**: read `~/.claude/rulesets/core/code-review.md` and inline that as `{SEVERITY_SCALE}`. If the project declares a framework in `<cwd>/.claude/CLAUDE.md`, append the *path* of the matching ruleset (e.g. `~/.claude/rulesets/frameworks/magento2.md`) — a path, not its contents; judges have Read access. Still record what was resolved for the `Skill Resolution:` output footer.
- **Parallel dispatch (rule #1, Round 1, dual mode)**: launch **two blind judges in parallel** with identical target and criteria via a single message containing two Task tool calls. Never review the code yourself. Before the launch message, write a one-line self-check in your text response: `Dispatch check: one message, two Task calls (sonnet + opus), identical prompts.` Skipping this check is the recurring failure mode — the check is the prevention.
- **Dispatch self-check (rounds 2+)**: scoped re-judge is a single Task call, so the Round-1 self-check line would be a lie. Write instead: `Dispatch check: scoped re-judge, single sonnet judge.` The check is never omitted, only swapped for the round type.
- **Sequential-dispatch recovery (soft)**: if Judge A was launched alone by mistake, do NOT discard the round. Launch Judge B in the very next turn with the original prompt verbatim. **Critical: the Opus prompt MUST NOT contain Sonnet's findings, output, or any reference to it** — blindness is preserved by prompt independence, not by timing. Record `Dispatch: sequential (blindness preserved)` in the output footer.
- Use `judgment-judge-sonnet` for Judge A and `judgment-judge-opus` for Judge B. Different model classes → real diversity. Reasoning budget is set per-agent via the `effort` frontmatter key in each agent file (`low` for sonnet judge and fixer, `medium` for opus judge) — since Claude Code v2.1.198 subagents inherit the session effort level unless they declare their own, and this session runs at `xhigh`. Do not remove those keys; they are the main cost control.
- **Dual judges apply to Round 1 only, and only without `--single`.** Round 1 is discovery, where model-class diversity pays. Scoped re-judge rounds (2+) only verify whether already-consensus-confirmed fixes landed — that is mechanical, so they dispatch `judgment-judge-sonnet` alone.
- Wait for **both** judges before synthesis in Round 1. Never accept a partial verdict.
- Classify warnings as `WARNING (real)` only if normal intended use can trigger them. Otherwise downgrade to `WARNING (theoretical)` and bucket as INFO.
- Ask the user before fixing Round 1 confirmed issues. Show the verdict table first.
- After any fix-agent run that touched files, immediately re-launch the scoped re-judge (single sonnet judge) **scoped to those files** before declaring any terminal state, commit, push, or session summary. If the fixer touched zero files, terminal state may be declared without a second round.
- Judges output the **table-only contract** defined in `judge-prompt.md`. No prose reasoning paragraphs.
- Terminal states are only `JUDGMENT: APPROVED ✅` or `JUDGMENT: ESCALATED ⚠️`.
- **Hard iteration cap**: at most **3 total judgment rounds** (Round 1 + up to 2 fix-rejudge rounds). After Round 3, auto-ESCALATE with reason `iteration cap`. Never ask the user "should I continue?" — the cap is non-negotiable, especially in auto / non-interactive mode where forever-loops are otherwise possible.
- **Stagnation guard**: if the same finding (matched by `severity + file:line + first-60-chars-of-description`, normalized) is confirmed in two consecutive rounds, auto-ESCALATE that finding and **do not re-fix it**. Continue to terminal state immediately if no other confirmed findings remain; otherwise apply remaining fixes once and terminate next round.

## Decision Gates

| Condition | Action |
|---|---|
| Target unclear | Ask for scope; do not launch judges. |
| `~/.claude/rulesets/core/code-review.md` missing | Warn, proceed with generic criteria, record `Skill Resolution: none`. |
| **Round 1**: **any 2 judges** find the same CRITICAL or `WARNING (real)` | Confirmed → ask/fix per round rules. (With no Judge C this is the usual both-of-two.) |
| **Round 1**: one judge only finds an issue | Suspect → report, triage, do not auto-fix. |
| Judges contradict on an issue (one flags, another explicitly clears) | Escalate for manual decision — or, if the contradiction blocks a high-risk merge, resolve it with one `gpt-6-astra` dispatch (see *Optional third judge*). |
| Round 2+ has only theoretical warnings or suggestions | Report as INFO; do not re-judge. |
| **Scoped round**: single judge marks a checklist item `STILL PRESENT` | **Confirmed** without a second vote — the finding already cleared dual-judge consensus in Round N−1. Re-verification does not re-litigate it. |
| **Scoped round**: single judge marks a checklist item `RESOLVED` | Finding closed. |
| **Scoped round**: single judge raises a *new* CRITICAL / `WARNING (real)` inside touched files | **Suspect** — report it, never auto-fix. New findings need dual-judge consensus, which a scoped round does not provide. |

## Optional third judge — Codex Sol (cross-family)

Sonnet and Opus share a training family, so they share blind spots. Codex Sol (`cdx-sol`) on the Codex backend is
the cheapest uncorrelated third vote available. It is **opt-in, Round 1 only, and off by default** — the
Codex plan is metered.

**Add Judge C when** the target touches security-sensitive paths, is a pre-merge to `main`, or the user
asks for it. Skip it otherwise; two judges remain the default contract.

**It is not a Task subagent.** Codex runs as an hc (herdr-core) terminal, so dispatch differs from
Judges A and B:

```bash
# cdx-sol is an hc template (codex --no-daemon; model from ~/.codex/config.toml); the filled judge-prompt.md is its task
hc run --bg --json --no-notify --name jc-sol --cwd "$PWD" cdx-sol "$(cat "$filled_prompt_file")"
#   -> the reply must show first_message.sent: true; if false, hc read jc-sol (trust prompt?) and hc send the task
hc wait jc-sol --timeout 600        # repeat while reason is timeout or status is working
hc read jc-sol --lines 200          # plain text; first real Judge C run under hc still to confirm
hc kill jc-sol; hc rm jc-sol
```

One argument is capped at 128 KiB on Linux: for a larger filled prompt, launch with a one-line task
that tells the judge to read the prompt file instead. The template prepends three lines of role
constraints (read-only, no agents, follow the task's format) to the prompt.

Consequences of it being outside the harness:

- **It inherits nothing** — no `CLAUDE.md`, no rulesets, no MCP. `{SEVERITY_SCALE}` must be inlined as
  usual, **and** `{FRAMEWORK_RULESET_PATH}` must be inlined *as contents*, not as a path: Judge C cannot
  read a path it was never told about and has no project context to resolve it. This is the one place the
  no-inlining Hard Rule does not apply, because its premise (harness auto-injection) is false here.
- No sandbox or approval flags, ever. A judge never needs to write.
- Blindness is preserved the same way: its prompt must not contain Judge A's or B's findings.
- If not inside herdr (`HC_TERMINAL_ID` unset), say so in one line and run the standard two-judge round. Never
  silently drop to two judges without saying it.
- **Codex unavailable for any reason — quota exhausted, not logged in, spawn fails — degrades to the
  two-judge Claude contract.** Say so in one line and proceed; it is not a blocker and there is no
  escalation path to wait on. Same for the astra tiebreak: with no Codex, a Contradiction stays
  `ESCALATED` for manual decision, exactly as it did before Judge C existed. Never stall a review, and
  never substitute a third Claude judge — that would be same-family, which is the whole thing Judge C
  exists to avoid.

**Consensus with three judges: any 2 of 3 agreeing at CRITICAL or `WARNING (real)` is Confirmed.** A
finding only Judge C raises is Suspect, exactly like a solo Sonnet or Opus finding — cross-family does not
mean authoritative.

**Astra as tiebreak.** On a Contradiction that blocks a high-risk merge, one `gpt-6-astra` dispatch may
resolve it — spawn `cdx --model gpt-6-astra`, give it the contradicted finding plus the relevant hunks,
and take its verdict as the deciding vote. Budget it: astra runs ~2–4 dispatches/week across all uses.
Never use astra as Judge C — that is Sol's seat at 2.5x less cost.

Scoped re-judge rounds (2+) stay single-Sonnet. Never dispatch Codex there.

## Execution Steps

1. **Confirm target and optional custom criteria.** Capture as `{TARGET}` and `{CUSTOM_CRITERIA}`.
2. **Resolve severity scale.** Read `~/.claude/rulesets/core/code-review.md` → `{SEVERITY_SCALE}`. If `./.claude/CLAUDE.md` declares a framework, capture the matching ruleset **path** (not its contents) → `{FRAMEWORK_RULESET_PATH}`. Do **not** read or inline either `CLAUDE.md` — the harness injects those into subagents already. Note resolution source for the output footer.
3. **Compute git range** (if PR/diff target): `BASE_SHA=$(git rev-parse HEAD~1)` (or `origin/main`), `HEAD_SHA=$(git rev-parse HEAD)`.
4. **Pre-bundle diff (orchestrator-side, run once).**
   - `git diff --stat $BASE_SHA..$HEAD_SHA` → capture as `{DIFF_STAT}`.
   - `git diff $BASE_SHA..$HEAD_SHA` → capture as `{DIFF_BODY}`. (`--single` on a multi-commit range: `git log --patch --reverse $BASE_SHA..$HEAD_SHA` instead, and apply the ≤300-line chunking from *Single-judge mode*.)
   - **Size guard**: if `{DIFF_BODY}` exceeds **~1200 lines** (≈15k tokens, and it is inlined into every judge prompt), set `{DIFF_BODY}` = `"(omitted: >1200 lines — read files directly)"` and keep `{DIFF_STAT}` plus the changed-file path list only. Judges retain Read access and pull the hunks they need. The old 5000-line threshold inlined ~60k tokens into each judge.
5. **Round 1 only — launch Judge A and Judge B in parallel** (`--single`: one judge, see *Single-judge mode*; skip the two-call self-check and use the single-mode line) — one message, two Task tool calls. Both prompts filled from `judge-prompt.md` with `REVIEW_MODE: full`, `{SEVERITY_SCALE}`, `{DIFF_STAT}`, `{DIFF_BODY}`, empty `{RESOLUTION_CHECKLIST}`.
   - **Before the launch message, write this exact self-check line in text:** `Dispatch check: one message, two Task calls (sonnet + opus), identical prompts.` If you cannot write it truthfully, you are about to dispatch sequentially — fix the message before sending.
   - Task 1: `subagent_type: judgment-judge-sonnet`
   - Task 2: `subagent_type: judgment-judge-opus`
   - **Judge C (optional, high-risk targets only)**: if the *Optional third judge* criteria apply, dispatch
     Codex Sol (`cdx-sol`) on the `cdx` herdr backend in the same round, prompt filled identically except that
     `{FRAMEWORK_RULESET_PATH}` is inlined as contents. It is an hc terminal, not a Task call, so the
     self-check line stays as written; append `+ codex sol (hc)` to it when Judge C is in play.
6. **Synthesize (Round 1, dual judge)** findings into four buckets (`--single`: CRITICAL / `WARNING (real)` → Confirmed, rest → INFO):
   - **Confirmed** — **any two judges** flagged the same issue at CRITICAL or `WARNING (real)`
   - **Suspect** — one judge only (including a solo Judge C finding)
   - **Contradiction** — one flags, the other explicitly clears
   - **INFO** — `WARNING (theoretical)` or SUGGESTION from either judge
7. **Render verdict table** (see Output Contract). Show user before any mutation.
8. **Round 1 fix gate**: ask user "Apply confirmed fixes? [y/N/select-subset]". Only proceed on explicit approval.
9. **Dispatch fix agent**: Task tool with `subagent_type: judgment-fixer`, prompt = filled `fix-prompt.md`. Pass only confirmed findings.
10. **Parse fixer output.** Extract `TOUCHED_FILES:` line into `{TOUCHED_FILES}`.
    - **Skip-re-judge guard**: if `{TOUCHED_FILES}` is empty (user approved zero confirmed fixes, or fixer reported nothing applicable) → skip Step 11. Declare APPROVED if Round 1 had no confirmed remaining; otherwise declare ESCALATED with reason `no fixes applied`.
11. **Scoped re-judge — single judge.**
    - `PRE_FIX_SHA = HEAD_SHA` (from previous round); `POST_FIX_SHA = $(git rev-parse HEAD)` if fixer committed, else use working-tree diff.
    - `git diff --stat $PRE_FIX_SHA..$POST_FIX_SHA -- {TOUCHED_FILES}` → `{DIFF_STAT}`.
    - `git diff $PRE_FIX_SHA..$POST_FIX_SHA -- {TOUCHED_FILES}` (or `git diff -- {TOUCHED_FILES}` for unstaged) → `{DIFF_BODY}` (apply same size guard).
    - Build `{RESOLUTION_CHECKLIST}` listing each Round-N-1 confirmed finding (severity + file:line + one-line desc).
    - Override `{TARGET}` = `Scoped re-judge of touched files: {TOUCHED_FILES}`.
    - **Write this exact self-check line in text before dispatching:** `Dispatch check: scoped re-judge, single sonnet judge.`
    - Launch **one** Task call: `subagent_type: judgment-judge-sonnet`, `REVIEW_MODE: scoped`. Do **not** dispatch the opus judge — the findings under verification already cleared dual-judge consensus, so model diversity buys nothing here.
    - Synthesize per the scoped-round rows in Decision Gates: `STILL PRESENT` → Confirmed; `RESOLVED` → closed; any new finding → Suspect, never auto-fixed.
    - Update `HEAD_SHA = POST_FIX_SHA` for any subsequent round.
12. **Repeat** Steps 7–11 until any of (synthesis for rounds 2+ is Step 11's own rule, not Step 6):
    - Zero confirmed remain → `APPROVED`.
    - **Round 3 reached** (Round 1 + 2 fix-rejudge rounds) and confirmed findings still remain → `ESCALATED` with reason `iteration cap`. **Do not ask the user to continue.**
    - **Stagnation detected** (same finding confirmed in two consecutive rounds, matched by `severity + file:line + first-60-chars-of-description`) → mark that finding `ESCALATED (stagnant)`. If no other confirmed findings remain, terminate immediately; otherwise dispatch one more fix round for the remaining ones, then terminate regardless of outcome.
    - Contradiction blocks progress → `ESCALATED` with reason `contradiction`.
13. **Before any terminal action** (commit, push, session summary): verify every active Judgment Review reached `APPROVED` or `ESCALATED`.

## Output Contract

```
## Judgment Review — {TARGET}

**Round:** {N}
**Range:** {BASE_SHA}..{HEAD_SHA}
**Re-judge mode:** full | scoped ({K} files)

Round 1 (dual judge; in `--single` mode drop the absent judge column and the Status values are Confirmed / INFO only):

| Finding | Judge A (sonnet) | Judge B (opus) | Judge C (sol)¹ | Severity | Status |
|---------|------------------|----------------|----------------|----------|--------|
| ...     | ✅ / ❌           | ✅ / ❌         | ✅ / ❌ / —     | CRITICAL / WARNING (real) / WARNING (theoretical) / SUGGESTION | Confirmed / Suspect / Contradiction / INFO |

¹ Judge C column present only when the cross-family third judge ran; drop it otherwise.

Rounds 2+ (scoped, single judge):

| Finding | Judge (sonnet) | Severity | Status |
|---------|----------------|----------|--------|
| ...     | RESOLVED / STILL PRESENT / new | CRITICAL / WARNING (real) / WARNING (theoretical) / SUGGESTION | Closed / Confirmed / Suspect / INFO |

**Confirmed:** {n} | **Suspect:** {n} | **Contradiction:** {n} | **INFO:** {n}

**Fixes applied (Round {N-1}):** {summary or "none"}
**Touched files (Round {N-1}):** {comma list or "—"}
**Re-judgment result:** {clean / N confirmed remaining / contradiction}

**Mode:** dual | single (sonnet|opus)
**Skill Resolution:** claude-md-global[+project] — {paths read}

JUDGMENT: APPROVED ✅
```

Or:

```
JUDGMENT: ESCALATED ⚠️
**Reason:** {iteration cap | stagnation: <finding ref> | contradiction: <details> | user requested escalation}
```

Approved criteria: zero confirmed CRITICAL **and** zero confirmed `WARNING (real)`. Theoretical warnings and suggestions may remain.

## Cost Notes

**The dominant cost lever is `effort` in the agent frontmatter.** Claude Code v2.1.198 changed subagent behavior: before it, subagents ran with extended thinking *disabled* regardless of the main conversation's setting; after it, they inherit the session setting. With a session at `effortLevel: xhigh`, every judge and fixer silently went from zero thinking tokens to xhigh thinking tokens on identical input. `judgment-judge-sonnet` and `judgment-fixer` declare `effort: low`; `judgment-judge-opus` declares `effort: medium`. Removing those keys re-introduces the regression.

Other optimizations, in rough order of savings:
- **No CLAUDE.md re-injection**: the harness auto-injects `~/.claude/CLAUDE.md` and project `CLAUDE.md` into every custom subagent. The old `{PROJECT_STANDARDS}` block re-sent ~4k tokens into 3 agent prompts per round. Only the severity scale (`rulesets/core/code-review.md`, ~1KB) is inlined now.
- **Single-judge scoped re-judge**: rounds 2+ drop the opus judge. Verification of already-consensus-confirmed findings is mechanical.
- **Diff size guard at ~1200 lines** (was 5000): the diff is inlined into *every* judge prompt, so the old threshold could push ~60k tokens per judge. Above the guard, judges get `--stat` + file list and Read on demand.
- **Table-only output contract**: judges emit one markdown table, one-line desc + one-line fix. No prose paragraphs.
- **Diff prebundle**: orchestrator runs `git diff` once; judges skip redundant bash turns.
- **Skip-re-judge guard**: if the fixer touches zero files, no re-judge round is launched at all.

Per-round accounting:
- **Round 1**: 1× sonnet judge (`effort: low`) + 1× opus judge (`effort: medium`) in parallel, table-only, full diff prebundled.
- **Each fix round**: 1× sonnet fixer (`effort: low`) + (if any files touched) 1× sonnet scoped re-judge (`effort: low`).
- **Cap**: 2 fix iterations max. Worst case is now 1 opus + 5 sonnet (down from 3 opus + 5 sonnet).
- **Cheaper fallback**: if diversity matters less than cost, switch Judge B to `judgment-judge-sonnet` with a paranoid-security system prompt instead of the opus variant. Yields prompt-level diversity at sonnet × 2 cost.
- **Judge C (Codex Sol) is off by default** and bills against a *separate, metered* plan, not Claude quota. At $4/$20 per Mtok on a bounded read-diff/emit-findings job it is the cheapest real cross-family vote — but it is an hc terminal with hand-inlined framework rules, so it costs orchestration attention too. High-risk targets only. Astra ($10/$50) is never Judge C; it is the contradiction tiebreak, ~2–4 dispatches/week across all uses.
- **`--single` mode**: Round 1 is one judge instead of two — ~half the Round 1 cost with sonnet, and no Opus at all mid-plan. Reserved for plan-execution checkpoints and solo foundational/security tasks per the orchestration batching rule; the final pre-merge pass stays dual.
- **Before invoking at all**: honor the Judgment-Review Cost Gate — ≥3 files or ≥150 changed lines or security-sensitive paths. Below that, use the `reviewer` agent when independent review is warranted; otherwise self-review according to `routing.md`.

## References

- `judge-prompt.md` — judge prompt template (shared by A and B)
- `fix-prompt.md` — surgical fix-agent prompt template
- Inspired by gentleman-programming/gentle-ai `judgment-day` v1.4 (Apache-2.0)
