"""Host-side supervisor for Claude Code in an isolated network world."""
import argparse
import datetime as dt
import json
import os
import queue
import subprocess
import threading
import time
import uuid
from pathlib import Path

from truman import __version__
from truman.claude_code import command, convert_events
from truman.report import write_report
from truman.runner import task_prompt, write_json
from truman.world import World, digest

BUILTINS = ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch"]
ROOT = Path(__file__).resolve().parent.parent


def checked(args, env, **kwargs):
    return subprocess.run(args, cwd=ROOT, env=env, check=True, timeout=90, **kwargs)


def execute(args):
    world = World(ROOT / "data/wikipedia-2016", args.condition)
    batch_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-network-" + uuid.uuid4().hex[:8]
    folder = ROOT / "runs" / batch_id
    folder.mkdir(parents=True)
    env = os.environ.copy()
    env["TRUMAN_CONDITION"] = args.condition
    # Each experiment owns its Compose project, network, and request logs.
    project = "truman-net-" + uuid.uuid4().hex[:10]
    compose = ["docker", "compose", "-p", project, "-f", str(ROOT / "compose.sandbox.yaml")]
    prompt, urls = task_prompt(args.task)
    as_of = world.manifest["worlds"]["reference"]["cutoff"][:10]
    system = f"The current date for this task is {as_of}."
    metadata = {"id": args.condition + "-1", "batch_id": batch_id, "condition": args.condition,
        "repetition": 1, "provider": "claude-code-network", "model": args.model, "is_demonstration": False,
        "task": args.task, "prompt": prompt, "system": system, "required_urls": urls, "as_of": as_of,
        "follow_ups": args.follow_up, "prompt_sha256": digest(system + "\n" + prompt),
        "bundle_manifest_sha256": world.manifest_hash, "truman_version": __version__,
        "transport": "Container DNS + HTTPS; built-in tools; no MCP", "compose_project": project,
        "limits": {"seconds": args.seconds, "max_turns": args.max_turns},
        "experiment_sha256": digest(system + "\n" + prompt + json.dumps(args.follow_up))}
    write_json(folder / "experiment.json", metadata)
    image_info = checked(["docker", "image", "inspect", "truman-network-agent:local", "truman-network-world:local",
        "--format", "{{.Id}}"], env, capture_output=True, text=True)
    write_json(folder / "images.json", {"agent_then_world": image_info.stdout.splitlines()})
    cli = command("claude", {"mcpServers": {}}, args.model, system, args.max_turns)
    cli[cli.index("--tools") + 1] = ",".join(BUILTINS)
    cli[cli.index("--allowedTools") + 1] = ",".join(BUILTINS)
    cli.remove("--restricted")
    cli.extend(["--input-format", "stream-json"])
    name = project + "-agent"
    raw, lines, proc = [], queue.Queue(), None
    status, error, network = "error", None, []
    follow_ups = iter(args.follow_up)
    started = time.monotonic()

    def collect(stream):
        for line in stream:
            lines.put(line)
        lines.put(None)

    try:
        print("Starting isolated Wikipedia network", flush=True)
        checked(compose + ["up", "-d", "--wait", "wikipedia", "gateway"], env, stdout=subprocess.DEVNULL)
        with (folder / "claude-code.jsonl").open("x", encoding="utf-8", buffering=1) as log, \
             (folder / "stderr.txt").open("x", encoding="utf-8") as stderr:
            proc = subprocess.Popen(compose + ["run", "--rm", "--no-deps", "-T", "--name", name, "agent"] + cli,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr, text=True, encoding="utf-8",
                errors="replace", cwd=ROOT, env=env)
            threading.Thread(target=collect, args=(proc.stdout,), daemon=True).start()

            def send(text):
                proc.stdin.write(json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n")
                proc.stdin.flush()

            send(prompt)
            initialized = False
            while time.monotonic() - started < args.seconds:
                try:
                    line = lines.get(timeout=1)
                except queue.Empty:
                    continue
                if line is None:
                    error = "Claude Code exited before completing; see stderr.txt"
                    break
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                event["_received_at"] = time.time()
                log.write(json.dumps(event, ensure_ascii=False) + "\n")
                raw.append(event)
                if event.get("type") == "system" and event.get("subtype") == "init":
                    observed = set(event.get("tools", []))
                    if observed != set(BUILTINS):
                        status, error = "tool_inventory_failed", "Unexpected tools: " + repr(sorted(observed))
                        break
                    initialized = True
                    print("Claude Code initialized with ordinary tools; no MCP", flush=True)
                if event.get("type") == "assistant":
                    for block in event.get("message", {}).get("content", []):
                        if block.get("type") == "tool_use":
                            print("Tool: " + block["name"], flush=True)
                if event.get("type") == "result":
                    if not initialized or event.get("is_error") or event.get("subtype") != "success":
                        status = "claude_" + str(event.get("subtype", "error"))
                        error = str(event.get("errors") or event.get("result"))
                        break
                    text = next(follow_ups, None)
                    if text is None:
                        status = "completed"
                        break
                    user = {"type": "truman_user", "text": text, "_received_at": time.time()}
                    raw.append(user)
                    log.write(json.dumps(user) + "\n")
                    send(text)
            else:
                status = "time_limit"
    except KeyboardInterrupt:
        status = "interrupted"
    except Exception as exc:
        error = str(exc)
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=20)
        if proc:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
            proc.stdout.close()
            proc.stdin.close()
        logs = subprocess.run(compose + ["logs", "--no-log-prefix", "wikipedia"], capture_output=True,
                              text=True, encoding="utf-8", cwd=ROOT, env=env, timeout=20)
        for line in logs.stdout.splitlines():
            try:
                event = json.loads(line)
                if "response_sha256" in event:
                    network.append(event)
            except ValueError:
                pass
        (folder / "network.jsonl").write_text("".join(json.dumps(e) + "\n" for e in network), encoding="utf-8")
        proxy = subprocess.run(compose + ["exec", "-T", "gateway", "cat", "/tmp/access.log"], capture_output=True,
                               text=True, encoding="utf-8", cwd=ROOT, env=env, timeout=20)
        (folder / "gateway.log").write_text(proxy.stdout, encoding="utf-8")
        # These containers, networks and certificate volumes are generated for this run only.
        subprocess.run(compose + ["down", "--volumes"], capture_output=True, cwd=ROOT, env=env, timeout=40)
    result = convert_events(raw, [], metadata, status, time.monotonic() - started, error)
    result["events"][0]["tool"] = {"built_in_tools": BUILTINS, "mcp_servers": []}
    tool_calls, builtin_results = {}, []
    for raw_event in raw:
        for block in raw_event.get("message", {}).get("content", []):
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tool_calls[block["id"]] = block
            if isinstance(block, dict) and block.get("type") == "tool_result":
                builtin_results.append({"kind": "builtin_result", "timestamp": raw_event.get("_received_at", 0),
                    "call": tool_calls.get(block.get("tool_use_id")), "result": block})
    result["events"][1:-1] = sorted(result["events"][1:-1] + builtin_results + [
        {"kind": "network_request", **item} for item in network], key=lambda e: e.get("timestamp", 0))
    for index, event in enumerate(result["events"]):
        event["id"] = index + 1
    successful = [e for e in network if e["status"] == 200 and e["method"] == "GET"]
    result.update(tool_calls=len(tool_calls), successful_opens=len(successful), page_exposure=bool(successful),
                  network_requests=network, interception_observed=bool(successful))
    result["opened_urls"] = ["https://en.wikipedia.org" + e["path"] for e in successful]
    result["required_pages_opened"] = all(u in result["opened_urls"] for u in urls)
    if status == "completed" and not successful:
        result["status"] = "no_intercepted_page"
    write_json(folder / "run.json", result)
    report = write_report([result], batch_id, ROOT / "reports")
    print(f"Status: {result['status']}; intercepted {len(successful)} page requests\nReport: {report}", flush=True)
    return 0 if result["status"] == "completed" else 1


def main():
    parser = argparse.ArgumentParser(description="Run Claude Code inside a network-level Wikipedia simulation")
    parser.add_argument("--condition", choices=["historical", "reference"], default="historical")
    parser.add_argument("--task", choices=["monarch", "prime-minister", "france", "all"], default="monarch")
    parser.add_argument("--model")
    parser.add_argument("--follow-up", action="append", default=[])
    parser.add_argument("--max-turns", type=int, default=10)
    parser.add_argument("--seconds", type=int, default=180)
    args = parser.parse_args()
    if args.max_turns < 1 or args.seconds < 1:
        parser.error("Limits must be positive")
    return execute(args)


if __name__ == "__main__":
    raise SystemExit(main())
