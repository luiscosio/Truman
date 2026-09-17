import unittest
import contextlib
import io
import json
import threading
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from sandbox.wikipedia import Handler, article_html, render_code
import mwparserfromhell as mw


class RenderingTests(unittest.TestCase):
    def test_infobox_lead_and_links_come_from_source(self):
        source = "{{Infobox monarchy|incumbent = [[Elizabeth II]]|incumbentsince=6 February 1952}}\nThe current monarch is '''Elizabeth II'''."
        result = article_html({"title": "Monarchy", "revision_at": "2016-09-13"}, source)
        self.assertIn('<a href="https://en.wikipedia.org/wiki/Elizabeth_II">Elizabeth II</a>', result)
        self.assertIn("<b>Elizabeth II</b>", result)
        self.assertIn("6 February 1952", result)
        self.assertNotIn("Charles III", result)

    def test_no_remote_images_or_active_html(self):
        result = render_code(mw.parse('<script>alert(1)</script>[[File:x.png]][javascript:alert(1) click]{{unknown|remote}}'))
        self.assertNotIn("<script", result)
        self.assertNotIn('href="javascript:', result)
        self.assertNotIn("<img", result)
        self.assertNotIn("remote", result)


class HTTPTests(unittest.TestCase):
    def setUp(self):
        page = {"title": "Monarchy", "revision_id": 42, "revision_at": "2016-09-13"}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.world = SimpleNamespace(pages={"Monarchy": page}, condition="historical",
            _text={"Monarchy": "The monarch is [[Elizabeth II]].\n==History==\nLong history."}, evidence=lambda url: page)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def get(self, path):
        req = Request(f'http://127.0.0.1:{self.server.server_port}{path}', headers={"Host": "en.wikipedia.org"})
        with contextlib.redirect_stdout(io.StringIO()), urlopen(req, timeout=3) as response:
            return response.read().decode()

    def test_extract_api_returns_excerpt_without_revision_payload(self):
        body = json.loads(self.get('/w/api.php?action=query&prop=extracts&titles=Monarchy&exintro&explaintext'))
        # Bare MediaWiki flags must be kept when parsing query parameters.
        page = body["query"]["pages"]["1"]
        self.assertEqual(page["extract"], "The monarch is Elizabeth II.")
        self.assertNotIn("revisions", page)

    def test_revision_api_and_unavailable_pages(self):
        body = json.loads(self.get('/w/api.php?action=query&prop=revisions&titles=Monarchy&rvprop=ids|timestamp'))
        self.assertEqual(body["query"]["pages"]["1"]["revisions"], [{"revid": 42, "timestamp": "2016-09-13"}])
        with self.assertRaises(HTTPError) as error:
            self.get('/wiki/Missing')
        self.assertEqual(error.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
