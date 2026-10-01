"""Frozen origin responses served and archived through mitmproxy's HTTP stack.

Archives are final application fields/bodies, not HTTP/2 compressed wire frames.
The response hook is before sending: queued_for_delivery does not assert receipt.
"""
import asyncio
import base64
import http.client as http_client
import json
import os
import time
from email.utils import formatdate
from pathlib import Path

from mitmproxy import http, io
from sandbox.archive import Store, FrozenWorld, durable, encoded, sha
from sandbox.site_policy import validate

HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade"}
PRIVATE = {"authorization", "proxy-authorization", "cookie"}


def normalized_headers(original, length):
    hop = HOP | {value.strip().lower() for key, value in original if key.lower() == "connection" for value in value.split(",")}
    headers = [(k, v) for k, v in original if k.lower() not in hop | {"date", "content-length", "x-world-coverage", "x-world-evidence"}
               and not (k.lower() == "server" and v.strip() == "MediaWiki")]
    headers += [("Date", formatdate(usegmt=True)), ("Content-Length", str(length))]
    return headers


class FrozenHTTP:
    def load(self, loader):
        self.world = FrozenWorld("/snapshot", "world")
        self.capture = Store("/capture")
        self.sites = validate(json.loads(Path("/sites.json").read_bytes()))
        durable(self.capture.root / "context.json", encoded({"condition": self.world.condition,
            "bundle_manifest_sha256": self.world.manifest_hash, "as_of": self.world.manifest["worlds"]["reference"]["cutoff"],
            "capture_scope": "Final application HTTP fields and body; no HTTP/2 wire framing or client receipt assertion"}))
        for key, page in self.world.pages.items():
            self.capture.article(key, page, self.world._text[key])
        self.stream = (self.capture.root / "flows.mitm").open("xb")
        self.writer = io.FlowWriter(self.stream)

    def origin(self, path, host):
        upstream = http_client.HTTPConnection("wikipedia", 80, timeout=int(os.environ.get('WORLD_ORIGIN_TIMEOUT','20')))
        try:
            upstream.request("GET", path, headers={"Host": host, "Connection": "close"})
            response = upstream.getresponse()
            body = response.read(8_000_001)
            if len(body) > 8_000_000:
                raise ValueError("Origin response exceeds capture limit")
            return response.status, response.getheaders(), body
        finally:
            upstream.close()

    async def request(self, flow):
        request = flow.request
        host = request.host_header.lower().split(":")[0] if request.host_header else ""
        site = self.sites.get(host)
        # Provider TLS never reaches this HTTP stack. Do not retain page credentials.
        headers = [(k, "[redacted]" if k.lower() in PRIVATE else v) for k, v in request.headers.items(multi=True)]
        self.capture.event("http_request", request_id=flow.id, method=request.method, host=host, path=request.path,
            origin="agent", request_headers=headers, request_body_blob=self.capture.blob(request.raw_content or b""))
        flow.metadata.update(host=host, started=time.monotonic())
        try:
            if not site or site.get("transport") != "frozen-wikipedia":
                status, original, body = 403, [("Content-Type", "text/plain")], b"Access denied by network policy"
            elif request.method not in ("GET", "HEAD"):
                status, original, body = 405, [("Content-Type", "text/plain"), ("Allow", "GET, HEAD")], b"Method not allowed"
            else:
                status, original, body = await asyncio.to_thread(self.origin, request.path, host)
            flow.metadata["representation"] = body
            flow.metadata["origin_headers"] = original
            response_headers = http.Headers([(k.encode("latin1"), v.encode("latin1")) for k, v in normalized_headers(original, len(body))])
            flow.response = http.Response.make(status, b"" if request.method == "HEAD" else body, response_headers)
            # Response.make recomputes content length, including for HEAD.
            flow.response.headers["Content-Length"] = str(len(body))
        except Exception as exc:
            self.capture.event("origin_error", request_id=flow.id, error=str(exc))
            flow.response = http.Response.make(502, b"Upstream unavailable", {"Content-Type": "text/plain"})
            flow.metadata["representation"] = flow.response.raw_content

    def response(self, flow):
        response, request = flow.response, flow.request
        host, body = flow.metadata["host"], flow.metadata["representation"]
        version = "HTTP/2" if flow.client_conn.alpn == b"h2" else "HTTP/1.1"
        response.http_version = version
        if version == "HTTP/2":
            response.headers = http.Headers([(k.lower(), v) for k, v in response.headers.fields])
        route = self.world.lookup(request.method, host, request.path)
        proof = route.get("evidence") if route else self.world.evidence("https://" + host + request.path)
        replay = "exact" if route else ("outside_snapshot" if response.status_code == 404 and not proof else "derived")
        if os.environ.get('WORLD_ON_DEMAND'):
            internal={k.lower():v for k,v in flow.metadata.get('origin_headers',[])}
            replay=internal.get('x-world-coverage','error')
            if internal.get('x-world-evidence'):proof=json.loads(base64.b64decode(internal['x-world-evidence']))
        if response.status_code >= 500 and replay not in ('generation_failed', 'outside_snapshot'):
            replay = "error"
        elif route and (sha(body) != route["representation_blob"] or response.status_code != route["status"]):
            raise ValueError("Frozen route returned different content")
        canonical = (version + " " + str(response.status_code) + " " + response.reason + "\r\n").encode()
        canonical += b"".join(k + b": " + v + b"\r\n" for k, v in response.headers.fields) + b"\r\n"
        self.capture.event("http_response", request_id=flow.id, method=request.method, host=host, path=request.path,
            status=response.status_code, condition=self.world.condition, origin="agent", evidence=proof,
            site_category=self.sites.get(host, {}).get("category", "unlisted-blocked"), replay=replay,
            replay_scope="body; proxy normalizes application headers", capture_scope="application-fields; not wire framing",
            http_version=version, connection_id=flow.client_conn.id, bytes=len(body), response_sha256=sha(body),
            elapsed_seconds=round(time.monotonic() - flow.metadata["started"], 6),
            headers_blob=self.capture.blob(canonical), body_blob=self.capture.blob(response.raw_content or b""),
            representation_blob=self.capture.blob(body), upstream_headers=flow.metadata.get("origin_headers", []))
        saved = flow.copy()
        for key in PRIVATE:
            if key in saved.request.headers:
                saved.request.headers[key] = "[redacted]"
        self.writer.add(saved)
        self.stream.flush()
        os.fsync(self.stream.fileno())
        self.capture.event("http_delivery", request_id=flow.id, outcome="queued_for_delivery")

    def error(self, flow):
        self.capture.event("proxy_error", request_id=flow.id, error=str(flow.error))

    def done(self):
        self.stream.close()


addons = [FrozenHTTP()]
