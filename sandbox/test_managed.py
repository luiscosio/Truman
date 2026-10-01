import asyncio
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dnslib import DNSRecord, RCODE
from mitmproxy import http
from sandbox.archive import Store, journal
from sandbox.managed_gateway import ManagedResolver
from sandbox.managed_http import FrozenHTTP, normalized_headers
from sandbox.site_policy import effective, validate

POLICY = {"schema_version": 1, "default": "block",
          "altered": [{"hosts": ["en.wikipedia.org"], "transport": "frozen-wikipedia", "reason": "Test"}],
          "unaltered": [{"hosts": ["api.anthropic.com"], "transport": "tls-passthrough", "reason": "Inference"}],
          "blacklisted": [{"hosts": ["example.com"], "reason": "Outside experiment"}]}


class ManagedTests(unittest.TestCase):
    def test_generation_failure_keeps_distinct_audit_classification(self):
        import time
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryFile() as stream:
            addon=FrozenHTTP();addon.capture=Store(temp);addon.sites=validate(POLICY)
            addon.world=SimpleNamespace(condition='synthetic',lookup=lambda *a:None,evidence=lambda *a:None)
            addon.writer=Mock();addon.stream=stream
            flow=SimpleNamespace(id='failed',request=http.Request.make('GET','https://en.wikipedia.org/wiki/Test'),
                response=http.Response.make(503,b'Unavailable'),client_conn=SimpleNamespace(alpn=None,id='connection'),
                metadata={'host':'en.wikipedia.org','representation':b'Unavailable','started':time.monotonic(),
                          'origin_headers':[('X-World-Coverage','generation_failed')]})
            flow.copy=lambda:flow
            with patch.dict('os.environ',{'WORLD_ON_DEMAND':'1'}):addon.response(flow)
            result=next(e for e in journal(Path(temp)/'events.jsonl') if e['kind']=='http_response')
            self.assertEqual(result['replay'],'generation_failed')

    def test_overlapping_policies_rejected(self):
        policy = copy.deepcopy(POLICY)
        policy["blacklisted"][0]["hosts"].append("en.wikipedia.org")
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            validate(policy)

    def test_reference_changes_classification_without_changing_routing(self):
        reference = effective(POLICY, "reference")
        self.assertEqual(reference["altered"], [])
        self.assertEqual(validate(reference)["en.wikipedia.org"]["transport"], "frozen-wikipedia")
        self.assertEqual(validate(POLICY)["en.wikipedia.org"]["category"], "altered")

    def test_blacklisted_resolves_but_unlisted_is_refused_not_nxdomain(self):
        with tempfile.TemporaryDirectory() as temp:
            resolver = ManagedResolver({"example.com": ["93.184.215.14"]}, POLICY, Store(temp))
            with patch("sandbox.managed_gateway.public_addresses", side_effect=AssertionError("Unexpected external DNS")):
                known = resolver.resolve(DNSRecord.question("example.com"), None)
                self.assertEqual(known.header.rcode, RCODE.NOERROR)
                self.assertEqual(str(known.rr[0].rdata), "93.184.215.14")
                self.assertEqual(resolver.resolve(DNSRecord.question("unlisted.invalid"), None).header.rcode, RCODE.REFUSED)

    def test_headers_preserve_end_to_end_and_remove_connection_named_fields(self):
        headers = normalized_headers([("Content-Type", "text/html"), ("ETag", '"abc"'),
            ("Connection", "close, x-internal"), ("X-Internal", "secret"), ("Content-Length", "99"),
            ("Server", "MediaWiki"), ("Cache-Control", "max-age=60")], 3)
        fields = {k.lower(): v for k, v in headers}
        self.assertEqual(fields["etag"], '"abc"')
        self.assertEqual(fields["cache-control"], "max-age=60")
        self.assertEqual(fields["content-length"], "3")
        self.assertFalse(set(fields) & {"connection", "x-internal", "server"})
        private=normalized_headers([('X-World-Coverage','derived'),('X-World-Evidence','internal')],0)
        self.assertFalse(any(k.lower().startswith('x-world-') for k,v in private))

    def test_head_fetches_full_representation_without_transmitting_body(self):
        with tempfile.TemporaryDirectory() as temp:
            addon = FrozenHTTP()
            addon.capture, addon.sites = Store(temp), validate(POLICY)
            flow = SimpleNamespace(id="test", request=http.Request.make("HEAD", "https://en.wikipedia.org/wiki/Test", headers={"Host": "en.wikipedia.org"}), metadata={})
            fake = SimpleNamespace(request=lambda *a, **kw: None, close=lambda: None,
                getresponse=lambda: SimpleNamespace(status=200, getheaders=lambda: [("Content-Type", "text/html")], read=lambda n: b"abc"))
            with patch("sandbox.managed_http.http_client.HTTPConnection", return_value=fake):
                asyncio.run(addon.request(flow))
            self.assertEqual(flow.response.status_code, 200)
            self.assertEqual(flow.response.raw_content, b"")
            self.assertEqual(flow.response.headers["content-length"], "3")
            self.assertEqual(flow.metadata["representation"], b"abc")
            self.assertEqual(len(journal(Path(temp) / "events.jsonl")), 1)


if __name__ == "__main__":
    unittest.main()
