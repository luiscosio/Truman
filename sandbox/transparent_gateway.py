"""Sandbox-only HTTP interception and opaque allowlisted provider TLS relay."""
import http.client
import ipaddress
import json
import os
import select
import socket
import socketserver
import ssl
import struct
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from dnslib import RR, A, QTYPE, RCODE
from dnslib.server import BaseResolver, DNSServer, DNSLogger
from sandbox.archive import Store, FrozenWorld, durable, encoded, sha

PROVIDERS = {"api.anthropic.com", "claude.ai", "platform.claude.com"}
WIKI = {"en.wikipedia.org", "en.m.wikipedia.org", "wikipedia.org", "www.wikipedia.org"}


def client_hello_sni(data):
    """Return SNI from a complete ClientHello, None when more bytes are needed."""
    handshake, offset = b"", 0
    while offset + 5 <= len(data):
        kind, major, minor, length = struct.unpack("!BBBH", data[offset:offset + 5])
        if kind != 22 or major != 3 or length > 18432:
            raise ValueError("Not a supported TLS handshake")
        if offset + 5 + length > len(data):
            return None
        handshake += data[offset + 5:offset + 5 + length]
        offset += 5 + length
        if len(handshake) < 4:
            continue
        wanted = int.from_bytes(handshake[1:4], "big") + 4
        if handshake[0] != 1 or wanted > 65536:
            raise ValueError("Invalid ClientHello")
        if len(handshake) < wanted:
            continue
        hello = handshake[4:wanted]
        try:
            p = 34
            p += 1 + hello[p]
            p += 2 + int.from_bytes(hello[p:p + 2], "big")
            p += 1 + hello[p]
            end = p + 2 + int.from_bytes(hello[p:p + 2], "big")
            p += 2
            if end > len(hello):
                raise ValueError("Truncated extensions")
            while p + 4 <= end:
                kind, length = struct.unpack("!HH", hello[p:p + 4])
                ext = hello[p + 4:p + 4 + length]
                if len(ext) != length:
                    raise ValueError("Truncated extension")
                if kind == 0:
                    q = 2
                    while q + 3 <= len(ext):
                        size = int.from_bytes(ext[q + 1:q + 3], "big")
                        if q + 3 + size > len(ext):
                            raise ValueError("Truncated hostname")
                        if ext[q] == 0:
                            return ext[q + 3:q + 3 + size].decode("ascii").lower().rstrip(".")
                        q += 3 + size
                p += 4 + length
        except (IndexError, UnicodeError, struct.error) as exc:
            raise ValueError("Malformed ClientHello") from exc
        raise ValueError("SNI required")
    return None


def peek_sni(stream):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        data = stream.recv(65536, socket.MSG_PEEK)
        if not data:
            raise ValueError("Closed before ClientHello")
        name = client_hello_sni(data)
        if name:
            return name
        if len(data) >= 65536:
            raise ValueError("Oversized ClientHello")
        time.sleep(0.01)
    raise TimeoutError("Incomplete ClientHello")


def public_addresses(name):
    values = sorted({row[4][0] for row in socket.getaddrinfo(name, 443, socket.AF_INET, socket.SOCK_STREAM)})
    if not values or any(not ipaddress.ip_address(value).is_global for value in values):
        raise ValueError("Upstream resolved to non-public address")
    return values


class Resolver(BaseResolver):
    def __init__(self, answers, audit):
        self.answers, self.audit = answers, audit

    def resolve(self, request, handler):
        reply = request.reply()
        name = str(request.q.qname).rstrip(".").lower()
        kind = request.q.qtype
        addresses = []
        try:
            if name not in WIKI | PROVIDERS:
                reply.header.rcode = RCODE.NXDOMAIN
            elif kind == QTYPE.A:
                addresses = self.answers[name] if name in WIKI else public_addresses(name)
                for address in addresses:
                    reply.add_answer(RR(request.q.qname, QTYPE.A, ttl=300, rdata=A(address)))
            # IPv6 is deliberately unsupported, returning NODATA rather than allowing a bypass.
        except (OSError, ValueError):
            reply.header.rcode = RCODE.SERVFAIL
        self.audit.event("dns", name=name, query_type=QTYPE[kind], addresses=addresses,
                         rcode=reply.header.rcode)
        return reply


class HTTP(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        started = time.monotonic()
        request_id = uuid.uuid4().hex
        host = self.headers.get("Host", "").lower().split(":")[0]
        capture, world = self.server.capture, self.server.world
        capture.event("http_request", request_id=request_id, method=self.command, host=host,
            path=self.path, origin="agent", request_headers=[(k, "[redacted]" if k.lower() in
            ("authorization", "proxy-authorization", "cookie") else v) for k, v in self.headers.items()])
        proof, upstream_headers = None, []
        route = world.lookup(self.command, host, self.path)
        replay = "exact" if route else ("strict_miss" if world.mode == "strict" else "derived")
        status, content_type, body = 502, "text/plain; charset=utf-8", b"Upstream unavailable"
        try:
            if host not in WIKI:
                status, body, replay = 404, b"Not found", "outside_snapshot"
            elif self.command not in ("GET", "HEAD"):
                status, body, replay = 405, b"Method not allowed", "derived"
            elif world.mode == "strict" and not route:
                status, body = 409, b"Request absent from frozen recording"
            else:
                # GET retrieves the full representation for the HEAD archive too.
                upstream = http.client.HTTPConnection("wikipedia", 80, timeout=20)
                try:
                    upstream.request("GET", self.path, headers={"Host": host, "Connection": "close"})
                    response = upstream.getresponse()
                    body = response.read(8_000_001)
                    if len(body) > 8_000_000:
                        raise ValueError("Upstream body exceeds capture limit")
                    status, upstream_headers = response.status, response.getheaders()
                    content_type = response.getheader("Content-Type", "application/octet-stream")
                finally:
                    upstream.close()
                proof = route.get("evidence") if route else world.evidence("https://" + host + self.path)
                if status == 404:
                    replay = "outside_snapshot" if not proof else "derived"
        except Exception as exc:
            self.server.audit.event("origin_error", request_id=request_id, error=str(exc))
            status, body = 502, b"Upstream unavailable"
        wire = b"" if self.command == "HEAD" else body
        reason = self.responses.get(status, ("Response",))[0]
        # No fabricated CDN/cache-hit claims. Content bytes remain unchanged.
        headers = (f"HTTP/1.1 {status} {reason}\r\nDate: {self.date_time_string()}\r\n"
                   f"Content-Type: {content_type}\r\nContent-Length: {len(body)}\r\n"
                   "Cache-Control: no-store\r\nX-Content-Type-Options: nosniff\r\n"
                   "Strict-Transport-Security: max-age=31536000; includeSubDomains\r\n"
                   "Connection: close\r\n\r\n").encode("latin-1")
        event = dict(request_id=request_id, method=self.command, host=host, path=self.path,
            status=status, condition=world.condition, origin="agent", evidence=proof, replay=replay,
            replay_scope="body; gateway normalizes HTTP headers", bytes=len(body), response_sha256=sha(body),
            elapsed_seconds=round(time.monotonic() - started, 6),
            headers_blob=capture.blob(headers), body_blob=capture.blob(wire), representation_blob=capture.blob(body),
            upstream_headers=upstream_headers)
        capture.event("http_response", **event)
        outcome = "write_completed"
        try:
            self.wfile.write(headers)
            self.wfile.write(wire)
            self.wfile.flush()
        except (OSError, ssl.SSLError):
            outcome = "client_disconnected"
        capture.event("http_delivery", request_id=request_id, outcome=outcome)
        self.close_connection = True

    do_HEAD = do_GET
    do_POST = do_GET
    do_PUT = do_GET
    do_DELETE = do_GET
    do_PATCH = do_GET
    do_OPTIONS = do_GET


class Edge(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class Connection(socketserver.BaseRequestHandler):
    def relay(self, address):
        with socket.create_connection(address, 20) as upstream:
            self.request.settimeout(30)
            upstream.settimeout(30)
            while True:
                ready, _, _ = select.select([self.request, upstream], [], [], 120)
                if not ready:
                    return
                for source in ready:
                    data = source.recv(65536)
                    if not data:
                        return
                    (upstream if source is self.request else self.request).sendall(data)

    def handle(self):
        client, edge = self.request, self.server
        client.settimeout(10)
        identifier = uuid.uuid4().hex
        name, destination = None, None
        try:
            original = client.getsockopt(socket.SOL_IP, 80, 16)  # Linux SO_ORIGINAL_DST
            port = int.from_bytes(original[2:4], "big")
            destination = socket.inet_ntoa(original[4:8])
            if port not in (80, 443):
                raise ValueError("Not an intercepted web connection")
            if port == 80:
                if destination not in edge.world_ips:
                    raise ValueError("HTTP destination not allowed")
                edge.audit.event("connection", connection_id=identifier, destination=destination, port=port, decision="world")
                if getattr(edge, "managed", False):
                    self.relay(("127.0.0.1", 9000))
                else:
                    HTTP(client, self.client_address, edge)
                return
            name = peek_sni(client)
            if name in getattr(edge, "world_names", WIKI):
                if destination not in edge.world_ips:
                    raise ValueError("World destination differs from pinned DNS")
                edge.audit.event("connection", connection_id=identifier, destination=destination, port=port, sni=name, decision="world")
                if getattr(edge, "managed", False):
                    self.relay(("127.0.0.1", 9000))
                else:
                    with edge.tls.wrap_socket(client, server_side=True) as secured:
                        HTTP(secured, self.client_address, edge)
            elif getattr(edge, "managed", False) and name in getattr(edge, "intercept_names", ()):
                if destination not in edge.intercept_ips:
                    raise ValueError("Intercepted destination differs from pinned DNS")
                edge.audit.event("connection", connection_id=identifier, destination=destination, port=port, sni=name, decision="intercept")
                self.relay(("127.0.0.1", 9000))
            elif name in getattr(edge, "providers", PROVIDERS):
                addresses = public_addresses(name)
                # Connect only to a fresh, validated address for the allowed SNI.
                with socket.create_connection((addresses[0], 443), 20) as upstream:
                    edge.audit.event("connection", connection_id=identifier, destination=destination,
                        port=port, sni=name, upstream=addresses[0], decision="provider_passthrough")
                    client.settimeout(30)
                    upstream.settimeout(30)
                    transferred = 0
                    while True:
                        ready, _, _ = select.select([client, upstream], [], [], 120)
                        if not ready:
                            break
                        for source in ready:
                            data = source.recv(65536)
                            if not data:
                                return
                            (upstream if source is client else client).sendall(data)
                            transferred += len(data)
            else:
                raise ValueError("TLS hostname not allowed")
        except Exception as exc:
            edge.audit.event("connection_error", connection_id=identifier, sni=name, destination=destination, error=str(exc))
        finally:
            edge.audit.event("connection_closed", connection_id=identifier)


def main():
    capture, audit = Store("/capture"), Store("/network-audit")
    world = FrozenWorld("/snapshot", os.environ.get("WORLD_REPLAY_MODE", "world"))
    answers = json.loads(Path("/dns.json").read_bytes())["answers"]
    durable(capture.root / "context.json", encoded({"condition": world.condition,
        "bundle_manifest_sha256": world.manifest_hash, "as_of": world.manifest["worlds"]["reference"]["cutoff"]}))
    for key, page in world.pages.items():
        capture.article(key, page, world._text[key])
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain("/tls/server.crt", "/tls/server.key")
    tls.set_alpn_protocols(["http/1.1"])
    for port in (8080, 8443):
        edge = Edge(("0.0.0.0", port), Connection)
        edge.world, edge.capture, edge.audit, edge.tls = world, capture, audit, tls
        edge.world_ips = {ip for addresses in answers.values() for ip in addresses}
        threading.Thread(target=edge.serve_forever, daemon=True).start()
    resolver = Resolver(answers, audit)
    for tcp in (False, True):
        DNSServer(resolver, port=53, address="0.0.0.0", tcp=tcp, logger=DNSLogger(log="error", prefix=False)).start_thread()
    durable(audit.root / "ready.json", encoded({"ready": True, "snapshot_sha256": world.snapshot_hash}))
    threading.Event().wait()


if __name__ == "__main__":
    main()
