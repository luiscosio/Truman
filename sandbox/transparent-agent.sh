#!/bin/sh
set -eu
mkdir -p "$HOME/.claude"
if [ -f /login/credentials.json ]; then
    cp /login/credentials.json "$HOME/.claude/.credentials.json"
    chmod 600 "$HOME/.claude/.credentials.json"
fi
printf '%s\n' '{"hasCompletedOnboarding":true}' > "$HOME/.claude.json"
exec "$@"
