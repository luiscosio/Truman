#!/bin/sh
set -eu
umask 077
if [ -s /tls/server.crt ] && [ -s /trust/ca.crt ]; then
    echo 'Existing sandbox certificates retained.'
    exit 0
fi
if [ -e /tls/ca.key ] || [ -e /tls/server.crt ] || [ -e /trust/ca.crt ]; then
    echo 'Partial certificate state: use new Docker volumes instead of overwriting.' >&2
    exit 1
fi
openssl req -x509 -newkey rsa:2048 -nodes -days 365 -sha256 \
    -subj "/CN=${TRUMAN_CA_NAME:-Sandbox Local CA}" -keyout /tls/ca.key -out /trust/ca.crt \
    -addext 'basicConstraints=critical,CA:TRUE' -addext 'keyUsage=critical,keyCertSign,cRLSign'
# TRUMAN_SERVER_NAMES lists every simulated host, comma-separated; the first is the subject.
names="${TRUMAN_SERVER_NAMES:-en.wikipedia.org,en.m.wikipedia.org,wikipedia.org,www.wikipedia.org}"
case "$names" in *[!a-z0-9.,-]*|''|,*|*,|*,,*) echo "Invalid server names: $names" >&2; exit 1;; esac
openssl req -newkey rsa:2048 -nodes -sha256 -subj "/CN=${names%%,*}" \
    -keyout /tls/server.key -out /tls/server.csr
printf '%s\n' "subjectAltName=DNS:$(printf '%s' "$names" | sed 's/,/,DNS:/g')" \
    'basicConstraints=critical,CA:FALSE' 'keyUsage=critical,digitalSignature,keyEncipherment' \
    'extendedKeyUsage=serverAuth' > /tls/extensions.cnf
openssl x509 -req -in /tls/server.csr -CA /trust/ca.crt -CAkey /tls/ca.key \
    -CAcreateserial -CAserial /tls/ca.srl -days 365 -sha256 \
    -extfile /tls/extensions.cnf -out /tls/server.crt
chmod 644 /trust/ca.crt /tls/server.crt
chown 10001:10001 /tls/server.key
cat /tls/server.crt /tls/server.key /trust/ca.crt > /tls/server.pem
# One certificate per host, named for that host, as a public site's own certificate is.
mkdir /tls/hosts
for name in $(printf '%s' "$names" | tr ',' ' '); do
    openssl req -newkey rsa:2048 -nodes -sha256 -subj "/CN=$name" \
        -keyout "/tls/hosts/$name.key" -out "/tls/hosts/$name.csr" 2>/dev/null
    printf '%s\n' "subjectAltName=DNS:$name" 'basicConstraints=critical,CA:FALSE' \
        'keyUsage=critical,digitalSignature,keyEncipherment' 'extendedKeyUsage=serverAuth' > "/tls/hosts/$name.cnf"
    openssl x509 -req -in "/tls/hosts/$name.csr" -CA /trust/ca.crt -CAkey /tls/ca.key \
        -CAserial /tls/ca.srl -days 365 -sha256 -extfile "/tls/hosts/$name.cnf" -out "/tls/hosts/$name.crt" 2>/dev/null
    cat "/tls/hosts/$name.crt" "/tls/hosts/$name.key" /trust/ca.crt > "/tls/hosts/$name.pem"
    rm "/tls/hosts/$name.key" "/tls/hosts/$name.csr" "/tls/hosts/$name.cnf"
done
echo "Sandbox-only CA and certificates created for: $names"
