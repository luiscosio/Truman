"""Managed DNS policy and opaque TLS routing into a mature HTTP proxy."""
import json
import os
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path

from dnslib import RR, A, QTYPE, RCODE
from dnslib.server import BaseResolver, DNSServer, DNSLogger
from sandbox.archive import Store, durable, encoded
from sandbox.site_policy import validate
from sandbox.transparent_gateway import Connection, Edge, public_addresses


class ManagedResolver(BaseResolver):
    def __init__(self, answers, policy, audit):
        self.answers, self.sites, self.audit = answers, validate(policy), audit

    def resolve(self, request, handler):
        reply = request.reply()
        name = str(request.q.qname).rstrip(".").lower()
        site = self.sites.get(name)
        addresses = []
        try:
            if not site:
                reply.header.rcode = RCODE.REFUSED
            elif request.q.qtype == QTYPE.A:
                # Only inference providers use current DNS; website answers are frozen.
                addresses = public_addresses(name) if site.get("transport") == "tls-passthrough" else self.answers[name]
                for address in addresses:
                    reply.add_answer(RR(request.q.qname, QTYPE.A, ttl=300, rdata=A(address)))
        except (OSError, ValueError, KeyError):
            reply.header.rcode = RCODE.SERVFAIL
        self.audit.event("dns", name=name, query_type=QTYPE.get(request.q.qtype, str(request.q.qtype)),
                         addresses=addresses, rcode=reply.header.rcode,
                         site_category=site["category"] if site else "unlisted-blocked")
        return reply


def main():
    audit = Store("/network-audit")
    policy = json.loads(Path("/sites.json").read_bytes())
    sites = validate(policy)
    answers = json.loads(Path("/dns.json").read_bytes())["answers"]
    wiki = {name for name, site in sites.items() if site.get("transport") == "frozen-wikipedia"}
    providers = {name for name, site in sites.items() if site.get("transport") == "tls-passthrough"}
    command = ["mitmdump", "--mode", "reverse:http://wikipedia:80@9000", "--listen-host", "127.0.0.1",
               "--set", "confdir=/tmp/proxy", "--set", "connection_strategy=lazy", "--set", "upstream_cert=false",
               "--set", "keep_host_header=true", "--set", "body_size_limit=8m", "--set", "flow_detail=0",
               "--certs", "*=/tls/server.pem", "-s", "/app/sandbox/managed_http.py"]
    child = subprocess.Popen(command)
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    try:
        for _ in range(150):
            if child.poll() is not None:
                raise RuntimeError("HTTP proxy exited during startup")
            try:
                with socket.create_connection(("127.0.0.1", 9000), 0.2):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("HTTP proxy did not become ready")
        for port in (8080, 8443):
            edge = Edge(("0.0.0.0", port), Connection)
            edge.managed, edge.audit, edge.wiki_names, edge.providers = True, audit, wiki, providers
            edge.wiki_ips = {ip for name in wiki for ip in answers[name]}
            threading.Thread(target=edge.serve_forever, daemon=True).start()
        resolver = ManagedResolver(answers, policy, audit)
        for tcp in (False, True):
            DNSServer(resolver, port=53, address="0.0.0.0", tcp=tcp, logger=DNSLogger(log="error", prefix=False)).start_thread()
        audit.event("site_policy", policy=policy)
        durable(audit.root / "ready.json", encoded({"ready": True, "engine": "mitmproxy"}))
        while not stop.wait(0.5):
            if child.poll() is not None:
                raise RuntimeError("HTTP proxy exited unexpectedly")
    finally:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


if __name__ == "__main__":
    main()
