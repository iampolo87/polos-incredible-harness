#!/usr/bin/env bash
# Version-agnostic wrapper for the caveman plugin's status line.
#
# settings.json used to hardcode the plugin's commit-pinned cache path, so the
# next caveman update silently killed the status line. Resolve it at run time
# instead: pick the newest install under the caveman cache and run it.
#
# Side job: inside a herdr-core terminal, publish model, effort, context % and
# cost as terminal labels for the herdr-app agents list (hc-agent-labels.sh).

set -u

payload=$(cat)

printf '%s' "$payload" | bash ${HOME}/.claude/hooks/hc-agent-labels.sh

cache="${HOME}/.claude/plugins/cache/caveman/caveman"
target=""

if [ -d "$cache" ]; then
    # Newest install wins if several versions are present.
    for d in $(ls -1t "$cache" 2>/dev/null); do
        candidate="$cache/$d/src/hooks/caveman-statusline.sh"
        if [ -r "$candidate" ]; then
            target="$candidate"
            break
        fi
    done
fi

# No caveman installed, or its layout changed: print nothing rather than an
# error. A broken status line must never look like a broken session.
[ -n "$target" ] || exit 0

printf '%s' "$payload" | exec bash "$target"
