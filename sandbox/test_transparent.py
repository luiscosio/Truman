import io
import socket
import ssl
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dnslib import DNSRecord, RCODE
from sandbox.archive import Store, journal, read_blob
from sandbox.transparent_gateway import client_hello_sni, Resolver, Edge, HTTP


class TransparentTests(unittest.TestCase):
    def test_sni_parses_real_clienthello_without_consuming_tls(self):
        outgoing = ssl.MemoryBIO()
        tls = ssl.create_default_context().wrap_bio(ssl.MemoryBIO(), outgoing, server_hostname="api.anthropic.com")
        with self.assertRaises(ssl.SSLWantReadError):
            tls.do_handshake()
        wire = outgoing.read()
        self.assertEqual(client_hello_sni(wire), "api.anthropic.com")
        self.assertIsNone(client_hello_sni(wire[:-1]))
        # Handshake fragmentation across two TLS records remains supported.
        payload = wire[5:]
        parts = (payload[:20], payload[20:])
        fragmented = b"".join(b"\x16\x03\x01" + len(p).to_bytes(2, "big") + p for p in parts)
        self.assertEqual(client_hello_sni(fragmented), "api.anthropic.com")

    def test_invalid_tls_is_rejected(self):
        with self.assertRaises(ValueError):
            client_hello_sni(b"GET / HTTP/1.1")

    def test_dns_pins_wikipedia_and_never_resolves_unknown_names(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = Resolver({"en.wikipedia.org": ["208.80.153.224"]}, Store(temp))
            with patch("sandbox.transparent_gateway.public_addresses", side_effect=AssertionError("Unexpected upstream lookup")):
                response = resolver.resolve(DNSRecord.question("en.wikipedia.org"), None)
                self.assertEqual(str(response.rr[0].rdata), "208.80.153.224")
                self.assertEqual(resolver.resolve(DNSRecord.question("example.com"), None).header.rcode, RCODE.NXDOMAIN)
                self.assertEqual(resolver.resolve(DNSRecord.question("en.wikipedia.org", "AAAA"), None).rr, [])
            self.assertEqual(len(journal(Path(temp) / "events.jsonl")), 3)

    def test_post_gateway_capture_matches_final_wire_get_and_head(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            server = Edge(("127.0.0.1", 0), HTTP)
            server.capture, server.audit = Store(root / "capture"), Store(root / "audit")
            server.world = SimpleNamespace(condition="synthetic", mode="world", lookup=lambda *args: {"evidence": None})
            body = b'<html>Elizabeth II is queen.</html>'
            class Upstream:
                def __init__(self, *args, **kwargs): pass
                def request(self, *args, **kwargs): pass
                def getresponse(self):
                    return SimpleNamespace(status=200, read=lambda n: body,
                        getheaders=lambda: [("Server", "MediaWiki")], getheader=lambda *args: "text/html")
                def close(self): pass
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with patch("sandbox.transparent_gateway.http.client.HTTPConnection", Upstream):
                    for method in ("GET", "HEAD"):
                        with socket.create_connection(server.server_address, timeout=3) as stream:
                            stream.sendall(f"{method} /wiki/Test HTTP/1.1\r\nHost: en.wikipedia.org\r\nConnection: close\r\n\r\n".encode())
                            wire = b""
                            while data := stream.recv(65536): wire += data
                        event = [e for e in journal(root / "capture/events.jsonl") if e["kind"] == "http_response"][-1]
                        headers = read_blob(root / "capture", event["headers_blob"])
                        served = read_blob(root / "capture", event["body_blob"])
                        self.assertEqual(wire, headers + served)
                        self.assertTrue(headers.startswith(b"HTTP/1.1 200"))
                        self.assertNotIn(b"MediaWiki", headers)
                        self.assertEqual(served, body if method == "GET" else b"")
                        self.assertEqual(read_blob(root / "capture", event["representation_blob"]), body)
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
