#!/bin/sh
set -eu
if [ "${1:-}" = backend ]; then
    mkdir -p /srv/status
    printf 'ok\n' > /srv/status/health
    exec python -m http.server 8080 --bind 0.0.0.0 --directory /srv/status
fi
cp /bootstrap/authorized_keys /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
ssh-keygen -A
exec /usr/sbin/sshd -D -e
