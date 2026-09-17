"""Minimal stdio MCP reader. Run in a network-disabled container."""

import json
import sys
import time
from pathlib import Path

from .providers import TOOL
from .world import World


class Reader:
    def __init__(self, world: World, trace: Path, max_calls: int):
        self.world, self.trace, self.max_calls = world, trace, max_calls
        self.calls = 0

    def handle(self, request: dict) -> dict | None:
        request_id = request.get("id")
        method = request.get("method")
        if request_id is None:
            return None
        reply = {"jsonrpc": "2.0", "id": request_id}
        if method == "initialize":
            requested = request.get("params", {}).get("protocolVersion")
            version = requested if requested in ("2024-11-05", "2025-03-26", "2025-06-18") else "2025-06-18"
            reply["result"] = {"protocolVersion": version, "capabilities": {"tools": {}},
                               "serverInfo": {"name": "wikipedia-reader", "version": "0.1.0"}}
        elif method == "ping":
            reply["result"] = {}
        elif method == "tools/list":
            reply["result"] = {"tools": [{"name": TOOL["name"], "description": TOOL["description"],
                "inputSchema": TOOL["parameters"],
                "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}}]}
        elif method == "tools/call":
            params = request.get("params", {})
            args = params.get("arguments", {})
            self.calls += 1
            evidence = None
            if self.calls > self.max_calls:
                output = {"error": "tool_call_limit", "message": "The page-reading limit has been reached."}
            elif params.get("name") != "open_url":
                output = {"error": "unknown_tool", "message": "That tool is unavailable."}
            elif not isinstance(args, dict) or set(args) != {"url", "offset"}:
                output = {"error": "invalid_arguments", "message": "Supply url and offset."}
            else:
                output = self.world.open_url(args["url"], args["offset"])
                if "error" not in output:
                    evidence = self.world.evidence(args["url"])
            with self.trace.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"kind": "tool_result", "timestamp": time.time(),
                    "call": {"id": request_id, "name": params.get("name"), "arguments": args},
                    "result": output, "evidence": evidence}, ensure_ascii=False) + "\n")
            reply["result"] = {"content": [{"type": "text", "text": json.dumps(output, ensure_ascii=False)}],
                               "isError": "error" in output}
        else:
            reply["error"] = {"code": -32601, "message": "Method not found"}
        return reply


def serve(bundle: Path, condition: str, trace: Path, max_calls: int):
    reader = Reader(World(bundle, condition), trace, max_calls)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("Expected an object")
            reply = reader.handle(request)
        except (ValueError, TypeError, KeyError):
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
        if reply is not None:
            print(json.dumps(reply, ensure_ascii=False), flush=True)
