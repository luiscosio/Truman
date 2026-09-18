"""Serve the pinned corpus over ordinary Wikipedia HTTP(S) URLs."""

import hashlib
import html
import json
import os
import re
import ssl
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import mwparserfromhell as mw

from truman.world import World, title_key, url_title, wiki_url
from sandbox.synthetic import GenerationError, SyntheticWorld
from sandbox.archive import Store, FrozenWorld, encoded, durable, read_blob


def escape(value):
    return html.escape(str(value), quote=True)


def render_code(code):
    """Conservative offline renderer: no template expansion or remote assets."""
    parts = []
    for node in code.nodes:
        kind = type(node).__name__
        if kind == "Text":
            text = escape(node.value)
            text = re.sub(r"&#x27;&#x27;&#x27;(.*?)&#x27;&#x27;&#x27;", r"<b>\1</b>", text, flags=re.S)
            text = re.sub(r"&#x27;&#x27;(.*?)&#x27;&#x27;", r"<i>\1</i>", text, flags=re.S)
            parts.append(text)
        elif kind == "Wikilink":
            target = str(node.title).strip()
            if not target.lower().startswith(("file:", "image:", "category:")):
                label = render_code(node.text) if node.text is not None else escape(target)
                parts.append(f'<a href="{escape(wiki_url(target))}">{label}</a>')
        elif kind == "ExternalLink":
            url = str(node.url).strip()
            label = render_code(node.title) if node.title is not None else escape(url)
            if urlsplit(url).scheme in ("http", "https"):
                parts.append(f'<a href="{escape(url)}">{label}</a>')
            else:
                parts.append(label)
        elif kind == "Heading":
            level = max(2, min(6, node.level))
            parts.append(f'<h{level}>{render_code(node.title)}</h{level}>')
        elif kind == "HTMLEntity":
            parts.append(escape(node.normalize()))
        elif kind == "Tag":
            if str(node.tag).lower() not in ("ref", "references", "script", "style", "gallery"):
                if node.contents is not None:
                    rendered = render_code(node.contents)
                    tag = str(node.tag).lower()
                    parts.append(f'<{tag}>{rendered}</{tag}>' if tag in ("b", "i", "strong", "em", "sup", "sub", "p", "li", "ul", "ol", "table", "tr", "td", "th") else rendered)
        elif kind == "Template":
            name = str(node.name).strip().lower()
            if name.startswith("infobox"):
                rows = []
                for param in node.params:
                    key = str(param.name).strip()
                    if key.lower().startswith(("image", "flag", "insignia", "coat", "signature", "alt", "caption")):
                        continue
                    value = render_code(param.value).strip()
                    if value:
                        rows.append(f'<tr><th>{escape(key.replace("_", " "))}</th><td>{value}</td></tr>')
                parts.append('<table class="infobox">' + ''.join(rows) + '</table>')
            elif name in ("nowrap", "nobr", "small", "lang", "lang-fr", "lang-en"):
                values = [p.value for p in node.params if not p.showkey]
                if values:
                    parts.append(render_code(values[-1]))
            elif name in ("birth date", "birth date and age", "death date", "death date and age", "start date", "end date"):
                values = [str(p.value).strip() for p in node.params if not p.showkey][:3]
                parts.append(escape("-".join(values)))
    return ''.join(parts)


def article_html(page, source):
    body = render_code(mw.parse(source))
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(page['title'])} - Wikipedia</title>
<style>body{{font:16px/1.65 Georgia,serif;margin:0;color:#202122;background:#fff}}header{{padding:20px 4%;border-bottom:1px solid #a2a9b1;font:24px Georgia}}main{{max-width:1100px;margin:auto;padding:30px}}h1{{font-weight:normal;border-bottom:1px solid #a2a9b1}}a{{color:#36c;text-decoration:none}}.mw-parser-output{{white-space:pre-wrap;overflow-wrap:anywhere}}.infobox{{float:right;width:340px;white-space:normal;border:1px solid #a2a9b1;background:#f8f9fa;margin:0 0 20px 24px;font:13px/1.5 sans-serif}}th,td{{padding:4px;text-align:left;vertical-align:top}}footer{{clear:both;border-top:1px solid #a2a9b1;margin-top:40px;padding-top:15px;font:12px sans-serif}}</style></head>
<body><header>WIKIPEDIA <small>The Free Encyclopedia</small></header><main><h1 id="firstHeading">{escape(page['title'])}</h1>
<div id="mw-content-text"><div class="mw-parser-output">{body}</div></div>
<footer>This page was last edited on {escape(page['revision_at'])}.<br>Text is available under the Creative Commons Attribution-ShareAlike License; additional terms may apply. <a href="{escape(page.get('source_url', '#'))}">Revision and contributors</a>.</footer>
</main></body></html>'''


class Handler(BaseHTTPRequestHandler):
    server_version = "MediaWiki"
    sys_version = ""

    def log_message(self, *args):
        pass

    def do_HEAD(self):
        self.do_GET()

    def begin_request(self):
        self.request_id = uuid.uuid4().hex
        self.request_started = time.monotonic()
        self.replay_kind = None
        capture = getattr(self.server, "capture", None) if self.path != "/health" else None
        if capture:
            headers = [(k, "[redacted]" if k.lower() in ("authorization", "proxy-authorization", "cookie") else v)
                       for k, v in self.headers.items()]
            capture.event("http_request", request_id=self.request_id, method=self.command,
                host=self.headers.get("Host", ""), path=self.path, request_headers=headers,
                origin="setup" if self.client_address[0] in ("127.0.0.1", "::1") else "agent")

    def respond(self, status, content_type, body, page=None, recorded_headers=None, evidence=None):
        world = self.server.world
        capture = getattr(self.server, "capture", None) if self.path != "/health" else None
        proof = evidence if evidence is not None else (world.evidence(wiki_url(page["title"])) if page else None)
        if recorded_headers is None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self._headers_buffer.append(b"\r\n")
            header_bytes = b"".join(self._headers_buffer)
            self._headers_buffer = []
        else:
            header_bytes = recorded_headers
        wire_body = b"" if self.command == "HEAD" else body
        event = {"request_id": self.request_id, "method": self.command, "path": self.path,
            "host": self.headers.get("Host", ""), "status": status, "condition": world.condition,
            "origin": "setup" if self.client_address[0] in ("127.0.0.1", "::1") else "agent",
            "response_sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body), "evidence": proof,
            "replay": self.replay_kind, "elapsed_seconds": round(time.monotonic() - self.request_started, 6)}
        if capture:
            event.update(headers_blob=capture.blob(header_bytes), body_blob=capture.blob(wire_body),
                         representation_blob=capture.blob(body))
            if page:
                key = title_key(page["title"])
                capture.article(key, page, world._text[key])
            persisted = capture.event("http_response", **event)
            event.update(timestamp=persisted["timestamp"], capture_seq=persisted["seq"])
        else:
            event["timestamp"] = time.time()
        delivery = "write_completed"
        try:
            self.wfile.write(header_bytes)
            self.wfile.write(wire_body)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            delivery = "client_disconnected"
        if capture:
            capture.event("http_delivery", request_id=self.request_id, outcome=delivery)
        if self.path != "/health":
            print(json.dumps({**event, "delivery": delivery}), flush=True)

    def do_POST(self):
        self.begin_request()
        capture = getattr(self.server, "capture", None)
        try:
            size = max(0, int(self.headers.get("Content-Length", "0")))
        except ValueError:
            size = 0
        self.connection.settimeout(10)
        body = self.rfile.read(min(size, 1_000_000)) if size else b""
        if capture:
            capture.event("unsupported_request_body", request_id=self.request_id,
                          body_blob=capture.blob(body), truncated=size > len(body),
                          transfer_encoding=self.headers.get("Transfer-Encoding"))
        self.respond(405, "text/plain; charset=utf-8", b"Method not allowed")

    do_PUT = do_POST
    do_DELETE = do_POST
    do_PATCH = do_POST
    do_OPTIONS = do_POST

    def do_GET(self):
        world = self.server.world
        self.begin_request()
        if isinstance(world, FrozenWorld) and self.path != "/health":
            route = world.lookup(self.command, self.headers.get("Host", ""), self.path)
            if route:
                self.replay_kind = "exact"
                self.respond(route["status"], None, read_blob(world.root, route["representation_blob"]),
                    recorded_headers=read_blob(world.root, route["headers_blob"]), evidence=route["evidence"])
                return
            self.replay_kind = "strict_miss" if world.mode == "strict" else "derived"
            if world.mode == "strict":
                self.respond(409, "text/plain; charset=utf-8", b"Request absent from frozen recording")
                return
        parts = urlsplit(self.path)
        if isinstance(world, FrozenWorld) and world.snapshot.get("presentation") == "captured-html-v1" and self.path != "/health":
            if self.headers.get("Host", "").split(":")[0].lower() not in ("en.wikipedia.org", "en.m.wikipedia.org", "wikipedia.org", "www.wikipedia.org"):
                self.replay_kind = "outside_snapshot"
                self.respond(404, "text/plain", b"Not found")
                return
            from sandbox.rewrite_http import response
            status, content_type, body, page, extra, self.replay_kind = response(world, self.path)
            if extra:
                from email.utils import formatdate
                headers = (f"HTTP/1.1 {status} Found\r\nContent-Type: {content_type}\r\nContent-Length: {len(body)}\r\nDate: {formatdate(usegmt=True)}\r\n" +
                           ''.join(f"{k}: {v}\r\n" for k,v in extra.items()) + '\r\n').encode()
            else:
                headers = None
            self.respond(status, content_type, body, page, recorded_headers=headers)
            return
        query = parse_qs(parts.query, keep_blank_values=True)
        page, content_type, status = None, "text/html; charset=utf-8", 200
        if self.path == "/health":
            body = b"ok"
        else:
            try:
                host = self.headers.get("Host", "").split(":")[0].lower()
                if host not in ("en.wikipedia.org", "en.m.wikipedia.org", "wikipedia.org", "www.wikipedia.org"):
                    raise ValueError("Unknown host")
                if parts.path == "/w/api.php":
                    title = query.get("titles", query.get("page", [""]))[0]
                    key = title_key(title)
                elif parts.path == "/w/index.php" and query.get("action") == ["raw"]:
                    key = title_key(query.get("title", [""])[0])
                else:
                    key = url_title("https://en.wikipedia.org" + self.path)
                page = world.pages.get(key)
                if not page:
                    if isinstance(world, FrozenWorld):
                        self.replay_kind = "outside_snapshot"
                    raise ValueError("Unavailable page")
                if hasattr(world, "prepare"):
                    world.prepare(key, self.path, request_id=self.request_id)
                    page = world.pages[key]
                source = world._text[key]
                if parts.path == "/w/api.php":
                    content_type = "application/json; charset=utf-8"
                    action = query.get("action", ["query"])[0]
                    if action == "parse":
                        payload = {"parse": {"title": page["title"], "text": {"*": render_code(mw.parse(source))}}}
                    elif action == "query":
                        page_id = page.get("page_id", 1)
                        info = {"pageid": page_id, "ns": 0, "title": page["title"]}
                        props = query.get("prop", ["revisions"])[0].split("|")
                        if not set(props) <= {"revisions", "extracts", "info"}:
                            raise ValueError("Unsupported query property")
                        if "revisions" in props:
                            requested = query.get("rvprop", ["ids|timestamp"])[0].split("|")
                            revision = {}
                            if "ids" in requested:
                                revision["revid"] = page["revision_id"]
                            if "timestamp" in requested:
                                revision["timestamp"] = page["revision_at"]
                            if "content" in requested:
                                if "rvslots" in query:
                                    revision["slots"] = {"main": {"*": source, "contentmodel": "wikitext", "contentformat": "text/x-wiki"}}
                                else:
                                    revision["*"] = source
                            info["revisions"] = [revision]
                        if "extracts" in props:
                            excerpt = source.split("\n==", 1)[0] if "exintro" in query else source
                            code = mw.parse(excerpt)
                            info["extract"] = code.strip_code().strip() if "explaintext" in query else render_code(code)
                        if "info" in props:
                            info.update(contentmodel="wikitext", pagelanguage="en", lastrevid=page["revision_id"],
                                        touched=page["revision_at"], length=len(source.encode()))
                        pages = [info] if query.get("formatversion") == ["2"] else {str(page_id): info}
                        payload = {"batchcomplete": "", "query": {"pages": pages}}
                    else:
                        raise ValueError("Unsupported API action")
                    body = json.dumps(payload, ensure_ascii=False).encode()
                elif query.get("action") == ["raw"]:
                    content_type = "text/plain; charset=utf-8"
                    body = source.encode()
                else:
                    body = article_html(page, source).encode()
            except GenerationError:
                status = 503
                page = None
                body = b"<!doctype html><title>Service unavailable</title><h1>Service unavailable</h1>"
                content_type = "text/html; charset=utf-8"
            except ValueError:
                status = 404
                body = b"<!doctype html><title>Page unavailable</title><h1>Page unavailable</h1>"
        self.respond(status, content_type, body, page)


def serve():
    condition = os.environ.get("WORLD_CONDITION", "historical")
    if os.environ.get("WORLD_REPLAY_DIR"):
        world = FrozenWorld(os.environ["WORLD_REPLAY_DIR"], os.environ.get("WORLD_REPLAY_MODE", "world"))
    else:
        world = (SyntheticWorld(Path("/data"), os.environ["WORLD_MODEL_URL"], os.environ["WORLD_AUDIT_DIR"],
                                json.loads(os.environ["WORLD_SCENARIO_JSON"]) if os.environ.get("WORLD_SCENARIO_JSON") else None)
                 if condition == "synthetic" else World(Path("/data"), condition))
    capture = Store(os.environ["WORLD_CAPTURE_DIR"]) if os.environ.get("WORLD_CAPTURE_DIR") else None
    if capture:
        durable(capture.root / "context.json", encoded({"condition": world.condition,
            "bundle_manifest_sha256": world.manifest_hash,
            "as_of": world.manifest["worlds"]["reference"]["cutoff"][:10]}))
        if not isinstance(world, SyntheticWorld):
            for key, page in world.pages.items():
                capture.article(key, page, world._text[key])
    http = ThreadingHTTPServer(("0.0.0.0", 80), Handler)
    https = ThreadingHTTPServer(("0.0.0.0", 443), Handler)
    http.world = https.world = world
    http.capture = https.capture = capture
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain("/tls/server.crt", "/tls/server.key")
    https.socket = ctx.wrap_socket(https.socket, server_side=True)
    threading.Thread(target=http.serve_forever, daemon=True).start()
    https.serve_forever()


if __name__ == "__main__":
    serve()
