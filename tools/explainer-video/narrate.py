"""Synthesize the explainer narration with ElevenLabs, one clip per scene.

Reads narration/script.json and writes public/narration/<scene>.mp3 plus
src/narration.json (each clip's length), which Root.tsx uses to time scenes.
Clips are cached by a hash of the request, so a rerun only bills changed lines.

Settings come from the environment or from the repository's Git-ignored .env:
ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID. The key is never printed.

    uv run python tools/explainer-video/narrate.py [--force] [scene ...]
"""

import argparse
import base64
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
SCRIPT = HERE / "narration" / "script.json"
AUDIO = HERE / "public" / "narration"
TIMINGS = HERE / "src" / "narration.json"


def settings():
    values = {}
    env_file = REPO / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and not key.startswith("#"):
                values[key.strip()] = value.strip().strip("\"'")
    values.update({k: v for k, v in os.environ.items() if k.startswith("ELEVENLABS_")})
    missing = [k for k in ("ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID") if not values.get(k)]
    if missing:
        sys.exit(f"Set {' and '.join(missing)} in the environment or in {env_file}.")
    return values["ELEVENLABS_API_KEY"], values["ELEVENLABS_VOICE_ID"]


def synthesize(text, language, model, key, voice):
    url = (f"https://api.elevenlabs.io/v1/text-to-speech/{urllib.parse.quote(voice)}/with-timestamps?"
           + urllib.parse.urlencode({"output_format": "mp3_44100_128"}))
    payload = {"text": text, "model_id": model, "language_code": language,
               "voice_settings": {"stability": 0.5}, "apply_text_normalization": "auto"}
    request = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "xi-api-key": key})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        sys.exit(f"ElevenLabs returned {error.code}: {error.read().decode(errors='replace')[:300]}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scenes", nargs="*", help="Only these scene ids (default: all)")
    parser.add_argument("--force", action="store_true", help="Synthesize even when cached")
    args = parser.parse_args()

    script = json.loads(SCRIPT.read_text(encoding="utf-8"))
    key, voice = settings()
    AUDIO.mkdir(parents=True, exist_ok=True)
    timings = json.loads(TIMINGS.read_text(encoding="utf-8")) if TIMINGS.exists() else {}
    ids = {scene["id"] for scene in script["scenes"]}
    timings = {sid: t for sid, t in timings.items() if sid in ids}  # scenes removed from the script

    for scene in script["scenes"]:
        sid, text = scene["id"], " ".join(scene["text"].split())
        if args.scenes and sid not in args.scenes:
            continue
        digest = hashlib.sha256(json.dumps([text, script["model_id"], script["language"], voice]).encode()).hexdigest()[:16]
        clip = AUDIO / f"{sid}.mp3"
        if not args.force and clip.exists() and timings.get(sid, {}).get("hash") == digest:
            print(f"cached  {sid}")
            continue
        result = synthesize(text, script["language"], script["model_id"], key, voice)
        clip.write_bytes(base64.b64decode(result["audio_base64"]))
        alignment = result.get("normalized_alignment") or result.get("alignment") or {}
        seconds = round((alignment.get("character_end_times_seconds") or [0])[-1], 3)
        timings[sid] = {"hash": digest, "seconds": seconds}
        print(f"voice   {sid:<12} {seconds:6.2f} s")

    TIMINGS.write_text(json.dumps(timings, indent=1) + "\n", encoding="utf-8")
    total = sum(t["seconds"] for t in timings.values())
    print(f"{len(timings)} clips, {total:.1f} s of narration")


if __name__ == "__main__":
    main()
