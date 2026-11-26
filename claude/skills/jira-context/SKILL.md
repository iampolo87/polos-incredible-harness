---
name: jira-context
description: Use when picking up a Jira ticket, triaging a new bug, or asking whether an issue happened before in this project. Triggers - "any prior history?", "did this happen before?", "jira context", "contexto del ticket", "¿esto pasó antes?", "historial de este bug", "buscá en Jira/Confluence", or a ticket key like PROJ-123 handed over at the start of work. Requires the global `atlassian` MCP server (OAuth via /mcp).
---

# Jira/Confluence Project Context (live query)

## Overview

Answers "did this happen before, how was it fixed, is there a doc?" by querying Jira and Confluence live. Read-only, no index, no cache — fresh every run. Complements claude-mem (code-side history) with ticket-side history.

## Arguments

One of:
- Ticket key (`PROJ-123`)
- Quoted free-text bug/task description
- Nothing → ask which ticket/bug before doing anything else

## Step 1 — Load tools + auth precheck

Atlassian MCP tools are deferred and their exact names depend on server registration (user-scope server `atlassian` → `mcp__atlassian__*`). **Never assume the `mcp__claude_ai_Atlassian__*` prefix.** Load in ONE ToolSearch call by keyword — `"+atlassian jira confluence search"`, `max_results: 10` — and use the names it returns.

Call the accessible-resources tool (`getAccessibleAtlassianResources`) first; cache the cloudId for the whole run. On auth error: tell the user to run `/mcp`, complete the Atlassian OAuth, and re-run. Stop there.

## Step 2 — Project config

Read `.atl/atlassian.yml`, walking up from cwd (same sidecar convention as `jira-estimate`):

```yaml
jira_project_key: PROJ
confluence_space_keys: [DOCS]   # optional; omit to search all spaces
```

Missing file → ask the user for the project key first. Only if they don't know it, call `getVisibleJiraProjects` **with `searchString` (derived from the repo/client name) and `maxResults: 10`** — never unbounded: the bare call returns 50+ projects and ~70k characters on this instance. Then offer to write `.atl/atlassian.yml` so the next run asks nothing.

## Step 3 — Subject

- **Ticket mode:** `getJiraIssue` with `responseContentFormat: "markdown"` and explicit fields (summary, description, components, labels, issuetype, status, issuelinks). Extract 3–6 search keywords from summary/description/components.
- **Free-text mode:** extract keywords directly from the description.

## Step 4 — Jira history search

- JQL 1: `project = <KEY> AND text ~ "<keywords>" ORDER BY resolutiondate DESC` — `maxResults: 10`, explicit `fields` list.
- JQL 2 (ticket mode only): the issues referenced in `issuelinks`.
- For the top 3–5 hits: fetch resolution + latest comments, bounded. Resolved/Done issues rank first — they carry the "how it was fixed".

## Step 5 — Confluence search

CQL `siteSearch ~ "<keywords>"`, scoped with `space in (...)` when `confluence_space_keys` is configured, `limit: 5`. Keep titles + excerpt + URL only. Fetch a full page body only when the title clearly matches the subject.

The site may have no Confluence product at all — the search then returns `404 Not Found` on `/ex/confluence/...` (verified on your-site.atlassian.net). Not an error in your call: skip the step, state "no Confluence on this site" in Gaps, and continue.

## Step 5b — Widen once (sources the ticket does not name)

Before the verdict, one bounded pass over context the subject does not reference: parent/epic of the ticket, issues in the same component resolved in the last 6 months (`maxResults: 10`, explicit fields), and a claude-mem search on the keywords. Anything relevant joins Prior history; anything skipped goes in Gaps.

## Step 6 — Report (fixed shape)

Inline in the conversation, terse, in the conversation's language:

1. **Verdict** — first line: `Seen before: yes | partial | no` + one sentence.
2. **Prior history** — per hit: key, one line what happened, how it was resolved, link.
3. **Docs** — title, link, why relevant.
4. **Gaps** — what was NOT covered: truncated searches, unconfigured spaces, keyword blind spots. Never end without this section.

## Token discipline (mandatory)

- Every Jira/Confluence call bounded: `maxResults`/`limit` + explicit field lists (JQL/CQL analogue of the NRQL `LIMIT N` rule — see the Atlassian rows in `~/.claude/rulesets/core/orchestration.md`).
- A fetch expected to return >50 raw lines (long comment thread, full Confluence page) → Haiku subagent with the orchestration matrix template: "Call `<tool>` with `<params>`. Return ONLY: `<fields>`. Hard cap 30 lines."
- Read-only skill: never `addComment`, `create*`, `edit*`, `transition*`.

## Common mistakes

| Mistake | Fix |
|---|---|
| Hardcoding `mcp__claude_ai_Atlassian__*` tool names | ToolSearch by keyword; use returned names |
| Unbounded JQL / no fields list | Always `maxResults` + explicit `fields` |
| Dumping full issue/page payloads into context | Bounded fields; Haiku subagent for big fetches |
| Reporting "0 results" as "never happened" | Keyword search misses rephrasings — state it in Gaps |
| Falling back to WebFetch/WebSearch on the Jira URL | Auth-walled, always fails — MCP is the only route |
