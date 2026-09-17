"""Exercise real generation, Wikipedia TLS, protocol consistency and isolation."""
import datetime as dt
import json
import os
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    identifier = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-qwen-check-" + uuid.uuid4().hex[:8]
    folder = ROOT / "runs" / identifier
    audit = folder / "generation"
    audit.mkdir(parents=True)
    project = "truman-check-" + uuid.uuid4().hex[:10]
    env = {**os.environ, "TRUMAN_AUDIT_DIR": str(audit.resolve()), "TRUMAN_CONDITION": "synthetic"}
    compose = ["docker", "compose", "-p", project, "-f", str(ROOT / "compose.sandbox.yaml"),
               "-f", str(ROOT / "compose.synthetic.yaml")]
    def execute(arguments, **kwargs):
        return subprocess.run(arguments, cwd=ROOT, env=env, text=True, encoding="utf-8", check=True, **kwargs)
    result = {"id": identifier, "status": "error"}
    try:
        model_id = execute(["docker", "compose", "-f", "compose.qwen.yaml", "ps", "-q", "simulator"], capture_output=True, timeout=20).stdout.strip()
        model = json.loads(execute(["docker", "inspect", model_id], capture_output=True, timeout=20).stdout)[0]
        model_ip = model["NetworkSettings"]["Networks"]["truman-model"]["IPAddress"]
        execute(compose + ["up", "-d", "--wait", "wikipedia", "gateway"], timeout=90)
        probe = execute(compose + ["run", "--rm", "--no-deps", "-T", "agent", "python3", "-", model_ip],
                        input=(ROOT / "sandbox/probe_synthetic.py").read_text(encoding="utf-8"),
                        capture_output=True, timeout=250)
        result.update(status="passed", probe=json.loads(probe.stdout), model_image=model["Image"],
                      model_command=model["Config"]["Cmd"])
        try:
            result["gpu"] = execute(["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free", "--format=csv,noheader"],
                                     capture_output=True, timeout=20).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            result["gpu"] = "unavailable"
    except Exception as exc:
        result["error"] = str(exc)
        if isinstance(exc, subprocess.CalledProcessError):
            result["stdout"], result["stderr"] = exc.stdout, exc.stderr
        raise
    finally:
        logs = subprocess.run(compose + ["logs", "--no-log-prefix", "wikipedia"], cwd=ROOT, env=env,
                              text=True, encoding="utf-8", capture_output=True, timeout=20)
        (folder / "world-service.log").write_text(logs.stdout + logs.stderr, encoding="utf-8")
        subprocess.run(compose + ["down", "--volumes"], cwd=ROOT, env=env, capture_output=True, timeout=40)
        (folder / "check.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps({**result, "directory": str(folder)}, indent=2), flush=True)


if __name__ == "__main__":
    main()
