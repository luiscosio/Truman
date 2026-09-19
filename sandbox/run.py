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
from sandbox.archive import FrozenWorld, journal, seal, durable, read_blob, encoded
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


def attach_world_outcomes(result,root,previous,queue=None):
    """Include host generation failures even when the client stopped waiting."""
    outcomes=[]
    for attempt in sorted((Path(root)/'attempts').iterdir()):
        if attempt.name in previous:continue
        context=json.loads((attempt/'context.json').read_bytes()) if (attempt/'context.json').exists() else {}
        failure=json.loads((attempt/'failure.json').read_bytes()) if (attempt/'failure.json').exists() else None
        outcome={'attempt':attempt.name,'title':context.get('title'),
                 'status':'failed' if failure else 'incomplete' if not (attempt/'seal.json').exists() else 'completed'}
        if failure:outcome['error']=failure.get('error','Generation failed')
        outcomes.append(outcome)
    result['world_generation']=outcomes
    requests=[]
    if queue is not None:
        for path in sorted(Path(queue).glob('*.request.json')):
            request=json.loads(path.read_bytes())
            response=path.with_name(path.name.replace('.request.json','.response.json'))
            value=json.loads(response.read_bytes()) if response.exists() else {}
            requests.append({'path':request['path'],'status':value.get('status'),
                             'coverage':value.get('coverage','incomplete')})
        result['world_requests']=requests
    if any(o['status']!='completed' for o in outcomes) or any(r['coverage'] in ('incomplete','generation_failed') for r in requests):
        if result['status']=='completed':result['status']='generation_failed'
    return result


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
    if getattr(args, "resolved_scenario", None):
        env["TRUMAN_SCENARIO_JSON"] = json.dumps(args.resolved_scenario)
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
    transparent = args.network_mode in ("transparent", "managed")
    if transparent:
        from sandbox.transparent import configure
        configure(folder, world, args.network_profile.resolve(), env)
        compose = ["docker", "compose", "-p", project, "-f", str(ROOT / "compose.transparent.yaml")]
        profile_engine = json.loads((folder / "network-profile.json").read_bytes()).get("engine", "transparent")
        if profile_engine != args.network_mode:
            raise ValueError("Network mode does not match the sealed profile")
        if args.network_mode == "managed":
            compose += ["-f", str(ROOT / "compose.managed.yaml")]
    demand_worker = None
    world_attempts_before=set()
    if getattr(args,'world_service',None):
        world_attempts_before={p.name for p in (args.world_service.root/'attempts').iterdir()}
        durable(folder/'world-before.json',encoded({'attempts':sorted(world_attempts_before)}))
        queue_path=folder/'world-queue'
        bridge_path=folder/'demand-bridge.py'
        durable(bridge_path,(ROOT/'sandbox/demand_bridge.py').read_bytes())
        env['TRUMAN_WORLD_BRIDGE']=str(bridge_path.resolve())
        env['TRUMAN_WORLD_QUEUE']=str(queue_path.resolve())
        compose += ['-f',str(ROOT/'compose.demand.yaml')]
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
        "generator": getattr(args, "resolved_generator", None),
        "world_mode": ('replay' if args.world_service.readonly else 'exploration') if getattr(args,'world_service',None) else None,
        "scenario_sha256": digest(json.dumps(args.resolved_scenario, sort_keys=True)) if getattr(args, "resolved_scenario", None) else None,
        "follow_ups": args.follow_up, "prompt_sha256": digest(system + "\n" + prompt),
        "bundle_manifest_sha256": world.manifest_hash, "truman_version": __version__,
        "transport": "Transparent gateway; public DNS; built-in tools" if transparent else "Container DNS + HTTPS; built-in tools; no MCP",
        "network_mode": args.network_mode, "compose_project": project,
        "limits": {"seconds": args.seconds, "max_turns": args.max_turns},
        "experiment_sha256": digest(system + "\n" + prompt + json.dumps(args.follow_up))}
    if args.network_mode == "managed":
        metadata["site_policy"] = json.loads((folder / "effective-sites.json").read_bytes())
        metadata["transport"] = "Managed gateway; mitmproxy; pinned website DNS; built-in tools"
    write_json(folder / "experiment.json", metadata)
    if getattr(args, "resolved_scenario", None):
        write_json(folder / "scenario.json", args.resolved_scenario)
    image_info = checked(["docker", "image", "inspect",
        env["TRUMAN_AGENT_IMAGE"] if transparent else "truman-network-agent:local",
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
        if getattr(args,'world_service',None):
            from sandbox.demand_bridge import Worker
            demand_worker=Worker(args.world_service,queue_path)
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
                            status = "claude_error" if event.get("is_error") else "claude_" + str(event.get("subtype", "error"))
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
        if demand_worker:
            demand_worker.close()
            frozen_seal=args.world_service.freeze(folder/'world-snapshot')
            durable(folder/'world-state.json',encoded({'world':str(args.world_service.root),
                'facts':args.world_service.facts(),'world_snapshot_seal':frozen_seal,
                'mode':'replay' if args.world_service.readonly else 'exploration'}))
    try:
        if (capture / "events.jsonl").exists():
            captured = journal(capture / "events.jsonl")
            network = [e for e in captured if e["kind"] == "http_response" and e["origin"] == "agent" and e["seq"] > capture_after_seq]
            if any(e["kind"] in ("proxy_error", "origin_error") and e["seq"] > capture_after_seq for e in captured):
                status, error = "gateway_failed", "Proxy or origin error recorded"
        elif status in ("completed", "prepared"):
            raise ValueError("Missing HTTP capture journal")
    except (ValueError, OSError) as exc:
        status, error = "recording_failed", str(exc)
    (folder / "network.jsonl").write_text("".join(json.dumps(e) + "\n" for e in network), encoding="utf-8")
    result = convert_events(raw, [], metadata, status, time.monotonic() - started, error)
    result['agent_status']=result['status']
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
                                    for kind in ("exact", "derived", "outside_snapshot", "strict_miss", "world_missing", "generation_failed")}
        if result["replay_coverage"]["strict_miss"]:
            result["status"] = "replay_incomplete"
        if world.snapshot.get("presentation") in ("captured-html-v1", "on-demand-v1") and result["replay_coverage"]["outside_snapshot"]:
            result["status"] = "coverage_incomplete"
        if result['replay_coverage']['generation_failed']:
            result['status']='generation_failed'
    if getattr(args,'world_service',None):
        attach_world_outcomes(result,args.world_service.root,world_attempts_before,folder/'world-queue')
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
    parser.add_argument("--generator", choices=["a", "b", "generate", "rewrite"])
    parser.add_argument("--scenario", type=Path)
    parser.add_argument("--originals", type=Path, help="Sealed original-HTML source bundle for generator B")
    parser.add_argument('--world',type=Path,help='Persistent on-demand world or frozen world export')
    parser.add_argument("--task", choices=["monarch", "prime-minister", "france", "all"], default="monarch")
    parser.add_argument("--model")
    parser.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--network-mode", choices=["explicit", "transparent", "managed"], default="explicit")
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
    from sandbox.generators import select, scenario_file
    args.resolved_scenario = scenario_file(args.scenario) if args.scenario else None
    args.world_service=None
    if args.world:
        if args.replay_from or args.originals or args.scenario or args.generator not in (None,'b','rewrite') or args.condition not in (None,'synthetic'):
            parser.error('--world supplies its own scenario, generator and state; do not combine with source/replay options')
        if args.network_mode!='managed':parser.error('On-demand worlds require the managed network')
        from sandbox.demand import WorldService
        args.world_service=WorldService(args.world)
        name=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-world-context-'+uuid.uuid4().hex[:8]
        args.replay_from=args.world_service.bootstrap(ROOT/'data/worlds'/name)
    if args.replay_from:
        from sandbox.archive import load_snapshot
        snapshot, _ = load_snapshot(args.replay_from)
        args.resolved_generator = select(args.generator, args.resolved_scenario, snapshot, args.condition)
        if args.resolved_scenario and snapshot.get("generator", {}).get("scenario_sha256") != __import__('hashlib').sha256(encoded(args.resolved_scenario)).hexdigest():
            parser.error("Scenario conflicts with frozen snapshot")
        if args.originals:
            parser.error("Replay already contains its captured source identity")
    else:
        if args.generator or args.scenario:
            args.condition = args.condition or 'synthetic'
        args.resolved_generator = select(args.generator, args.resolved_scenario, condition=args.condition)
        if args.resolved_generator == 'b':
            if not args.scenario or not args.originals:
                parser.error("Generator B requires --scenario and --originals; capture originals with sandbox.rewrite_capture first")
            from sandbox.rewrite import prepare
            name = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-rewrite-' + uuid.uuid4().hex[:8]
            args.replay_from = prepare(args.originals, args.resolved_scenario, ROOT/'data/worlds'/name)
        elif args.originals:
            parser.error("--originals applies only to generator B")
    if args.network_mode in ("transparent", "managed") and (not args.replay_from or args.replay_mode != "world"):
        parser.error("Transparent mode requires --replay-from with world replay; header bytes are normalized")
    if args.max_turns < 1 or args.seconds < 1 or args.repetition < 1:
        parser.error("Limits must be positive")
    try:return execute(args)
    finally:
        if args.world_service:args.world_service.close()


if __name__ == "__main__":
    raise SystemExit(main())
