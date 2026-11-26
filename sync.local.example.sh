# Copy to sync.local.sh (gitignored) and adapt. Sourced by sync.sh.
# It names the things you do NOT want public, so it must never be committed.

# Paths under ~/.claude to leave out (rsync rules, anchored with a leading /).
EXCLUDES=(
  --exclude=/bin/some-launcher-that-reads-a-token
  --exclude=/skills/some-client-specific-skill/
)

# MCP servers to leave out, by name.
MCP_SKIP='["internal-gitlab", "personal-server"]'

# sed -E expressions applied to every exported text file. Specific patterns first.
REPLACE=(
  's/\bacme-corp\b/client-a/gI'
  's/MyEmployer/Vendor/g'
  's/\bmyusername\b/user/g'
)

# Anything matching this (case-insensitive) after the rewrites fails the run. List every name REPLACE handles.
PRIVATE_TERMS='acme-corp|myemployer|myusername'
