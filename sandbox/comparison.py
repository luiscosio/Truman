"""Combine two already completed, matching network runs without rerunning models."""
import argparse
import datetime as dt
import json
import uuid
from pathlib import Path

from truman.report import write_report
from truman.runner import write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", type=Path, nargs=2, help="Two run directories, reference and historical")
    args = parser.parse_args()
    results = [json.loads((p / "run.json").read_text(encoding="utf-8")) for p in args.runs]
    if {r["condition"] for r in results} != {"reference", "historical"}:
        parser.error("Provide one run of each condition")
    for key in ("experiment_sha256", "bundle_manifest_sha256", "model", "observed_tools", "limits"):
        if results[0][key] != results[1][key]:
            parser.error("Runs differ in " + key)
    if any(r["status"] != "completed" or not r["interception_observed"] for r in results):
        parser.error("Both runs must complete with intercepted page requests")
    images = [json.loads((p / "images.json").read_text(encoding="utf-8")) for p in args.runs]
    if images[0] != images[1]:
        parser.error("Runs used different images")
    batch = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-network-pair-" + uuid.uuid4().hex[:8]
    for result in results:
        result["source_batch_id"] = result["batch_id"]
        result["batch_id"] = batch
    root = Path(__file__).resolve().parent.parent
    folder = root / "runs" / batch
    folder.mkdir()
    write_json(folder / "comparison.json", {"source_runs": [str(p.resolve()) for p in args.runs], "results": results})
    print(write_report(results, batch, root / "reports"))


if __name__ == "__main__":
    main()
