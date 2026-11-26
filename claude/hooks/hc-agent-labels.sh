#!/usr/bin/env bash
# Publish this Claude session's model, effort, context % and cost as herdr-core
# terminal labels (agent.model / agent.effort / agent.ctx / agent.cost). The
# herdr-app `agents-labels` mod shows them under each agent.
#
#   <statusline JSON on stdin>   publish; hc is only called when a value changed
#   clear                        SessionEnd: drop them, so the next program in
#                                this terminal does not show a stale model
#
# Outside an hc terminal this does nothing.

set -u

[ -n "${HC_TERMINAL_ID:-}" ] && command -v hc >/dev/null 2>&1 || exit 0
state="${XDG_RUNTIME_DIR:-/tmp}/hc-agent-labels-${HC_TERMINAL_ID//\//_}"

if [ "${1:-}" = clear ]; then
    hc label "$HC_TERMINAL_ID" agent.model= agent.effort= agent.ctx= agent.cost= >/dev/null 2>&1
    rm -f "$state"
    exit 0
fi

# One key=value per line; an empty value removes that label.
labels=$(jq -r '
    "agent.model=" + ((.model.display_name // .model.id // "")
        + (if (.context_window.context_window_size // 0) >= 1000000 then "[1m]" else "" end)),
    "agent.effort=" + (.effort.level // ""),
    "agent.ctx=" + (if .context_window.used_percentage != null
        then "\(.context_window.used_percentage | floor)%" else "" end),
    "agent.cost=" + (if .cost.total_cost_usd != null
        then "$\(.cost.total_cost_usd * 100 | round / 100)" else "" end)
' 2>/dev/null) || exit 0

[ -n "$labels" ] && [ "$labels" != "$(cat "$state" 2>/dev/null)" ] || exit 0
mapfile -t args <<<"$labels"
hc label "$HC_TERMINAL_ID" "${args[@]}" >/dev/null 2>&1 && printf '%s' "$labels" >"$state"
exit 0
