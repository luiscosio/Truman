"""Compare model/effort variants against one independently frozen world."""
import argparse
import datetime as dt
import json
import subprocess
import sys
import uuid
from pathlib import Path

from sandbox.archive import durable, encoded, load_snapshot, seal, verify
from truman.report import write_report

ROOT = Path(__file__).resolve().parent.parent


def compare_runs(paths):
    results, images = [], []
    for path in paths:
        verify(path)
        result = json.loads((path / "run.json").read_bytes())
        if not result.get("snapshot_sha256"):
            raise ValueError("Model comparisons require a frozen snapshot")
        if result["status"] != "completed" or not result["required_pages_opened"]:
            raise ValueError("A case failed or did not retrieve the required article")
        results.append(result)
        images.append(json.loads((path / "images.json").read_bytes()))
    for key in ("snapshot_sha256", "replay_mode", "experiment_sha256", "observed_tools", "limits", "agent_adapter"):
        if any(r.get(key) != results[0].get(key) for r in results):
            raise ValueError("Incompatible cases: " + key)
    if any(image != images[0] for image in images):
        raise ValueError("Cases used different images")
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--repetitions", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 50:
        parser.error("Repetitions must be between 1 and 50")
    snapshot, fingerprint = load_snapshot(args.snapshot)
    config = json.loads(args.config.read_bytes())
    if not config.get("cases") or len(config["cases"]) > 20:
        parser.error("Supply 1-20 cases")
    for case in config["cases"]:
        if case.get("agent", "claude-code") != "claude-code":
            parser.error("Only the Claude Code adapter is installed; archives are agent-independent")
        if not case.get("model") or case.get("effort") not in ("low", "medium", "high", "xhigh", "max"):
            parser.error("Each case needs explicit model and effort values")
    batch = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-suite-" + uuid.uuid4().hex[:8]
    folder = ROOT / "runs" / batch
    folder.mkdir()
    durable(folder / "suite.json", encoded({"snapshot_sha256": fingerprint, "config": config, "repetitions": args.repetitions}))
    paths, cases = [], []
    try:
        for repetition in range(1, args.repetitions + 1):
            for index, case in enumerate(config["cases"], 1):
                identifier = batch + f"-r{repetition}-c{index}"
                command = [sys.executable, "-m", "sandbox.run", "--replay-from", str(args.snapshot.resolve()),
                    "--run-id", identifier, "--repetition", str(repetition),
                    "--model", case["model"], "--effort", case["effort"],
                    "--label", case.get("name", f"Case {index}") + f" / repetition {repetition}",
                    "--task", config.get("task", "monarch"), "--seconds", str(config.get("seconds", 360)),
                    "--max-turns", str(config.get("max_turns", 16))]
                for follow in config.get("follow_ups", []):
                    command += ["--follow-up", follow]
                with (folder / f"case-r{repetition}-c{index}.log").open("xb") as log:
                    outcome = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                             timeout=int(config.get("seconds", 360)) + 240)
                print(f"Case {index}, repetition {repetition}: exit {outcome.returncode}; {identifier}", flush=True)
                paths.append(ROOT / "runs" / identifier)
                cases.append({"run": identifier, "exit_code": outcome.returncode})
        results = compare_runs(paths)
        report = write_report(results, batch, ROOT / "reports")
        durable(folder / "report.html", report.read_bytes())
        durable(folder / "comparison.json", encoded({"results": results, "source_runs": [str(p) for p in paths]}))
        print("Report: " + str(report), flush=True)
    finally:
        durable(folder / "cases.json", encoded(cases))
        seal(folder)


if __name__ == "__main__":
    main()
