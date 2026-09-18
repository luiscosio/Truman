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
openssl req -newkey rsa:2048 -nodes -sha256 -subj '/CN=en.wikipedia.org' \
    -keyout /tls/server.key -out /tls/server.csr
printf '%s\n' 'subjectAltName=DNS:en.wikipedia.org,DNS:en.m.wikipedia.org,DNS:wikipedia.org,DNS:www.wikipedia.org' \
    'basicConstraints=critical,CA:FALSE' 'keyUsage=critical,digitalSignature,keyEncipherment' \
    'extendedKeyUsage=serverAuth' > /tls/extensions.cnf
openssl x509 -req -in /tls/server.csr -CA /trust/ca.crt -CAkey /tls/ca.key \
    -CAcreateserial -CAserial /tls/ca.srl -days 365 -sha256 \
    -extfile /tls/extensions.cnf -out /tls/server.crt
chmod 644 /trust/ca.crt /tls/server.crt
chown 10001:10001 /tls/server.key
cat /tls/server.crt /tls/server.key /trust/ca.crt > /tls/server.pem
echo 'Sandbox-only CA and Wikipedia certificate created.'
