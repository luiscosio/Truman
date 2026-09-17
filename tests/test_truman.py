import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from truman.prepare import Wikipedia, cutoff, prepare
from truman.providers import Anthropic, OpenAI, Scripted, Turn
from truman.report import report_html
from truman.runner import execute, run_pair, task_prompt
from truman.world import World, digest, url_title, wiki_url


def make_bundle(root):
    root = Path(root)
    root.mkdir()
    manifest = {"schema_version": 1, "worlds": {}}
    for condition, name, date in (("reference", "Charles III", "2026-09-17"),
                                  ("historical", "Elizabeth II", "2016-09-16")):
        text = "| incumbent = [[" + name + "]]\n" + ("Article body.\n" * 1500)
        filename = f"{condition}.wiki"
        (root / filename).write_text(text, encoding="utf-8", newline="")
        manifest["worlds"][condition] = {"cutoff": date + "T12:00:00Z", "pages": {
            "Monarchy of the United Kingdom": {"title": "Monarchy of the United Kingdom",
                "file": filename, "sha256": digest(text), "revision_id": 100 if condition == "reference" else 50,
                "revision_at": date + "T10:00:00Z", "source_url": "https://en.wikipedia.org/w/index.php?oldid=50"}
        }}
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root


class WorldTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bundle = make_bundle(Path(self.temp.name) / "bundle")
        self.url = wiki_url("Monarchy of the United Kingdom")

    def test_retrieval_is_offline_and_world_specific(self):
        with patch("socket.socket", side_effect=AssertionError("network attempted")):
            new = World(self.bundle, "reference").open_url(self.url)
            old = World(self.bundle, "historical").open_url(self.url)
        self.assertIn("Charles III", new["text"])
        self.assertIn("Elizabeth II", old["text"])
        self.assertEqual(new["url"], old["url"])
        for private in ("condition", "sha256", "revision_id", "cutoff", "file"):
            self.assertNotIn(private, old)

    def test_pagination_reconstructs_exact_page(self):
        world = World(self.bundle, "historical")
        first = world.open_url(self.url)
        second = world.open_url(self.url, first["next_offset"])
        self.assertIsNone(second["next_offset"])
        self.assertEqual(first["text"] + second["text"], world._text["Monarchy of the United Kingdom"])

    def test_url_is_never_an_outbound_request(self):
        world = World(self.bundle, "historical")
        for url in ("file:///etc/passwd", "http://127.0.0.1/", "https://en.wikipedia.org.evil.com/wiki/Test",
                    "https://user@en.wikipedia.org/wiki/Test", "https://en.wikipedia.org:443/wiki/Test",
                    "https://en.wikipedia.org/wiki/Test?redirect=https://evil.com",
                    "https://en.wikipedia.org/w/index.php?title=Test&oldid=3", "not a url", None):
            with self.subTest(url=url):
                self.assertEqual(world.open_url(url)["error"], "unavailable")
        self.assertEqual(world.open_url("https://en.wikipedia.org/wiki/Unknown")["error"], "unavailable")

    def test_normalization(self):
        self.assertEqual(url_title("https://en.m.wikipedia.org/wiki/Fran%C3%A7ois_Hollande#Life"), "François Hollande")
        self.assertEqual(url_title("https://en.wikipedia.org/w/index.php?title=Elizabeth_II"), "Elizabeth II")

    def test_invalid_offset(self):
        world = World(self.bundle, "historical")
        for offset in (-1, True, "0", 999999):
            self.assertEqual(world.open_url(self.url, offset)["error"], "invalid_arguments")

    def test_tamper_detection(self):
        (self.bundle / "historical.wiki").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            World(self.bundle, "historical")

    def test_manifest_path_escape(self):
        manifest = json.loads((self.bundle / "manifest.json").read_text())
        manifest["worlds"]["historical"]["pages"]["Monarchy of the United Kingdom"]["file"] = "../secret"
        (self.bundle / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "escapes"):
            World(self.bundle, "historical")


class AcquisitionTests(unittest.TestCase):
    def test_cutoff_requires_timezone(self):
        self.assertEqual(cutoff("2016-09-16"), "2016-09-16T23:59:59Z")
        with self.assertRaises(ValueError):
            cutoff("2016-09-16T12:00:00")

    def test_queries_exact_historical_cutoff_without_live_template_rendering(self):
        api = Wikipedia()
        response = {"query": {"pages": [{"title": "Test", "revisions": [{"revid": 3,
            "timestamp": "2016-09-16T00:00:00Z", "slots": {"main": {"content": "{{Template}} raw content"}}}]}]}}
        with patch.object(api, "request", return_value=response) as request, patch("truman.prepare.time.sleep"):
            page = api.revision("Test", "2016-09-16T23:59:59Z")
        params = request.call_args.args[0]
        self.assertEqual(params["rvdir"], "older")
        self.assertEqual(params["rvstart"], "2016-09-16T23:59:59Z")
        self.assertEqual(page["content"], "{{Template}} raw content")

    def test_rejects_revision_after_cutoff(self):
        api = Wikipedia()
        response = {"query": {"pages": [{"title": "Test", "revisions": [{"revid": 3,
            "timestamp": "2026-09-16T00:00:00Z", "slots": {"main": {"content": "new"}}}]}]}}
        with patch.object(api, "request", return_value=response), self.assertRaisesRegex(ValueError, "beyond"):
            api.revision("Test", "2016-09-16T23:59:59Z")

    def test_refuses_overwriting_corpus(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "exists"):
                prepare(Path(folder), "2016-09-16", ["Test"])

    def test_redirect_target_uses_same_cutoff(self):
        calls = []
        def fake_revision(self, title, at):
            calls.append((title, at))
            return {"title": title, "revision_id": len(calls), "revision_at": at,
                    "content": "#REDIRECT [[Target]]" if title == "Alias" else "Actual article"}
        with tempfile.TemporaryDirectory() as folder, patch.object(Wikipedia, "revision", fake_revision):
            manifest = prepare(Path(folder) / "new", "2016-09-16", ["Alias"])
        self.assertEqual(calls[0][1], calls[1][1])
        self.assertEqual(calls[2][1], calls[3][1])
        self.assertIn("Target", manifest["worlds"]["historical"]["pages"])


class ProviderTests(unittest.TestCase):
    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"})
    def test_openai_roundtrip_preserves_reasoning_and_custom_tools_only(self):
        requests = []
        raw = {"status": "completed", "usage": {"input_tokens": 12, "output_tokens": 5}, "output": [
            {"type": "reasoning", "encrypted_content": "opaque"},
            {"type": "function_call", "call_id": "c1", "name": "open_url",
             "arguments": '{"url":"https://en.wikipedia.org/wiki/Test","offset":0}'}]}
        def transport(url, headers, body, timeout):
            requests.append(json.loads(json.dumps(body)))
            return raw
        provider = OpenAI("explicit-model", "ordinary system", "ordinary prompt", transport)
        turn = provider.step(1000, 10)
        provider.results([(turn.calls[0], {"text": "page"})])
        provider.step(1000, 10)
        self.assertEqual(requests[0]["tools"][0]["type"], "function")
        self.assertEqual(len(requests[0]["tools"]), 1)
        self.assertFalse(requests[0]["store"])
        self.assertEqual(requests[1]["input"][1]["encrypted_content"], "opaque")
        self.assertEqual(requests[1]["input"][3]["call_id"], "c1")
        self.assertEqual(turn.usage["input_tokens"], 12)

    @patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-only"})
    def test_anthropic_roundtrip_and_truncation(self):
        raw = {"stop_reason": "tool_use", "content": [{"type": "tool_use", "id": "t1", "name": "open_url",
               "input": {"url": "https://en.wikipedia.org/wiki/Test", "offset": 0}}],
               "usage": {"input_tokens": 1, "cache_read_input_tokens": 2, "output_tokens": 3}}
        provider = Anthropic("explicit-model", "system", "prompt", lambda *args: raw)
        turn = provider.step(1000, 10)
        provider.results([(turn.calls[0], {"error": "unavailable"})])
        self.assertEqual(provider.history[-1]["content"][0]["tool_use_id"], "t1")
        self.assertTrue(provider.history[-1]["content"][0]["is_error"])
        self.assertEqual(turn.usage["input_tokens"], 3)
        raw["stop_reason"] = "max_tokens"
        self.assertEqual(provider.step(1000, 10).status, "max_tokens")

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_credentials_fail_clearly(self):
        with self.assertRaisesRegex(ValueError, "OPENAI_API_KEY"):
            OpenAI("model", "system", "prompt")
        with self.assertRaisesRegex(ValueError, "ANTHROPIC_API_KEY"):
            Anthropic("model", "system", "prompt")


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = make_bundle(self.root / "bundle")
        self.prompt, self.urls = task_prompt("monarch")
        self.metadata = {"system": "system", "prompt": self.prompt, "required_urls": self.urls}

    def test_paired_demo_has_identical_prompts_fresh_sessions_and_explicit_labels(self):
        batch, results = run_pair(self.bundle, self.root / "runs", "scripted", None, "monarch", repeats=2)
        self.assertEqual(len(results), 4)
        self.assertEqual(len({r["prompt_sha256"] for r in results}), 1)
        for result in results:
            self.assertTrue(result["is_demonstration"])
            self.assertTrue(result["required_pages_opened"])
            self.assertEqual(result["status"], "completed")
            self.assertIsNone(result["manual_review"]["suspected_simulation"])
            self.assertNotIn("historical", result["prompt"])
            self.assertNotIn("Truman", result["system"])
            self.assertTrue((batch / result["id"] / "events.jsonl").is_file())

    def test_date_drift_rejected(self):
        with self.assertRaisesRegex(ValueError, "must match"):
            run_pair(self.bundle, self.root / "runs", "scripted", None, "monarch", as_of="2027-01-01")

    def test_error_preserves_partial_trace(self):
        class Broken:
            def step(self, *args):
                raise RuntimeError("Deliberate test failure")
        result = execute(World(self.bundle, "historical"), Broken(), self.root / "run", self.metadata)
        self.assertEqual(result["status"], "error")
        self.assertTrue((self.root / "run" / "run.json").is_file())
        self.assertEqual(result["events"][-2]["kind"], "error")

    def test_limits_stop_infinite_tool_use(self):
        class Repeated:
            def step(self, *args):
                return Turn({}, calls=[{"id": "call", "name": "open_url", "arguments": {"url": self_url, "offset": 0}}])
            def results(self, results):
                pass
        self_url = self.urls[0]
        result = execute(World(self.bundle, "historical"), Repeated(), self.root / "run", self.metadata, max_calls=1)
        self.assertEqual(result["status"], "tool_call_limit")
        self.assertEqual(result["tool_calls"], 1)

    def test_unknown_tool_cannot_execute(self):
        class Unknown(Scripted):
            def step(self, *args):
                turn = super().step(*args)
                for call in turn.calls:
                    call["name"] = "run_shell"
                return turn
        result = execute(World(self.bundle, "historical"), Unknown(self.urls), self.root / "run", self.metadata)
        self.assertFalse(result["page_exposure"])
        output = next(e for e in result["events"] if e["kind"] == "tool_result")
        self.assertEqual(output["result"]["error"], "unknown_tool")

    def test_no_tools_is_not_exposure(self):
        class Memory:
            def step(self, *args):
                return Turn({}, text="A memorized answer.")
        result = execute(World(self.bundle, "historical"), Memory(), self.root / "run", self.metadata)
        self.assertFalse(result["page_exposure"])
        self.assertFalse(result["required_pages_opened"])

    def test_output_tokens_capped_across_turns(self):
        class Expensive(Scripted):
            def step(self, *args):
                turn = super().step(*args)
                turn.usage = {"output_tokens": 300}
                return turn
        result = execute(World(self.bundle, "historical"), Expensive(self.urls), self.root / "run", self.metadata, total_output_tokens=400)
        self.assertEqual(result["status"], "output_token_limit")

    def test_html_escapes_source_and_embedded_json(self):
        _, results = run_pair(self.bundle, self.root / "runs", "scripted", None, "monarch")
        results[0]["final_answer"] = '</script><script>alert("injection")</script>'
        markup = report_html(results, "batch")
        self.assertNotIn('<script>alert("injection")', markup)
        self.assertIn("\\u003c/script>", markup)
        self.assertIn("not an AI evaluation", markup)
        self.assertNotIn('class="review"', markup)


if __name__ == "__main__":
    unittest.main()
