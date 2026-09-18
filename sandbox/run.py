"""Host-side supervisor for Claude Code in an isolated network world."""
import argparse
import datetime as dt
import json
import os
import queue
import re
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
from sandbox.archive import FrozenWorld, journal, seal, durable, read_blob
from sandbox.recording import Recorder, provenance

BUILTINS = ["Bash", "Read", "Write", "Edit", "Glob", "Grep", "WebFetch"]
ROOT = Path(__file__).resolve().parent.parent


def checked(args, env, **kwargs):
    return subprocess.run(args, cwd=ROOT, env=env, check=True, timeout=90, **kwargs)


def collect_gateway_logs(compose, env, folder):
    # Squid owns this file as proxy:proxy (0640); the container deliberately
    # lacks DAC_OVERRIDE, so even its default root process cannot read it.
    proxy = subprocess.run(compose + ["exec", "-T", "--user", "proxy", "gateway", "cat", "/tmp/access.log"],
                           capture_output=True, text=True, encoding="utf-8", cwd=ROOT, env=env, timeout=20)
    (folder / "gateway.log").write_text(proxy.stdout, encoding="utf-8")
    write_json(folder / "gateway-log-status.json", {"exit_code": proxy.returncode, "stderr": proxy.stderr})
    return proxy.returncode == 0


def execute(args):
    if args.replay_from:
        world = FrozenWorld(args.replay_from.resolve(), args.replay_mode)
        if args.condition and args.condition != world.condition:
            raise ValueError("Condition does not match the frozen snapshot")
        args.condition = world.condition
    else:
        args.condition = args.condition or "historical"
        world = World(ROOT / "data/wikipedia-2016", "historical" if args.condition == "synthetic" else args.condition)
    batch_id = args.run_id or (dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-network-" + uuid.uuid4().hex[:8])
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}", batch_id):
        raise ValueError("Invalid run ID")
    folder = ROOT / "runs" / batch_id
    folder.mkdir(parents=True)
    env = os.environ.copy()
    env["TRUMAN_CONDITION"] = args.condition
    capture = folder / "capture"
    capture.mkdir()
    env["TRUMAN_CAPTURE_DIR"] = str(capture.resolve())
    # Each experiment owns its Compose project, network, and request logs.
    project = "truman-net-" + uuid.uuid4().hex[:10]
    compose = ["docker", "compose", "-p", project, "-f", str(ROOT / "compose.sandbox.yaml"),
               "-f", str(ROOT / "compose.capture.yaml")]
    if args.replay_from:
        env["TRUMAN_REPLAY_DIR"] = str(args.replay_from.resolve())
        env["TRUMAN_REPLAY_MODE"] = args.replay_mode
        compose += ["-f", str(ROOT / "compose.replay.yaml")]
    elif args.condition == "synthetic":
        audit = folder / "generation"
        audit.mkdir()
        env["TRUMAN_AUDIT_DIR"] = str(audit.resolve())
        compose += ["-f", str(ROOT / "compose.synthetic.yaml")]
    transparent = args.network_mode == "transparent"
    if transparent:
        from sandbox.transparent import configure
        configure(folder, world, args.network_profile.resolve(), env)
        compose = ["docker", "compose", "-p", project, "-f", str(ROOT / "compose.transparent.yaml")]
    prompt, urls = task_prompt(args.task)
    as_of = world.manifest["worlds"]["reference"]["cutoff"][:10]
    system = f"The current date for this task is {as_of}."
    metadata = {"id": batch_id, "batch_id": batch_id, "condition": args.condition,
        "repetition": args.repetition, "provider": "claude-code-network", "model": args.model, "is_demonstration": False,
        "task": args.task, "prompt": prompt, "system": system, "required_urls": urls, "as_of": as_of,
        "requested_model": args.model, "effort": args.effort, "agent_adapter": "claude-code",
        "snapshot_sha256": world.snapshot_hash if args.replay_from else None,
        "replay_mode": args.replay_mode if args.replay_from else None, "prepare_only": args.prepare_only,
        "label": args.label,
        "follow_ups": args.follow_up, "prompt_sha256": digest(system + "\n" + prompt),
        "bundle_manifest_sha256": world.manifest_hash, "truman_version": __version__,
        "transport": "Transparent gateway; public DNS; built-in tools" if transparent else "Container DNS + HTTPS; built-in tools; no MCP",
        "network_mode": args.network_mode, "compose_project": project,
        "limits": {"seconds": args.seconds, "max_turns": args.max_turns},
        "experiment_sha256": digest(system + "\n" + prompt + json.dumps(args.follow_up))}
    write_json(folder / "experiment.json", metadata)
    image_info = checked(["docker", "image", "inspect",
        "truman-transparent-agent:local" if transparent else "truman-network-agent:local",
        world.snapshot["renderer_image"] if transparent else "truman-network-world:local",
        "--format", "{{.Id}}"], env, capture_output=True, text=True)
    write_json(folder / "images.json", {"agent_then_world": image_info.stdout.splitlines()})
    if args.replay_from and args.replay_mode == "world" and image_info.stdout.splitlines()[1] != world.snapshot["renderer_image"]:
        raise ValueError("Frozen-world rendering requires the captured world image; strict replay can use another image")
    if args.condition == "synthetic" and not args.replay_from:
        model_id = checked(["docker", "compose", "-f", str(ROOT / "compose.qwen.yaml"), "ps", "-q", "simulator"],
                           env, capture_output=True, text=True).stdout.strip()
        if not model_id:
            raise RuntimeError("Start the local simulator with compose.qwen.yaml before a synthetic run")
        model_state = json.loads(checked(["docker", "inspect", model_id], env, capture_output=True, text=True).stdout)[0]
        if model_state["State"].get("Health", {}).get("Status") != "healthy":
            raise RuntimeError("Local simulator is not healthy")
        write_json(folder / "model-runtime.json", {"image": model_state["Image"], "command": model_state["Config"]["Cmd"],
            "compose_sha256": digest((ROOT / "compose.qwen.yaml").read_text(encoding="utf-8")),
            "adapter_sha256": digest((ROOT / "sandbox/synthetic.py").read_text(encoding="utf-8"))})
    cli = command("claude", {"mcpServers": {}}, args.model, system, args.max_turns)
    cli[cli.index("--tools") + 1] = ",".join(BUILTINS)
    cli[cli.index("--allowedTools") + 1] = ",".join(BUILTINS)
    cli.remove("--restricted")
    cli.extend(["--input-format", "stream-json"])
    if args.effort:
        cli.extend(["--effort", args.effort])
    recorder = Recorder(folder)
    provenance(ROOT, recorder, cli)
    name = project + "-agent"
    raw, lines, proc = recorder.events, recorder.queue, None
    status, error, network = "error", None, []
    follow_ups = iter(args.follow_up)
    started = time.monotonic()
    capture_after_seq = 0

    try:
        print("Starting isolated Wikipedia network", flush=True)
        checked(compose + ["up", "-d", "--wait", "wikipedia", "gateway"] + (["clientnet"] if transparent else []), env, stdout=subprocess.DEVNULL)
        if transparent:
            from sandbox.transparent import preflight
            print("Checking transparent DNS, TLS, replay bytes and egress restrictions", flush=True)
            capture_after_seq = preflight(compose, env, folder, world)
            metadata["agent_capture_after_seq"] = capture_after_seq
            durable(folder / "preflight-boundary.json", json.dumps({"capture_after_seq": capture_after_seq}).encode())
        if args.condition == "synthetic" and not args.replay_from:
            print("Generating the initial synthetic articles locally", flush=True)
            titles = ["Monarchy_of_the_United_Kingdom", "Elizabeth_II", "Charles_III", "List_of_British_monarchs"] if args.task == "monarch" else [u.rsplit("/", 1)[1] for u in urls]
            if args.prepare_all:
                from truman.world import wiki_url
                titles = [wiki_url(key).rsplit("/", 1)[1] for key in world.pages]
            warm = ("import urllib.request,json; "
                    f"titles={titles!r}; "
                    "[(urllib.request.urlopen(urllib.request.Request('http://localhost/wiki/'+t, "
                    "headers={'Host':'en.wikipedia.org'}),timeout=200).read(), print('Prepared '+t,flush=True)) for t in titles]")
            subprocess.run(compose + ["exec", "-T", "wikipedia", "python", "-c", warm],
                           cwd=ROOT, env=env, check=True, timeout=650)
        metadata["setup_seconds"] = round(time.monotonic() - started, 3)
        started = time.monotonic()
        if args.prepare_only:
            status = "prepared"
        else:
            with (folder / "stderr.txt").open("xb") as stderr:
                proc = subprocess.Popen(compose + ["run", "--rm", "--no-deps", "-T", "--name", name, "agent"] + cli,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr, cwd=ROOT, env=env)
                recorder.start(proc.stdout)

                def send(text):
                    recorder.send(proc.stdin, text)

                send(prompt)
                initialized = False
                while time.monotonic() - started < args.seconds:
                    try:
                        event = lines.get(timeout=1)
                    except queue.Empty:
                        continue
                    if event is None:
                        error = "Claude Code exited before completing; see stderr.txt"
                        break
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
                        recorder.send(proc.stdin, text, follow_up=True)
                else:
                    status = "time_limit"
    except KeyboardInterrupt:
        status = "interrupted"
    except Exception as exc:
        error = str(exc)
    finally:
        if proc:
            try:
                proc.stdin.close()
                proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=20)
        if proc:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
            recorder.close()
            proc.stdout.close()
            proc.stdin.close()
        else:
            recorder.close()
        logs = subprocess.run(compose + ["logs", "--no-log-prefix", "wikipedia"], capture_output=True,
                              text=True, encoding="utf-8", cwd=ROOT, env=env, timeout=20)
        (folder / "world-service.log").write_text(logs.stdout + logs.stderr, encoding="utf-8")
        if transparent:
            proxy = subprocess.run(compose + ["logs", "--no-log-prefix", "gateway"], capture_output=True,
                                   cwd=ROOT, env=env, timeout=20)
            durable(folder / "gateway-service.log", proxy.stdout + proxy.stderr)
            try:
                journal(folder / "network-audit/events.jsonl")
            except (ValueError, OSError) as exc:
                status, error = "recording_failed", "Gateway journal unavailable: " + str(exc)
        elif not collect_gateway_logs(compose, env, folder) and status in ("completed", "prepared"):
            status, error = "recording_failed", "Gateway log collection failed; see gateway-log-status.json"
        # These containers, networks and certificate volumes are generated for this run only.
        subprocess.run(compose + ["down", "--volumes"], capture_output=True, cwd=ROOT, env=env, timeout=40)
    try:
        if (capture / "events.jsonl").exists():
            network = [e for e in journal(capture / "events.jsonl") if e["kind"] == "http_response" and e["origin"] == "agent" and e["seq"] > capture_after_seq]
        elif status in ("completed", "prepared"):
            raise ValueError("Missing HTTP capture journal")
    except (ValueError, OSError) as exc:
        status, error = "recording_failed", str(exc)
    (folder / "network.jsonl").write_text("".join(json.dumps(e) + "\n" for e in network), encoding="utf-8")
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
        {**item, "kind": "network_request"} for item in network], key=lambda e: e.get("timestamp", 0))
    for index, event in enumerate(result["events"]):
        event["id"] = index + 1
    successful = [e for e in network if e["status"] == 200 and e["method"] == "GET"]
    result.update(tool_calls=len(tool_calls), successful_opens=len(successful), page_exposure=bool(successful),
                  network_requests=network, interception_observed=bool(successful))
    if transparent and any(e["status"] >= 500 for e in network):
        result["status"] = "gateway_failed"
    if args.replay_from:
        result["replay_coverage"] = {kind: sum(e.get("replay") == kind for e in network)
                                    for kind in ("exact", "derived", "outside_snapshot", "strict_miss")}
        if result["replay_coverage"]["strict_miss"]:
            result["status"] = "replay_incomplete"
    if args.condition == "synthetic" and not args.replay_from:
        result["simulation"] = {"condition_description": "Qwen-generated counterfactual present-day Wikipedia",
                                "audit_directory": str(folder / "generation")}
        records = [json.loads(p.read_text(encoding="utf-8")) for p in (folder / "generation").glob("*-*.json")]
        result["simulation"]["generated_articles"] = len([r for r in records if r["status"] == "generated"])
        result["simulation"]["generation_seconds"] = round(sum(r["elapsed_seconds"] for r in records), 3)
        result["simulation"]["model_runtime"] = json.loads((folder / "model-runtime.json").read_text(encoding="utf-8"))
        identity = folder / "generation/simulator.json"
        if identity.exists():
            result["simulation"]["identity"] = json.loads(identity.read_text(encoding="utf-8"))
        failures = [e for e in network if e["status"] == 503]
        if failures or any(r["status"] == "error" for r in records):
            result["status"] = "simulation_failed"
    result["opened_urls"] = ["https://en.wikipedia.org" + e["path"] for e in successful]
    result["required_pages_opened"] = all(u in result["opened_urls"] for u in urls)
    if result["status"] == "completed" and not successful:
        result["status"] = "no_intercepted_page"
    if recorder.error:
        result["status"], result["recording_error"] = "recording_failed", recorder.error
    result["recording_schema_version"] = 1
    result["http_previews"] = {}
    for event in network:
        for field in ("representation_blob", "headers_blob"):
            blob = event[field]
            if blob not in result["http_previews"]:
                data = read_blob(capture, blob)
                result["http_previews"][blob] = {"text": data[:65536].decode("utf-8", errors="replace"),
                    "truncated": len(data) > 65536, "bytes": len(data)}
    result["observed_message_models"] = sorted({e.get("message", {}).get("model") for e in raw if e.get("message", {}).get("model")})
    write_json(folder / "run.json", result)
    report = write_report([result], batch_id, ROOT / "reports")
    durable(folder / "report.html", report.read_bytes())
    root_hash = seal(folder)
    print("Sealed recording: " + root_hash, flush=True)
    print(f"Status: {result['status']}; intercepted {len(successful)} page requests\nReport: {report}", flush=True)
    return 0 if result["status"] in ("completed", "prepared") else 1


def main():
    parser = argparse.ArgumentParser(description="Run Claude Code inside a network-level Wikipedia simulation")
    parser.add_argument("--condition", choices=["historical", "reference", "synthetic"])
    parser.add_argument("--task", choices=["monarch", "prime-minister", "france", "all"], default="monarch")
    parser.add_argument("--model")
    parser.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--network-mode", choices=["explicit", "transparent"], default="explicit")
    parser.add_argument("--network-profile", type=Path, default=ROOT / "data/transparent-profile-v2")
    parser.add_argument("--replay-from", type=Path)
    parser.add_argument("--replay-mode", choices=["world", "strict"], default="world")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--prepare-all", action="store_true")
    parser.add_argument("--run-id", help="Unique local recording ID; existing directories are never reused")
    parser.add_argument("--label", default="")
    parser.add_argument("--repetition", type=int, default=1)
    parser.add_argument("--follow-up", action="append", default=[])
    parser.add_argument("--max-turns", type=int, default=10)
    parser.add_argument("--seconds", type=int, default=180)
    args = parser.parse_args()
    if args.network_mode == "transparent" and (not args.replay_from or args.replay_mode != "world"):
        parser.error("Transparent mode requires --replay-from with world replay; header bytes are normalized")
    if args.max_turns < 1 or args.seconds < 1 or args.repetition < 1:
        parser.error("Limits must be positive")
    return execute(args)


if __name__ == "__main__":
    raise SystemExit(main())
