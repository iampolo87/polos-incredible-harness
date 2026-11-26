#!/usr/bin/env bash
# PreToolUse guard: block Claude from reading keyring secrets or process environments.
input="$(cat)"
text="$(jq -r '.tool_input | [.command?, .file_path?, .path?, .pattern?] | map(select(.)) | join(" ")' <<<"$input")"
re='secret-tool|keyring|libsecret|seahorse|/environ|FASTLY_API_TOKEN|FASTLY_MCP_ENCRYPT_KEY|fastly-mcp-launch|org\.freedesktop\.secrets|\bps[[:space:]]+[a-zA-Z]*e[a-zA-Z]*([[:space:]]|$)'
if grep -Eq "$re" <<<"$text"; then
  echo "secret-guard: blocked (keyring / process-env / Fastly token access is off-limits to Claude)" >&2
  exit 2
fi
exit 0
