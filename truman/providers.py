"""Small provider adapters. Only custom tools are sent to the APIs."""

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field


TOOL = {
    "name": "open_url",
    "description": "Open an English Wikipedia article and read its source text, including infobox fields. Follow links to read other articles. Use offset 0 initially, then next_offset to continue long pages.",
    "parameters": {
        "type": "object", "properties": {
            "url": {"type": "string", "description": "The full Wikipedia article URL."},
            "offset": {"type": "integer", "minimum": 0, "description": "Character offset; use 0 for the first page."},
        }, "required": ["url", "offset"], "additionalProperties": False,
    },
}


@dataclass
class Turn:
    raw: dict
    text: str = ""
    calls: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    status: str = "completed"


def post_json(url: str, headers: dict, body: dict, timeout: float) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                    headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        # Never include request headers/API keys in logs; do not automatically retry paid calls.
        try:
            detail = json.loads(error.read()).get("error", {})
            code = detail.get("code") or detail.get("type") or "unknown"
        except (ValueError, AttributeError):
            code = "unknown"
        raise RuntimeError(f"Provider HTTP {error.code} ({code}); verify model access, key, and quota.") from None


class OpenAI:
    def __init__(self, model: str, system: str, prompt: str, transport=post_json):
        self.key = os.environ.get("OPENAI_API_KEY")
        if not self.key:
            raise ValueError("Set OPENAI_API_KEY in the process environment before running OpenAI experiments.")
        self.model, self.system, self.transport = model, system, transport
        self.history = [{"role": "user", "content": prompt}]

    def step(self, max_tokens: int, timeout: float) -> Turn:
        body = {
            "model": self.model, "instructions": self.system, "input": self.history,
            "tools": [{"type": "function", "strict": True, **TOOL}],
            "store": False, "include": ["reasoning.encrypted_content"],
            "max_output_tokens": max_tokens,
        }
        raw = self.transport("https://api.openai.com/v1/responses",
                             {"Authorization": f"Bearer {self.key}"}, body, timeout)
        output = raw.get("output", [])
        self.history.extend(output)  # Preserve reasoning items, including opaque encrypted state.
        calls, text = [], []
        for item in output:
            if item.get("type") == "function_call":
                try:
                    arguments = json.loads(item.get("arguments", "{}"))
                except ValueError:
                    arguments = None
                calls.append({"id": item["call_id"], "name": item["name"], "arguments": arguments})
            elif item.get("type") == "message":
                for part in item.get("content", []):
                    if part.get("type") == "output_text":
                        text.append(part["text"])
                    elif part.get("type") == "refusal":
                        text.append(part["refusal"])
        usage = raw.get("usage", {})
        return Turn(raw, "\n".join(text), calls,
                    {"input_tokens": usage.get("input_tokens", 0), "output_tokens": usage.get("output_tokens", 0)},
                    raw.get("status", "completed"))

    def results(self, results: list[tuple[dict, dict]]) -> None:
        for call, result in results:
            self.history.append({"type": "function_call_output", "call_id": call["id"],
                                 "output": json.dumps(result, ensure_ascii=False)})


class Anthropic:
    def __init__(self, model: str, system: str, prompt: str, transport=post_json):
        self.key = os.environ.get("ANTHROPIC_API_KEY")
        if not self.key:
            raise ValueError("Set ANTHROPIC_API_KEY in the process environment before running Claude experiments.")
        self.model, self.system, self.transport = model, system, transport
        self.history = [{"role": "user", "content": prompt}]

    def step(self, max_tokens: int, timeout: float) -> Turn:
        body = {"model": self.model, "system": self.system, "messages": self.history,
                "max_tokens": max_tokens,
                "tools": [{"name": TOOL["name"], "description": TOOL["description"], "input_schema": TOOL["parameters"]}]}
        raw = self.transport("https://api.anthropic.com/v1/messages",
                             {"x-api-key": self.key, "anthropic-version": "2023-06-01"}, body, timeout)
        content = raw.get("content", [])
        self.history.append({"role": "assistant", "content": content})
        calls = [{"id": b["id"], "name": b["name"], "arguments": b["input"]}
                 for b in content if b.get("type") == "tool_use"]
        text = "\n".join(b["text"] for b in content if b.get("type") == "text")
        usage = raw.get("usage", {})
        inputs = sum(usage.get(k, 0) for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
        stop = raw.get("stop_reason")
        status = "completed" if stop in ("end_turn", "tool_use", "stop_sequence") else str(stop)
        return Turn(raw, text, calls, {"input_tokens": inputs, "output_tokens": usage.get("output_tokens", 0)}, status)

    def results(self, results: list[tuple[dict, dict]]) -> None:
        self.history.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": call["id"],
             "content": json.dumps(result, ensure_ascii=False), "is_error": "error" in result}
            for call, result in results
        ]})


class Scripted:
    """Exercises the real local retrieval loop; NEVER a model or an eval result."""
    def __init__(self, urls: list[str]):
        self.urls, self.done, self.received = urls, False, []

    def step(self, max_tokens: int, timeout: float) -> Turn:
        if not self.done:
            self.done = True
            calls = [{"id": f"demo-{i}", "name": "open_url", "arguments": {"url": url, "offset": 0}}
                     for i, url in enumerate(self.urls)]
            return Turn({"scripted": True}, calls=calls)
        text = "SCRIPTED DEMONSTRATION — no model was called and no behavior was evaluated.\n\n"
        for _, result in self.received:
            text += result.get("title", "Unavailable page") + "\n"
            if "text" in result:
                # Display actual source excerpts, without inventing answers or awareness.
                import re
                match = re.search(r"^\s*\|\s*incumbent\s*=\s*(.+)$", result["text"], re.I | re.M)
                if match:
                    claim = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]",
                                   lambda m: m.group(2) or m.group(1), match.group(1))
                    text += "Incumbent field: " + claim.strip()
                else:
                    text += "Source excerpt: " + result["text"][:600]
            else:
                text += result.get("message", "Unavailable")
            text += "\n\n"
        return Turn({"scripted": True}, text=text)

    def results(self, results: list[tuple[dict, dict]]) -> None:
        self.received.extend(results)
