"""Lossless subprocess output plus normalized events; no provider interception."""
import json
import os
import queue
import threading
from pathlib import Path

from sandbox.archive import Store, encoded, durable


class Recorder:
    def __init__(self, root):
        self.root = Path(root)
        self.store = Store(self.root / "supervisor")
        self.events, self.queue = [], queue.Queue()
        self.error = None
        self.lock = threading.RLock()
        self.log = (self.root / "claude-code.jsonl").open("xb")
        self.input = (self.root / "agent.stdin.jsonl").open("xb")

    def normalized(self, value):
        with self.lock:
            self.events.append(value)
            self.log.write(encoded(value) + b"\n")
            self.log.flush()
            os.fsync(self.log.fileno())

    def collect(self, stream):
        try:
            with (self.root / "agent.stdout.bin").open("xb") as output:
                for line in stream:
                    output.write(line)
                    output.flush()
                    os.fsync(output.fileno())
                    receipt = self.store.event("agent_stdout", blob=self.store.blob(line))
                    try:
                        event = json.loads(line)
                        if not isinstance(event, dict):
                            raise ValueError("Non-object event")
                    except (ValueError, UnicodeError):
                        self.store.event("stdout_parse_error", receipt_seq=receipt["seq"])
                        continue
                    event["_received_at"] = receipt["timestamp"]
                    event["_receipt_seq"] = receipt["seq"]
                    self.normalized(event)
                    self.queue.put(event)
        except Exception as exc:
            self.error = str(exc)
        finally:
            self.queue.put(None)

    def start(self, stream):
        self.thread = threading.Thread(target=self.collect, args=(stream,), daemon=True)
        self.thread.start()

    def send(self, stream, text, follow_up=False):
        payload = encoded({"type": "user", "message": {"role": "user", "content": text}}) + b"\n"
        event = self.store.event("agent_input_attempt", blob=self.store.blob(payload), follow_up=follow_up)
        self.input.write(payload)
        self.input.flush()
        os.fsync(self.input.fileno())
        if follow_up:
            self.normalized({"type": "truman_user", "text": text, "_received_at": event["timestamp"]})
        stream.write(payload)
        stream.flush()
        self.store.event("agent_input_sent", input_seq=event["seq"])

    def close(self):
        if hasattr(self, "thread"):
            self.thread.join(timeout=20)
            if self.thread.is_alive():
                raise RuntimeError("Output collector has not finished; run cannot be sealed")
        self.log.close()
        self.input.close()


def provenance(root, recorder, cli):
    import subprocess
    root = Path(root)
    selected = list((root / "sandbox").glob("*.py")) + list((root / "truman").glob("*.py"))
    selected += list(root.glob("compose*.yaml")) + list((root / "sandbox").glob("*.sh"))
    selected += list((root / "sandbox").glob("Dockerfile.*")) + list((root / "sandbox").glob("*.conf"))
    sources = {p.relative_to(root).as_posix(): recorder.store.blob(p.read_bytes()) for p in selected}
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10)
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, timeout=10)
    durable(recorder.root / "provenance.json", encoded({"git_commit": commit.stdout.strip(),
        "git_dirty": bool(dirty.stdout.strip()), "source_blobs": sources, "agent_command": cli,
        "capture_scope": "Claude Code emitted events and Wikipedia application HTTP; no provider-internal exchanges"}))
