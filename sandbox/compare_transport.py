"""Audit two completed suites and render a four-trace transport comparison."""
import argparse
import datetime as dt
import json
import uuid
from pathlib import Path

from sandbox.archive import FrozenWorld, durable, encoded, journal, seal, verify
from sandbox.suite import compare_runs
from truman.report import write_report

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--explicit-suite", type=Path, required=True)
    parser.add_argument("--transparent-suite", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    world = FrozenWorld(args.snapshot, "world")
    controls = ("snapshot_sha256", "experiment_sha256", "observed_tools", "limits", "agent_adapter")
    groups, source_seals, validations, shared_bodies = [], {}, [], {}
    for mode, suite in (("explicit", args.explicit_suite), ("transparent", args.transparent_suite)):
        source_seals[suite.name] = verify(suite)
        cases = json.loads((suite / "cases.json").read_bytes())
        paths = [suite.parent / case["run"] for case in cases]
        results = compare_runs(paths)
        for path, result in zip(paths, results):
            assert result.get("network_mode", "explicit") == mode
            assert result["snapshot_sha256"] == world.snapshot_hash
            source_seals[path.name] = verify(path)
            entries = journal(path / "capture/events.jsonl")
            delivered = {e["request_id"]: e["outcome"] for e in entries if e["kind"] == "http_delivery"}
            exact = 0
            for event in result["network_requests"]:
                assert delivered[event["request_id"]] == "write_completed"
                if event["replay"] == "exact":
                    route = world.lookup(event["method"], event["host"], event["path"])
                    assert route is not None
                    assert event["body_blob"] == route["body_blob"]
                    assert event["representation_blob"] == route["representation_blob"]
                    exact += 1
                if event["status"] == 200 and event["method"] == "GET" and event["path"].startswith("/wiki/"):
                    key = event["host"] + event["path"]
                    shared_bodies.setdefault(key, {}).setdefault(mode, set()).add(event["body_blob"])
            assert not (path / "generation").exists()
            if mode == "transparent":
                journal(path / "network-audit/events.jsonl")
                journal(path / "origin-capture/events.jsonl")
                preflight = json.loads((path / "preflight.json").read_bytes())
                assert not preflight["environment_clues"] and preflight["capabilities"] == 0
                assert preflight["origin_direct_access_blocked"] and preflight["unknown_tls_blocked"]
            validations.append({"run": path.name, "mode": mode, "exact_bodies_verified": exact,
                                "responses_with_completed_write": len(result["network_requests"])})
            result["label"] = f"{mode.capitalize()} network / {result['effort']} effort"
        groups.append((paths, results))
    left, right = groups[0][1], groups[1][1]
    assert len(left) == len(right)
    for old_path, new_path, old, new in zip(groups[0][0], groups[1][0], left, right):
        for key in controls + ("effort", "requested_model", "repetition"):
            assert old.get(key) == new.get(key), key
        old_images = json.loads((old_path / "images.json").read_bytes())["agent_then_world"]
        new_images = json.loads((new_path / "images.json").read_bytes())["agent_then_world"]
        profile = json.loads((new_path / "network-profile.json").read_bytes())
        assert profile["base_agent_image"] == old_images[0]
        assert old_images[1] == new_images[1] == world.snapshot["renderer_image"]
    shared = {url: list(next(iter(values.values())))[0] for url, values in shared_bodies.items()
              if set(values) == {"explicit", "transparent"}}
    for url in shared:
        assert len(set.union(*shared_bodies[url].values())) == 1, url
    identifier = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-transport-comparison-" + uuid.uuid4().hex[:8]
    folder = ROOT / "runs" / identifier
    folder.mkdir()
    results = left + right
    report = write_report(results, identifier, ROOT / "reports")
    durable(folder / "report.html", report.read_bytes())
    durable(folder / "comparison.json", encoded({"results": results, "source_seals": source_seals}))
    durable(folder / "validation.json", encoded({"snapshot_sha256": world.snapshot_hash,
        "controls_checked": list(controls), "responses": validations, "shared_article_bodies": shared,
        "limitations": "Observational comparison, one run per effort/transport; inference and execution time differ. "
                       "Agent image differs by system CA and entrypoint; gateway changes DNS, routing and headers. "
                       "Old proxy connection metadata was not collected successfully. WebFetch may summarize content."}))
    durable(folder / "validator.py", Path(__file__).read_bytes())
    print("Seal: " + seal(folder))
    print("Report: " + str(report))


if __name__ == "__main__":
    main()
