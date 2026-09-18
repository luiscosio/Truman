"""Content-addressed application records, integrity checks and frozen worlds."""
import argparse
import hashlib
import json
import os
import shutil
import threading
import time
from pathlib import Path


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def durable(path, data):
    with Path(path).open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def route_key(method, host, target):
    return sha(encoded([method, host.lower().split(":")[0], target]))


class Store:
    def __init__(self, root):
        self.root = Path(root)
        (self.root / "blobs").mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.seq, self.previous = 0, "0" * 64
        if (self.root / "events.jsonl").exists():
            raise ValueError("Refusing to append to an existing event journal")
        durable(self.root / "events.jsonl", b"")

    def blob(self, data):
        digest = sha(data)
        path = self.root / "blobs" / digest
        with self.lock:
            if path.exists():
                if path.read_bytes() != data:
                    raise ValueError("Blob hash collision/corruption")
            else:
                durable(path, data)
        return digest

    def event(self, kind, **fields):
        with self.lock:
            self.seq += 1
            event = {**fields, "kind": kind, "seq": self.seq, "timestamp": time.time(),
                     "monotonic_ns": time.monotonic_ns(), "previous_sha256": self.previous}
            event["event_sha256"] = sha(encoded(event))
            with (self.root / "events.jsonl").open("ab") as stream:
                stream.write(encoded(event) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            self.previous = event["event_sha256"]
            return event

    def article(self, key, page, text):
        value = {"key": key, "page": page, "text_blob": self.blob(text.encode())}
        directory = self.root / "articles"
        directory.mkdir(exist_ok=True)
        path = directory / (sha(key.encode()) + ".json")
        data = encoded(value)
        with self.lock:
            if path.exists():
                if path.read_bytes() != data:
                    raise ValueError("An article changed within a frozen read-only world")
            else:
                durable(path, data)


def read_blob(root, digest):
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("Invalid blob identifier")
    data = (Path(root) / "blobs" / digest).read_bytes()
    if sha(data) != digest:
        raise ValueError("Blob checksum mismatch: " + digest)
    return data


def journal(path):
    previous = "0" * 64
    records = []
    for seq, line in enumerate(Path(path).read_bytes().splitlines(), 1):
        event = json.loads(line)
        claimed = event.pop("event_sha256")
        if event["seq"] != seq or event["previous_sha256"] != previous or sha(encoded(event)) != claimed:
            raise ValueError("Broken event chain: " + str(path))
        event["event_sha256"] = claimed
        records.append(event)
        previous = claimed
    return records


def files(root):
    return {p.relative_to(root).as_posix(): sha(p.read_bytes()) for p in sorted(Path(root).rglob("*"))
            if p.is_file() and p != Path(root) / "seal.json"}


def seal(root):
    root = Path(root)
    value = {"schema_version": 1, "files": files(root)}
    value["root_sha256"] = sha(encoded(value))
    durable(root / "seal.json", encoded(value))
    return value["root_sha256"]


def verify(root):
    root = Path(root)
    value = json.loads((root / "seal.json").read_bytes())
    claimed = value.pop("root_sha256")
    if sha(encoded(value)) != claimed or files(root) != value["files"]:
        raise ValueError("Run integrity failed: changed, missing or additional files")
    for path in root.rglob("events.jsonl"):
        journal(path)
    for directory in root.rglob("blobs"):
        for path in directory.iterdir():
            read_blob(directory.parent, path.name)
    return claimed


def freeze(run, destination):
    run, destination = Path(run), Path(destination)
    root_hash = verify(run)
    result = json.loads((run / "run.json").read_bytes())
    if result["status"] not in ("completed", "prepared"):
        raise ValueError("Only successful or prepared runs can be frozen")
    if result.get("network_mode") == "managed":
        raise ValueError("Freeze the source renderer recording, not normalized managed-proxy HTTP fields")
    capture = run / "capture"
    context = json.loads((capture / "context.json").read_bytes())
    articles = {a["key"]: a for p in (capture / "articles").glob("*.json") for a in [json.loads(p.read_bytes())]}
    if not articles:
        raise ValueError("No captured articles to freeze")
    routes = {}
    for event in journal(capture / "events.jsonl"):
        if event["kind"] != "http_response" or event["status"] >= 500:
            continue
        key = route_key(event["method"], event["host"], event["path"])
        route = {k: event[k] for k in ("method", "host", "path", "status", "headers_blob", "body_blob", "representation_blob", "evidence")}
        if key in routes and any(routes[key][k] != route[k] for k in ("status", "body_blob", "representation_blob")):
            raise ValueError("Response changed for one route; cannot freeze without choosing a version")
        routes.setdefault(key, route)  # First header block is the canonical replay, including its Date.
    images = json.loads((run / "images.json").read_bytes())
    manifest = {"schema_version": 1, "kind": "truman-frozen-world", **context,
                "source_run": result["batch_id"], "source_seal": root_hash,
                "renderer_image": images["agent_then_world"][1], "articles": articles, "routes": routes}
    for key, filename in (("generator", "generation/simulator.json"), ("generator_runtime", "model-runtime.json")):
        if (run / filename).exists():
            manifest[key] = json.loads((run / filename).read_bytes())
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "blobs").mkdir()
    needed = {a["text_blob"] for a in articles.values()}
    needed.update(route[k] for route in routes.values() for k in ("headers_blob", "body_blob", "representation_blob"))
    for digest in sorted(needed):
        durable(destination / "blobs" / digest, read_blob(capture, digest))
    durable(destination / "snapshot.json", encoded(manifest))
    seal(destination)
    return sha(encoded(manifest))


def load_snapshot(root):
    verify(root)
    data = (Path(root) / "snapshot.json").read_bytes()
    manifest = json.loads(data)
    if manifest.get("schema_version") != 1 or manifest.get("kind") != "truman-frozen-world":
        raise ValueError("Unsupported snapshot format")
    return manifest, sha(data)


class FrozenWorld:
    def __init__(self, root, mode="world"):
        self.root, self.mode = Path(root), mode
        self.snapshot, self.snapshot_hash = load_snapshot(self.root)
        self.condition = self.snapshot["condition"]
        self.manifest_hash = self.snapshot["bundle_manifest_sha256"]
        self.manifest = {"worlds": {"reference": {"cutoff": self.snapshot["as_of"]}}}
        self.pages = {key: a["page"] for key, a in self.snapshot["articles"].items()}
        self._text = {key: read_blob(self.root, a["text_blob"]).decode() for key, a in self.snapshot["articles"].items()}
        if any(sha(self._text[key].encode()) != page["sha256"] for key, page in self.pages.items()):
            raise ValueError("Frozen article metadata does not match its text")

    def lookup(self, method, host, target):
        return self.snapshot["routes"].get(route_key(method, host, target))

    def evidence(self, url):
        from truman.world import url_title
        try:
            page = self.pages.get(url_title(url))
        except ValueError:
            return None
        return {**page, "snapshot_sha256": self.snapshot_hash} if page else None


def main():
    parser = argparse.ArgumentParser(description="Verify recorded runs or freeze a reusable world")
    commands = parser.add_subparsers(dest="action", required=True)
    check = commands.add_parser("verify")
    check.add_argument("directory", type=Path)
    export = commands.add_parser("freeze")
    export.add_argument("run", type=Path)
    export.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(verify(args.directory) if args.action == "verify" else freeze(args.run, args.destination))


if __name__ == "__main__":
    main()
