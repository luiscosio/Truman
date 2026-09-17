#!/bin/sh
set -eu
# The login source is read-only. Runtime state disappears with this container.
mkdir -p "$HOME/.claude"
if [ -f /login/credentials.json ]; then
    cp /login/credentials.json "$HOME/.claude/.credentials.json"
    chmod 600 "$HOME/.claude/.credentials.json"
fi
printf '%s\n' '{"hasCompletedOnboarding":true}' > "$HOME/.claude.json"
cat /etc/ssl/certs/ca-certificates.crt /trust/ca.crt > /tmp/ca-bundle.crt
export SSL_CERT_FILE=/tmp/ca-bundle.crt
export REQUESTS_CA_BUNDLE=/tmp/ca-bundle.crt
export CURL_CA_BUNDLE=/tmp/ca-bundle.crt
exec "$@"
