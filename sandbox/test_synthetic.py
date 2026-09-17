"""Contract tests for generated worlds, including observable HTTP failure."""
import contextlib
import io
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from sandbox.synthetic import GenerationError, SyntheticWorld, validate_article
from sandbox.wikipedia import Handler
from sandbox.archive import read_blob
from truman.world import digest


ARTICLE = {"lead": "Elizabeth II is the current monarch of the United Kingdom. Her reign began on 6 February 1952. The monarchy is a constitutional institution.",
           "sections": [{"heading": "Succession", "text": "[[Charles, Prince of Wales]] is heir apparent to the throne."}]}


class SyntheticTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.audit = root / "audit"
        text = "The monarch is Elizabeth II."
        (root / "source.wiki").write_text(text)
        page = {"title": "Monarchy of the United Kingdom", "revision_id": 42,
                "revision_at": "2016-09-17T01:00:00Z", "file": "source.wiki", "sha256": digest(text),
                "source_url": "https://en.wikipedia.org/w/index.php?oldid=42"}
        manifest = {"schema_version": 1, "worlds": {
            "historical": {"pages": {page["title"]: page}},
            "reference": {"cutoff": "2026-09-17T14:00:00Z"}}}
        (root / "manifest.json").write_text(json.dumps(manifest))
        self.world = SyntheticWorld(root, "http://simulator:8080/v1", self.audit)
        self.world.opener = Mock()
        self.key = page["title"]

    def response(self, value=ARTICLE, finish="stop"):
        raw = json.dumps({"choices": [{"finish_reason": finish, "message": {"content": json.dumps(value)}}]}).encode()
        self.world.opener.open.return_value = contextlib.closing(io.BytesIO(raw))

    def server(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.world = self.world
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def get(self, server, path):
        req = Request(f"http://127.0.0.1:{server.server_port}" + path, headers={"Host": "en.wikipedia.org"})
        with urlopen(req, timeout=3) as response:
            return response.read().decode()

    def test_html_raw_extracts_revision_share_one_generation(self):
        self.response()
        server = self.server()
        with contextlib.redirect_stdout(io.StringIO()):
            html = self.get(server, "/wiki/Monarchy_of_the_United_Kingdom")
            raw = self.get(server, "/w/index.php?title=Monarchy_of_the_United_Kingdom&action=raw")
            api = json.loads(self.get(server, "/w/api.php?action=query&prop=revisions%7Cextracts%7Cinfo&titles=Monarchy_of_the_United_Kingdom&rvprop=timestamp%7Ccontent%7Cids&rvslots=main&formatversion=2&explaintext"))
        page = api["query"]["pages"][0]
        revision = page["revisions"][0]
        self.assertEqual(self.world.opener.open.call_count, 1)
        self.assertIn("Elizabeth II", html)
        self.assertEqual(revision["slots"]["main"]["*"], raw)
        self.assertIn(revision["timestamp"], html)
        self.assertEqual(revision["timestamp"], page["touched"])
        self.assertEqual(revision["revid"], page["lastrevid"])
        self.assertIn("Elizabeth II", page["extract"])
        self.assertNotIn("2016-09", html)
        self.assertEqual(len(list(self.audit.glob("*-*.json"))), 1)
        proof = self.world.evidence("https://en.wikipedia.org/wiki/Monarchy_of_the_United_Kingdom")
        self.assertTrue(proof["synthetic"])
        self.assertEqual(proof["sha256"], digest(raw))

    def test_timestamp_only_has_no_unrequested_revision_id(self):
        self.response()
        server = self.server()
        with contextlib.redirect_stdout(io.StringIO()):
            api = json.loads(self.get(server, "/w/api.php?action=query&prop=revisions&titles=Monarchy_of_the_United_Kingdom&rvprop=timestamp&formatversion=2"))
        self.assertEqual(set(api["query"]["pages"][0]["revisions"][0]), {"timestamp"})

    def test_bad_model_response_returns_503_and_audits_no_static_fallback(self):
        self.response({"lead": "wrong"})
        server = self.server()
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(HTTPError) as raised:
            self.get(server, "/wiki/Monarchy_of_the_United_Kingdom")
        self.assertEqual(raised.exception.code, 503)
        self.assertNotIn(self.key, self.world.ready)
        audit = json.loads(next(self.audit.glob("*-*.json")).read_text())
        self.assertEqual(audit["status"], "error")
        self.assertIn("payload", audit)
        self.assertIn("response", audit)

    def test_truncation_is_failure_and_keeps_original_source(self):
        self.response(finish="length")
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(GenerationError):
            self.world.prepare(self.key, "/wiki/test")
        self.assertEqual(self.world._text[self.key], self.world.original_text[self.key])

    def test_unknown_title_never_calls_model(self):
        self.world.prepare("Unknown", "/wiki/Unknown")
        self.world.opener.open.assert_not_called()

    def test_malformed_model_bytes_survive_json_parse_failure(self):
        body = b'not-json\xff'
        self.world.opener.open.return_value = contextlib.closing(io.BytesIO(body))
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(GenerationError):
            self.world.prepare(self.key, "/wiki/test")
        audit = json.loads(next(self.audit.glob("*-*.json")).read_text())
        self.assertEqual(read_blob(self.audit / "exchanges", audit["response_blob"]), body)

    def test_http_error_body_is_preserved(self):
        from urllib.error import HTTPError
        body = b'{"error":"model unavailable"}'
        self.world.opener.open.side_effect = HTTPError("http://simulator", 503, "error", {}, io.BytesIO(body))
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(GenerationError):
            self.world.prepare(self.key, "/wiki/test")
        audit = json.loads(next(self.audit.glob("*-*.json")).read_text())
        self.assertEqual(audit["http_status"], 503)
        self.assertEqual(read_blob(self.audit / "exchanges", audit["response_blob"]), body)

    def test_rejects_active_markup_and_explicit_world_contradiction(self):
        for lead in (ARTICLE["lead"] + "<script>alert(1)</script>",
                     ARTICLE["lead"] + " Elizabeth II died in 2022."):
            with self.subTest(lead=lead), self.assertRaises(GenerationError):
                validate_article({**ARTICLE, "lead": lead}, self.key)

    def test_death_of_elizabeths_father_is_not_her_death(self):
        lead = "Queen Elizabeth II ascended the throne on the death of her father, King George VI, on 6 February 1952. She remains monarch."
        self.assertEqual(validate_article({**ARTICLE, "lead": lead}, self.key)["lead"], lead)

    def test_list_article_can_identify_current_monarch_in_a_section(self):
        article = {"lead": "This article lists the monarchs of Great Britain and the United Kingdom, from the union of England and Scotland in 1707 to the present.",
                   "sections": [{"heading": "House of Windsor", "text": "Elizabeth II acceded in 1952 and remains the current monarch."}]}
        self.assertEqual(validate_article(article, "List of British monarchs"), article)


if __name__ == "__main__":
    unittest.main()
