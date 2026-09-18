#!/bin/sh
set -eu
if [ "${1:-}" = client ]; then
    ip route replace default via "$ROUTER_IP"
    # Prevent Docker's embedded resolver from bypassing the DNS allowlist.
    iptables -A OUTPUT -d 127.0.0.11 -j REJECT
    iptables -A OUTPUT -d "$ROUTER_IP" -p udp --dport 53 -j ACCEPT
    iptables -A OUTPUT -d "$ROUTER_IP" -p tcp --dport 53 -j ACCEPT
    iptables -A OUTPUT -p udp --dport 53 -j REJECT
    iptables -A OUTPUT -p tcp --dport 53 -j REJECT
    iptables -P OUTPUT DROP
    iptables -A OUTPUT -o lo -j ACCEPT
    iptables -A OUTPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
    for cidr in 0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16 172.16.0.0/12 192.168.0.0/16 224.0.0.0/4; do
        iptables -A OUTPUT -d "$cidr" -j REJECT
    done
    iptables -A OUTPUT -p tcp -m multiport --dports 80,443 -j ACCEPT
    exec sleep infinity
fi
# Only this task-owned namespace is changed. No host interfaces or rules.
edge=$(ip route get "$CLIENT_IP" | sed -n 's/.* dev \([^ ]*\).*/\1/p')
test -n "$edge"
iptables -P FORWARD DROP
iptables -t nat -A PREROUTING -i "$edge" -p tcp --dport 443 -j REDIRECT --to-ports 8443
iptables -t nat -A PREROUTING -i "$edge" -p tcp --dport 80 -j REDIRECT --to-ports 8080
exec python -m sandbox.transparent_gateway
