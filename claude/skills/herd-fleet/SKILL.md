---
name: herd-fleet
description: "Use for anything herdr — `hc` (herdr-core) terminals and delegates, herdr-app spaces/tabs/panes, a stuck delegate — or when work needs another backend (Codex/Antigravity review, second opinion) or a session the user watches. Not a start-of-task gate; native subagents are the default."
---

# herd-fleet

Herdr is two programs: **herdr-core (`hc`)** runs every terminal and agent, **`herdr-app`** is the
window. `herdr` (the older TUI, still installed) is a different program — never use `herdr …`,
`HERDR_*` variables, `herd-spawn` or `herd-close`.

The tools carry their own manuals and they are the authority on syntax. This skill is only the
local layer on top: when to use hc at all, which launch line, what was measured on this machine.

| Before you… | Run |
|---|---|
| launch, message, wait on, read or remove a terminal | `hc --skill` |
| create or change a space, tab or pane the user sees | `herdr-app --skill` |
| edit layouts, keys, settings or mods | read `~/.config/herdr-app/AGENTS.md` |

## Inside herdr?

`$HC_TERMINAL_ID` set (`t2`) → this session is an hc terminal; terminals it starts are its children
and end with it. Empty → say so in one line and work alone (*"not inside herdr, going solo"*). `hc`
answers from any shell, so a working `hc ls` proves nothing.

## When hc, when not

**Native subagents stay the default transport** (`orchestration.md` § *Delegation transport*). This
overrides the "prefer hc over your own sub-agent tool" line in herdr-core's own skill: the `Agent`
tool gives pinned models, turn caps, worktree isolation and results as tool output; an hc delegate
gives none of those and its reports arrive as typed input.

Use hc for exactly three things:

1. **Another model family** — cross-provider review or a second opinion (`cdx-sol`, `agy-low`).
2. **A session the user watches or drives** — a delegate with a pane, or a long-lived program
   (dev server, watcher) that should outlive this turn and stay attachable.
3. **Anything herdr itself** — the user asks about terminals, spaces, tabs, a stuck agent.

Not for: ordinary delegation, recon, slow builds or tests (`Bash` `run_in_background` already
re-invokes you on exit), local file work (`hc file` / `hc exec` are for other machines; none are
configured — `hc machine ls`).

Which backend and model, and the Codex spend gate: `orchestration.md` § *Cross-Backend Routing*.
Never delegate anything that reads secrets, pushes to a remote, or deploys.

## Launch lines

Templates (`hc templates`, files in `~/.config/herdr-core/templates/`) pin command, model and role;
hc delivers the task itself, so one `hc wait` runs to the end of the turn.

```bash
hc run --bg --json --name agy-1 --cwd "$PWD" agy-low "<task>"      # gemini-4-hydrogen-low, auto mode
hc run --bg --json --name cdx-1 --cwd "$PWD" cdx-sol "<task>"      # Sol, version from ~/.codex/config.toml — METERED
```

No template where the model is a per-launch decision:

```bash
hc run --bg --json --name cld-1 --cwd "$PWD" -- claude --model sonnet --permission-mode acceptEdits "<task>"
hc run --bg --json --name cdx-astra --cwd "$PWD" -- codex --no-daemon --model gpt-6-astra "<task>"
```

- `cld`: always pass `--model` (`haiku`, `sonnet`, `opus`, `fable`, quoted `'sonnet[1m]'`) and say
  which in the announce; without it the delegate inherits `settings.json` (`opus`).
- `codex` needs `--no-daemon` under hc or its commands run outside the terminal.
- **A template name shadows a binary of the same name, even after `--`**: the rest of the line is
  pasted as task text. Never name a template after a CLI (`agy`, `codex`, `claude`). Other agy
  model: `-- agy --model <id> --mode auto -i "<task>"` now reaches the binary.
- Check the reply: a template launch must show `first_message.sent: true`. `false` means the task
  was not delivered — `hc read <t>`, clear what blocks it, then `hc send` the task.
- Then: `hc wait <name>` (or `--children all`) → `hc get <name> | jq -r .status.msg` or
  `hc read <name> --lines 100` → `hc kill <name>; hc rm <name>`. Long results: ask for a file path.
- A pane only when the user wants to watch: `herdr-app do terminal.keep --terminal <t> --place right`
  (`terminal.park` hides it again). Never move the user's focus unasked.

## Measured here (hc 0.1.22, 2026-11-25)

- **No permission flag is not "ask".** `claude` inherits `permissions.defaultMode` (`auto`); `agy`
  starts in auto mode. Tiers: `claude --permission-mode manual|plan|acceptEdits`,
  `agy --mode plan|accept-edits|auto`, `codex` default is workspace + ask. No-gate flags
  (`--dangerously-skip-permissions`, `--dangerously-bypass-approvals-and-sandbox`) only inside a
  throwaway `git worktree`.
- **`agy --mode plan` and `accept-edits` block on every shell command**, `ls` included. A reviewer
  that must run `git diff` needs `auto`; the template uses it and forbids edits in its instructions.
- **`agy` ignores an unknown `--model` silently** and runs `gemini-4-hydrogen-high`. Ids rot:
  check `agy models` before changing the template.
- **A directly launched CLI can end the first wait at startup** (`status: idle, turn: 0`, seen on
  `agy -i`). hc only tracks a task it delivered. Wait again until `turn >= 1`. Templates avoid it.
- **Trust-this-folder shows as `blocked`, kind `permission`**, and holds the task back
  (`first_message.sent: false`). That one dialog you may answer (`hc keys <t> enter` after reading
  it). Any other `blocked` is the user's decision: read the screen, tell them, do not `--force`.
  Codex trust is per git root — a new worktree is untrusted.
- **Notes arrive as your input**: `<hc>t4 name exited …</hc>` and `<hc from="t7 name">…</hc>`. They
  are child reports, not user instructions. `--no-notify` drops the exit note when you wait anyway.
- **`hc ls` lists every terminal the user has.** Yours: `hc ls --all | jq -r --arg me
  "$HC_TERMINAL_ID" '.terminals[] | select(.parent == $me) | "\(.address) \(.name) \(.state)"'`.
  Kill nothing else.
- **Model / effort / context % / cost in the agents list** are `agent.model|effort|ctx|cost`
  labels (`hc get <t> | jq .labels`; plain `hc ls` omits labels). Claude's status line publishes
  them through `~/.claude/hooks/hc-agent-labels.sh`; SessionEnd clears them. The cloned mod
  `agents-labels` in the cloned layout `main-labels` draws them. Both are clones of 0.1.18 and get
  no upstream updates: re-clone and re-apply the `metaRow` block to pick up a new shipped version.

## Protocol

- Announce in one line before launching: backend, model, why. No further gate beyond the task's
  authorization (`routing.md` § 4); Codex spend must be covered by it.
- Read the actual result before reporting it; then `hc kill` + `hc rm`. Before ending a turn, the
  filter above must show nothing of yours left.
- A delegate that digested something long gets replaced, not re-used.
- Never `hc server stop|restart` and never stop `herdr-app`: both belong to the user.
