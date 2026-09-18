"""Run authentic/synthetic content controls behind the same managed network."""
import argparse
import datetime as dt
import json
import subprocess
import sys
import uuid
from pathlib import Path

from sandbox.archive import FrozenWorld, durable, encoded, seal, verify
from sandbox.site_policy import effective
from sandbox.suite import compare_runs
from truman.report import write_report

ROOT = Path(__file__).resolve().parent.parent


def compare_conditions(groups, profile):
    results = [compare_runs(group) for group in groups]
    expected_profile = verify(profile)
    policy = json.loads((profile / "sites.json").read_bytes())
    common = ("experiment_sha256", "observed_tools", "limits", "agent_adapter", "network_mode", "observed_message_models")
    first = results[0][0]
    images, gateways = [], []
    for paths, group in zip(groups, results):
        for path, result in zip(paths, group):
            for key in common:
                if result.get(key) != first.get(key):
                    raise ValueError("Control mismatch: " + key)
            network = json.loads((path / "network-profile.json").read_bytes())
            if network["profile_seal"] != expected_profile:
                raise ValueError("Control used a different DNS/trust profile")
            if json.loads((path / "effective-sites.json").read_bytes()) != effective(policy, result["condition"]):
                raise ValueError("Unexpected effective site policy")
            images.append(json.loads((path / "images.json").read_bytes()))
            gateways.append(network["gateway_image"])
    if any(value != images[0] for value in images) or len(set(gateways)) != 1:
        raise ValueError("Control used different agent, renderer or gateway images")
    if len(results[0]) != len(results[1]):
        raise ValueError("Unbalanced conditions")
    for left, right in zip(*results):
        for key in ("effort", "requested_model", "repetition"):
            if left[key] != right[key]:
                raise ValueError("Control mismatch: " + key)
    return results[0] + results[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--altered", type=Path, required=True)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    worlds = [FrozenWorld(args.reference, "world"), FrozenWorld(args.altered, "world")]
    if [w.condition for w in worlds] != ["reference", "synthetic"]:
        parser.error("Expected authentic reference and synthetic worlds")
    if set(worlds[0].pages) != set(worlds[1].pages):
        parser.error("Content controls must cover the same article titles")
    config = json.loads(args.config.read_bytes())
    if not config.get("cases") or len(config["cases"]) > 20:
        parser.error("Supply 1-20 model cases")
    identifier = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-managed-pair-" + uuid.uuid4().hex[:8]
    folder = ROOT / "runs" / identifier
    folder.mkdir()
    durable(folder / "suite.json", encoded({"config": config, "profile_seal": verify(args.profile),
        "reference_snapshot": worlds[0].snapshot_hash, "altered_snapshot": worlds[1].snapshot_hash,
        "limitations": "One run per effort/condition; saved authentic text uses the same simplified renderer and limited coverage. "
                       "The identical follow-up asserts Elizabeth II, including in the authentic condition."}))
    groups, cases = [], []
    try:
        for condition, snapshot in (("reference", args.reference), ("synthetic", args.altered)):
            paths = []
            groups.append(paths)
            for index, case in enumerate(config["cases"], 1):
                run = identifier + f"-{condition}-c{index}"
                command = [sys.executable, "-m", "sandbox.run", "--replay-from", str(snapshot.resolve()),
                    "--network-mode", "managed", "--network-profile", str(args.profile.resolve()), "--run-id", run,
                    "--model", case["model"], "--effort", case["effort"], "--task", config.get("task", "monarch"),
                    "--label", ("Authentic saved text" if condition == "reference" else "Altered text") + " / " + case["effort"],
                    "--seconds", str(config.get("seconds", 360)), "--max-turns", str(config.get("max_turns", 16))]
                for follow in config.get("follow_ups", []):
                    command += ["--follow-up", follow]
                with (folder / f"{condition}-c{index}.log").open("xb") as log:
                    result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                            timeout=int(config.get("seconds", 360)) + 240)
                paths.append(ROOT / "runs" / run)
                cases.append({"run": run, "exit_code": result.returncode})
                print(f"{condition} / {case['effort']}: exit {result.returncode}; {run}", flush=True)
        results = compare_conditions(groups, args.profile)
        report = write_report(results, identifier, ROOT / "reports")
        durable(folder / "report.html", report.read_bytes())
        durable(folder / "comparison.json", encoded({"results": results,
            "source_seals": {p.name: verify(p) for group in groups for p in group}}))
        print("Report: " + str(report), flush=True)
    finally:
        durable(folder / "cases.json", encoded(cases))
        print("Suite seal: " + seal(folder), flush=True)


if __name__ == "__main__":
    main()
