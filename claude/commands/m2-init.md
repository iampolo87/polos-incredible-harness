---
description: Bootstrap a Magento 2 project's .claude/ directory — symlink magento-agents, drop CLAUDE.md + settings skeleton. Idempotent.
argument-hint: [--force]
allowed-tools: [Read, Write, Edit, Bash, Glob]
---

# `/m2-init` — Magento 2 project bootstrap

Bootstrap `<cwd>/.claude/` for a Magento 2 project. Idempotent — safe to re-run.

## Behavior

### 1. Detect M2 project

Verify cwd looks like a Magento 2 root. Pass if ANY of:
- `bin/magento` exists
- `app/etc/` exists
- `composer.json` contains a require entry matching `magento/product-` or `magento/framework`

If none match AND `--force` not in `$ARGUMENTS`: abort with message `"<cwd> does not look like a Magento 2 project. Re-run with --force if you know better."`.

### 2. Ensure `.claude/` directory

```bash
[ -d ./.claude ] || mkdir ./.claude
```

### 3. Ensure `.claude/agents` symlink

```bash
TARGET=${HOME}/projects/magento-agents
LINK=./.claude/agents

if [ ! -e "$LINK" ] && [ ! -L "$LINK" ]; then
  ln -s "$TARGET" "$LINK" || {
    # Symlink failed (Windows native / sandbox / non-POSIX). Fall back to copy.
    cp -r "$TARGET" "$LINK"
    echo "WARN: agents copied not symlinked — upstream changes won't sync. Re-run /m2-init after upstream changes."
  }
elif [ -L "$LINK" ]; then
  CUR=$(readlink "$LINK")
  if [ "$CUR" != "$TARGET" ]; then
    echo "SKIP: $LINK already symlinked to $CUR (not canonical target $TARGET). Inspect manually."
  else
    echo "OK: $LINK already canonical."
  fi
elif [ -d "$LINK" ]; then
  echo "SKIP: $LINK exists as a real directory (not a symlink). Inspect manually before clobbering."
fi
```

### 4. Ensure project `.claude/CLAUDE.md`

If `./.claude/CLAUDE.md` is missing:

```bash
cp ${HOME}/projects/magento-agents/_shared/PROJECT-CLAUDE.template.md ./.claude/CLAUDE.md
```

Print: `"Created .claude/CLAUDE.md from template. Edit placeholders: PROJECT_NAME, PHP_VERSION, PROD_APP_NAME, STG_APP_NAME, NR_ACCOUNT_ID."`

If present, skip with `"OK: .claude/CLAUDE.md already exists."`.

### 5. Ensure `.claude/settings.local.json`

If missing:

```json
{
  "permissions": {
    "allow": [],
    "deny": []
  }
}
```

If present, skip.

### 6. Summary report

Print a 3–5 line summary:

```
m2-init summary for <cwd>:
  agents : created | already-symlinked | copied-fallback | skipped (<reason>)
  CLAUDE : created from template | already-present
  settings: created skeleton | already-present
  m2 detection: <which marker matched>
Next: edit .claude/CLAUDE.md placeholders.
```

## Args

- `--force` — skip M2 detection (use only for non-standard layouts).

## Rollback

Per-project: `rm -rf .claude/agents` (and the CLAUDE.md / settings.local.json if just created). Command itself: delete this file.

## Notes

- This command writes ONLY inside `<cwd>/.claude/`. Never operates outside cwd.
- Symlink target `${HOME}/projects/magento-agents` is version-controlled (git). Run `git -C ${HOME}/projects/magento-agents pull` periodically (or after upstream changes if working in copy-fallback mode).
- See `~/.claude/rulesets/core/orchestration.md` "M2 Subagent Routing" section for which subagent to dispatch per task class once bootstrap is done.
- See `${HOME}/projects/magento-agents/AGENTS-INDEX.md` for the canonical active-agent lookup (3 active; archived personas are not registered).
