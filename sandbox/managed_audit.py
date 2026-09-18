"""Verify managed proxy flows against hash-chained application recordings.

Run in the managed gateway image, mounting the completed case at /evidence.
"""
import json
from pathlib import Path

from mitmproxy.io import FlowReader
from sandbox.archive import journal, read_blob, sha, verify


def audit(path):
    path = Path(path)
    seal = verify(path)
    events = journal(path / "capture/events.jsonl")
    responses = [e for e in events if e["kind"] == "http_response"]
    with (path / "capture/flows.mitm").open("rb") as stream:
        flows = list(FlowReader(stream).stream())
    assert len(flows) == len(responses)
    links = []
    # The synchronous response hook appends both archives in the same order.
    # mitmproxy Flow.copy assigns an independent ID to the redacted archive copy.
    for flow, event in zip(flows, responses):
        assert flow.request.method == event["method"] and flow.request.path == event["path"]
        assert flow.metadata["host"] == event["host"]
        assert flow.client_conn.id == event["connection_id"]
        assert flow.response.status_code == event["status"]
        assert sha(flow.response.raw_content or b"") == event["body_blob"]
        assert sha(flow.metadata["representation"]) == event["representation_blob"]
        headers = (flow.response.http_version + " " + str(flow.response.status_code) + " " + flow.response.reason + "\r\n").encode()
        headers += b"".join(k + b": " + v + b"\r\n" for k, v in flow.response.headers.fields) + b"\r\n"
        assert headers == read_blob(path / "capture", event["headers_blob"])
        links.append({"native_flow_id": flow.id, "capture_request_id": event["request_id"]})
    origin = [e for e in journal(path / "origin-capture/events.jsonl") if e["kind"] == "http_response"]
    matched = 0
    for event in responses:
        if event["method"] in ("GET", "HEAD") and event["status"] < 500:
            candidates = [e for e in origin if e["host"] == event["host"] and e["path"] == event["path"] and e["status"] == event["status"]]
            assert any(e["representation_blob"] == event["representation_blob"] for e in candidates)
            matched += 1
    audit_events = journal(path / "network-audit/events.jsonl")
    assert not any(e["kind"] in ("origin_error", "proxy_error") for e in events)
    result = json.loads((path / "run.json").read_bytes())
    boundary = result["agent_capture_after_seq"]
    assert all(e["seq"] > boundary for e in result["network_requests"])
    assert not (path / "generation").exists()
    return {"run": path.name, "seal": seal, "native_flows_verified": len(flows),
            "target_responses": len(result["network_requests"]), "origin_body_matches": matched,
            "http_versions": sorted({e["http_version"] for e in responses}),
            "dns_decisions": sum(e["kind"] == "dns" for e in audit_events), "flow_links": links,
            "delivery_scope": "Response prepared for delivery; native flows are not independent proof of receipt"}


if __name__ == "__main__":
    print(json.dumps(audit("/evidence"), sort_keys=True))
