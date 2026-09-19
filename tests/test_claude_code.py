import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_truman import make_bundle
from truman.claude_code import EXPECTED_TOOL, check_auth, command, convert_events, subscription_environment
from truman.mcp_server import Reader
from truman.world import World, wiki_url


class MCPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.trace = root / "trace.jsonl"
        self.reader = Reader(World(make_bundle(root / "bundle"), "historical"), self.trace, 1)

    def test_handshake_and_tool_inventory(self):
        init = self.reader.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                  "params": {"protocolVersion": "2025-06-18"}})
        self.assertEqual(init["result"]["protocolVersion"], "2025-06-18")
        tools = self.reader.handle({"id": 2, "method": "tools/list"})["result"]["tools"]
        self.assertEqual([tool["name"] for tool in tools], ["open_url"])
        self.assertNotIn("historical", json.dumps(tools))
        self.assertIsNone(self.reader.handle({"method": "notifications/initialized"}))

    def test_page_result_and_operator_only_trace(self):
        request = {"id": 3, "method": "tools/call", "params": {"name": "open_url", "arguments": {
            "url": wiki_url("Monarchy of the United Kingdom"), "offset": 0}}}
        with patch("socket.socket", side_effect=AssertionError("network attempted")):
            reply = self.reader.handle(request)
        self.assertFalse(reply["result"]["isError"])
        text = reply["result"]["content"][0]["text"]
        self.assertIn("Elizabeth II", text)
        self.assertNotIn("revision_id", text)
        trace = json.loads(self.trace.read_text(encoding="utf-8"))
        self.assertEqual(trace["evidence"]["revision_id"], 50)
        limited = self.reader.handle(request)
        self.assertTrue(limited["result"]["isError"])
        self.assertIn("tool_call_limit", limited["result"]["content"][0]["text"])

    def test_unknown_tools_cannot_run(self):
        reply = self.reader.handle({"id": 3, "method": "tools/call", "params": {"name": "Bash", "arguments": {}}})
        self.assertTrue(reply["result"]["isError"])
        self.assertIn("unknown_tool", reply["result"]["content"][0]["text"])


class ClaudeCodeTests(unittest.TestCase):
    def test_subscription_environment_does_not_modify_parent(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "private", "ANTHROPIC_BASE_URL": "https://elsewhere"}):
            env = subscription_environment()
            self.assertNotIn("ANTHROPIC_API_KEY", env)
            self.assertNotIn("ANTHROPIC_BASE_URL", env)
            self.assertEqual(os.environ["ANTHROPIC_API_KEY"], "private")
            self.assertEqual(env["ENABLE_TOOL_SEARCH"], "false")

    def test_tool_confinement_flags_and_no_auth_bypass(self):
        args = command("claude", {"mcpServers": {}}, None, "date context", 4)
        self.assertEqual(args[args.index("--tools") + 1], "")
        self.assertEqual(args[args.index("--allowedTools") + 1], EXPECTED_TOOL)
        self.assertIn("--strict-mcp-config", args)
        self.assertIn("--no-session-persistence", args)
        self.assertIn("--restricted", args)
        self.assertNotIn("--bare", args)  # Bare mode disables subscription auth.
        self.assertNotIn("--dangerously-skip-permissions", args)
        self.assertNotIn("--model", args)

    def test_auth_status_redacts_account_identity(self):
        class Process:
            stdout = json.dumps({"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "max",
                                 "email": "private@example.com", "orgId": "private"})
        with patch("truman.claude_code.subprocess.run", return_value=Process()):
            status = check_auth("claude", {})
        self.assertEqual(set(status), {"loggedIn", "authMethod", "subscriptionType"})

    def test_api_auth_not_silently_used(self):
        class Process:
            stdout = json.dumps({"loggedIn": True, "authMethod": "apiKey"})
        with patch("truman.claude_code.subprocess.run", return_value=Process()), self.assertRaisesRegex(ValueError, "subscription"):
            check_auth("claude", {})

    def test_actual_model_and_result_appear_in_report(self):
        raw = [{"type": "system", "subtype": "init", "model": "actual-model", "tools": [EXPECTED_TOOL]},
               {"type": "assistant", "_received_at": 20, "message": {"content": [{"type": "text", "text": "Final"}]}},
               {"type": "result", "subtype": "success", "result": "Final", "usage": {"output_tokens": 12}}]
        tools = [{"kind": "tool_result", "timestamp": 10, "result": {"url": "https://en.wikipedia.org/wiki/Test"}}]
        result = convert_events(raw, tools, {"system": "date", "prompt": "prompt", "required_urls": ["https://en.wikipedia.org/wiki/Test"]}, "completed", 3)
        self.assertEqual(result["model"], "actual-model")
        self.assertEqual(result["final_answer"], "Final")
        self.assertTrue(result["required_pages_opened"])
        self.assertEqual(result["events"][1]["kind"], "tool_result")
        self.assertEqual(result["observed_tools"], [EXPECTED_TOOL])

    def test_follow_up_keeps_both_answers_and_user_turn_in_order(self):
        raw = [
            {"type": "assistant", "_received_at": 1, "message": {"content": [{"type": "text", "text": "First answer"}]}},
            {"type": "result", "result": "First answer", "subtype": "success"},
            {"type": "truman_user", "text": "Why? <script>", "_received_at": 2},
            {"type": "assistant", "_received_at": 3, "message": {"content": [{"type": "text", "text": "Explanation"}]}},
            {"type": "result", "result": "Explanation", "subtype": "success"},
        ]
        result = convert_events(raw, [], {"system": "date", "prompt": "prompt", "required_urls": []}, "completed", 3)
        self.assertEqual([e["kind"] for e in result["events"]], ["start", "assistant", "user", "assistant", "finish"])
        self.assertEqual([a["text"] for a in result["conversation_answers"]], ["First answer", "Explanation"])
        self.assertEqual(result["final_answer"], "Explanation")
        from truman.report import report_html
        result.update(id="historical-1", batch_id="test", is_demonstration=False, condition="historical", repetition=1)
        rendered = report_html([result], "test")
        self.assertIn("User follow-up", rendered)
        self.assertIn("Why? &lt;script&gt;", rendered)
        result.update(condition='synthetic',generator='b',world_mode='exploration')
        live=report_html([result],'live')
        self.assertIn('Seeded pages + live rewriting',live)
        self.assertIn('New pages may be acquired and rewritten',live)
        self.assertNotIn('No live Wikipedia retrieval occurs during a run',live)
        self.assertNotIn('Sonnet rewritten pages',live)


if __name__ == "__main__":
    unittest.main()
