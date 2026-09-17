"""Download and verify the pinned local world model outside the repository."""
import hashlib
import json
import os
import subprocess
from pathlib import Path

REPOSITORY = "unsloth/Qwen-AgentWorld-35B-A3B-GGUF"
REVISION = "3a305abf5cfd119ee999dfe929c433746edd8d63"
FILENAME = "Qwen-AgentWorld-35B-A3B-UD-Q4_K_M.gguf"
SHA256 = "e7a8eafdd8013443b6bcc4b6fb47b2d2025f772d359650b9ceb7d75971e22cad"
SIZE = 22134529280
VOLUME = "truman-qwen-model"


def model_directory():
    return Path(os.environ.get("TRUMAN_MODEL_DIR", Path.home() / ".cache/truman/models"))


def main():
    directory = model_directory()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / FILENAME
    partial = directory / (FILENAME + ".partial")
    if not target.exists():
        url = f"https://huggingface.co/{REPOSITORY}/resolve/{REVISION}/{FILENAME}"
        subprocess.run(["curl.exe" if os.name == "nt" else "curl", "--fail", "--location",
                        "--retry", "5", "--continue-at", "-", "--output", str(partial), url], check=True)
        candidate = partial
    else:
        candidate = target
    print("Verifying model SHA-256", flush=True)
    with candidate.open("rb") as stream:
        observed = hashlib.file_digest(stream, "sha256").hexdigest()
    if candidate.stat().st_size != SIZE or observed != SHA256:
        raise RuntimeError("Model size/hash does not match the pinned artifact")
    if candidate == partial:
        partial.rename(target)
    metadata = {"repository": REPOSITORY, "revision": REVISION, "file": FILENAME,
                "sha256": SHA256, "bytes": SIZE}
    (directory / "model.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Verified: {target}", flush=True)
    # Sequentially copy into native Docker storage. Parsing GGUF through the
    # Windows 9P bind mount incurs thousands of small, very slow reads.
    subprocess.run(["docker", "volume", "create", VOLUME], check=True)
    stage = f'''import hashlib, json, pathlib, time
source = pathlib.Path('/source') / {FILENAME!r}
target = pathlib.Path('/models') / {FILENAME!r}
expected = {SHA256!r}
if target.exists():
    with target.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == expected, 'Existing Docker model hash mismatch'
else:
    partial = target.with_suffix('.stage-' + str(time.time_ns()))
    total = 0
    checksum = hashlib.sha256()
    with source.open('rb') as incoming, partial.open('xb') as outgoing:
        while chunk := incoming.read(8 * 1024 * 1024):
            outgoing.write(chunk)
            checksum.update(chunk)
            total += len(chunk)
    assert total == {SIZE} and checksum.hexdigest() == expected, 'Staged model hash mismatch'
    partial.rename(target)
print('Verified model in native Docker volume', flush=True)
'''
    print("Staging verified weights into Docker storage", flush=True)
    subprocess.run(["docker", "run", "--rm", "--network", "none",
                    "--mount", f"type=bind,source={directory.resolve()},target=/source,readonly",
                    "--mount", f"type=volume,source={VOLUME},target=/models",
                    "python:3.12-slim", "python", "-c", stage], check=True)


if __name__ == "__main__":
    main()
