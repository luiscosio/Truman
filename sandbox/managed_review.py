"""Create a separately sealed audit and current-viewer report for a managed pair."""
import argparse
import datetime as dt
import json
import subprocess
import uuid
from pathlib import Path

from sandbox.archive import durable, encoded, seal, verify
from truman.report import write_report

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("suite", type=Path)
    args = parser.parse_args()
    source_seal = verify(args.suite)
    cases = json.loads((args.suite / "cases.json").read_bytes())
    if not cases or any(case["exit_code"] for case in cases):
        raise ValueError("Require a completed pair")
    identifier = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-managed-review-" + uuid.uuid4().hex[:8]
    folder = ROOT / "runs" / identifier
    folder.mkdir()
    audits, results = [], []
    for case in cases:
        path = args.suite.resolve().parent / case["run"]
        network = json.loads((path / "network-profile.json").read_bytes())
        command = ["docker", "run", "--rm", "--network", "none", "-v", str(ROOT) + ":/app:ro",
                   "-v", str(path) + ":/evidence:ro", network["gateway_image"], "python", "-m", "sandbox.managed_audit"]
        output = subprocess.run(command, check=True, capture_output=True, timeout=60)
        value = json.loads(output.stdout)
        value["run"] = path.name
        audits.append(value)
        result = json.loads((path / "run.json").read_bytes())
        results.append(result)
        durable(folder / (path.name + "-audit.json"), encoded(value))
        durable(folder / (path.name + "-preflight.json"), (path / "preflight.json").read_bytes())
    report = write_report(results, identifier, ROOT / "reports")
    durable(folder / "report.html", report.read_bytes())
    durable(folder / "validation.json", encoded({"source_suite": args.suite.name, "source_seal": source_seal,
        "cases": audits, "native_flows_verified": sum(a["native_flows_verified"] for a in audits),
        "target_responses": sum(a["target_responses"] for a in audits)}))
    durable(folder / "auditor.py", (ROOT / "sandbox/managed_audit.py").read_bytes())
    durable(folder / "reviewer.py", Path(__file__).read_bytes())
    print("Seal: " + seal(folder))
    print("Report: " + str(report))


if __name__ == "__main__":
    main()
