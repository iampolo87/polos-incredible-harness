---
description: Review current changes for over-engineering — what can be deleted
argument-hint: "[optional path or PR ref]"
---

Review the current code changes $ARGUMENTS for over-engineering ONLY, not correctness. Get the diff yourself (git diff of staged + unstaged, or the named target). One line per finding:

`L<line>: <tag> <what to cut>. <replacement>.`

Tags: `delete` (dead code/speculative feature), `stdlib` (reinvented standard library), `native` (dependency doing what the platform does), `yagni` (abstraction with one implementation), `shrink` (same logic, fewer lines).

End with the net lines removable. If nothing to cut: "Lean already. Ship."
