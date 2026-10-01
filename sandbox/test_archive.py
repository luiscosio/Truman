import io
import json
import socket
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from sandbox.archive import Store, FrozenWorld, durable, encoded, freeze, journal, read_blob, seal, sha, verify
from sandbox.recording import Recorder
from sandbox.wikipedia import Handler


class ArchiveTests(unittest.TestCase):
    def test_host_failure_is_reported_even_without_a_delivered_http_error(self):
        from sandbox.run import attach_world_outcomes
        root=self.root/'world';(root/'attempts').mkdir(parents=True)
        for name in ('old','new'):
            p=root/'attempts'/name;p.mkdir()
            durable(p/'context.json',encoded({'title':name}))
            durable(p/'failure.json',encoded({'error':'provider timeout'}));seal(p)
        result={'status':'completed','agent_status':'completed','network_requests':[{'status':200}]}
        attach_world_outcomes(result,[(root,{'old'})])
        self.assertEqual(result['status'],'generation_failed')
        self.assertEqual(result['agent_status'],'completed')
        self.assertEqual([o['title'] for o in result['world_generation']],['new'])
        clean={'status':'completed'};attach_world_outcomes(clean,[(root,{'old','new'})])
        self.assertEqual(clean['status'],'completed')
        queue=self.root/'queue';queue.mkdir()
        durable(queue/'late.request.json',encoded({'path':'/wiki/Unfinished'}))
        clean={'status':'completed'};attach_world_outcomes(clean,[(root,{'old','new'})],queue)
        self.assertEqual(clean['status'],'generation_failed')
        self.assertEqual(clean['world_requests'][0]['coverage'],'incomplete')
        durable(queue/'late.response.json',encoded({'status':503,'coverage':'generation_failed'}))
        clean={'status':'completed'};attach_world_outcomes(clean,[(root,{'old','new'})],queue)
        self.assertEqual(clean['status'],'generation_failed')

    def test_normalized_proxy_capture_cannot_be_frozen_as_wire_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            durable(root / "run.json", encoded({"status": "completed", "network_mode": "managed"}))
            seal(root)
            with self.assertRaisesRegex(ValueError, "source renderer"):
                freeze(root, root / "snapshot")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_concurrent_blobs_events_and_seal_detect_changes(self):
        store = Store(self.root / "capture")
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda n: store.event("test", number=n, blob=store.blob(b"same bytes")), range(40)))
        self.assertEqual(len(list((store.root / "blobs").iterdir())), 1)
        self.assertEqual(len(journal(store.root / "events.jsonl")), 40)
        fingerprint = seal(self.root)
        self.assertEqual(verify(self.root), fingerprint)
        (self.root / "extra").write_text("unexpected")
        with self.assertRaises(ValueError):
            verify(self.root)

    def test_chain_detects_reordered_events(self):
        store = Store(self.root)
        store.event("first")
        store.event("second")
        lines = (self.root / "events.jsonl").read_bytes().splitlines(keepends=True)
        (self.root / "events.jsonl").write_bytes(b"".join(reversed(lines)))
        with self.assertRaises(ValueError):
            journal(self.root / "events.jsonl")

    def test_missing_or_corrupt_blob_is_rejected(self):
        store = Store(self.root)
        digest = store.blob(b"correct")
        (self.root / "blobs" / digest).write_bytes(b"wrong")
        with self.assertRaises(ValueError):
            read_blob(self.root, digest)
        with self.assertRaises(ValueError):
            read_blob(self.root, "../outside")

    def test_stdout_preserves_malformed_bytes_and_trailing_events(self):
        recorder = Recorder(self.root)
        raw = b'{"type":"result","subtype":"success"}\nnot json\xff\n{"type":"late_telemetry"}\n'
        recorder.start(io.BytesIO(raw))
        outgoing = io.BytesIO()
        recorder.send(outgoing, "A question", follow_up=True)
        recorder.close()
        self.assertEqual((self.root / "agent.stdout.bin").read_bytes(), raw)
        self.assertEqual((self.root / "agent.stdin.jsonl").read_bytes(), outgoing.getvalue())
        self.assertIn("late_telemetry", [e["type"] for e in recorder.events])
        self.assertEqual(sum(e["kind"] == "stdout_parse_error" for e in journal(recorder.store.root / "events.jsonl")), 1)
        self.assertIsNone(recorder.error)


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "run"
        self.source.mkdir()
        page = {"title": "Monarchy", "revision_id": 42, "revision_at": "2016-09-13T10:00:00Z", "sha256": sha(b"Elizabeth II is monarch."), "source_url": "https://en.wikipedia.org/wiki/Monarchy"}
        self.world = SimpleNamespace(pages={"Monarchy": page}, _text={"Monarchy": "Elizabeth II is monarch."},
                                     condition="historical", evidence=lambda url: page)
        durable(self.source / "run.json", encoded({"status": "completed", "batch_id": "source"}))
        durable(self.source / "images.json", encoded({"agent_then_world": ["agent", "renderer"]}))

    def server(self, world, capture_root):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.world = world
        server.capture = Store(capture_root)
        durable(capture_root / "context.json", encoded({"condition": "historical", "as_of": "2026-09-17", "bundle_manifest_sha256": "corpus"}))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server

    def request(self, server, path, method="GET", extra=b""):
        with socket.create_connection(("127.0.0.1", server.server_port), timeout=3) as stream:
            stream.sendall(f"{method} {path} HTTP/1.0\r\nHost: en.wikipedia.org\r\n".encode() + extra + b"\r\n")
            response = b""
            while chunk := stream.recv(65536):
                response += chunk
            return response

    def stop(self, server):
        server.shutdown()
        server.server_close()

    def record(self):
        server = self.server(self.world, self.source / "capture")
        try:
            get = self.request(server, "/wiki/Monarchy", extra=b"Authorization: secret\r\nCookie: private\r\n")
            head = self.request(server, "/wiki/Monarchy", "HEAD")
            missing = self.request(server, "/wiki/Missing")
        finally:
            self.stop(server)
        seal(self.source)
        self.snapshot = self.root / "snapshot"
        freeze(self.source, self.snapshot)
        return get, head, missing

    def test_exact_wire_bytes_get_head_404_and_explicit_miss(self):
        get, head, missing = self.record()
        events = (self.source / "capture/events.jsonl").read_text()
        self.assertNotIn("secret", events)
        self.assertNotIn("private", events)
        frozen = FrozenWorld(self.snapshot, "strict")
        server = self.server(frozen, self.root / "replay")
        try:
            self.assertEqual(get, self.request(server, "/wiki/Monarchy"))
            self.assertEqual(head, self.request(server, "/wiki/Monarchy", "HEAD"))
            self.assertEqual(missing, self.request(server, "/wiki/Missing"))
            self.assertTrue(self.request(server, "/wiki/Unrecorded").startswith(b"HTTP/1.0 409"))
        finally:
            self.stop(server)
        records = journal(server.capture.root / "events.jsonl")
        self.assertEqual(sum(e.get("replay") == "exact" for e in records), 3)
        self.assertEqual(sum(e.get("replay") == "strict_miss" for e in records), 1)

    def test_new_api_query_uses_frozen_article_without_generator(self):
        self.record()
        world = FrozenWorld(self.snapshot, "world")
        server = self.server(world, self.root / "replay")
        try:
            response = self.request(server, "/w/api.php?action=query&titles=Monarchy&prop=revisions&rvprop=timestamp&formatversion=2")
            value = json.loads(response.split(b"\r\n\r\n", 1)[1])
            self.assertEqual(value["query"]["pages"][0]["revisions"][0]["timestamp"], "2016-09-13T10:00:00Z")
            self.assertTrue(self.request(server, "/wiki/Uncaptured").startswith(b"HTTP/1.0 404"))
        finally:
            self.stop(server)
        responses = [e for e in journal(server.capture.root / "events.jsonl") if e["kind"] == "http_response"]
        self.assertEqual([e["replay"] for e in responses], ["derived", "outside_snapshot"])


if __name__ == "__main__":
    unittest.main()
