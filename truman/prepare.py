"""Acquire actual Wikipedia revisions, without rendering current templates."""

import datetime as dt
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode

from .world import digest, title_key, wiki_url

DEFAULT_TITLES = [
    "Monarchy of the United Kingdom", "Prime Minister of the United Kingdom", "President of France",
    "Elizabeth II", "Charles III", "Theresa May", "Keir Starmer",
    "François Hollande", "Emmanuel Macron", "List of British monarchs",
]
USER_AGENT = "TrumanWikipediaResearch/0.1 (small local historical-revision experiment)"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def cutoff(value: str) -> str:
    if len(value) == 10:
        value += "T23:59:59Z"
    date = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.tzinfo is None:
        raise ValueError("Cutoff needs a date or a timezone-aware ISO timestamp")
    return date.astimezone(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Wikipedia:
    def __init__(self, transport: str = "urllib"):
        self.transport = transport
        self.cache = {}

    def request(self, params: dict) -> dict:
        url = "https://en.wikipedia.org/w/api.php?" + urlencode({
            "format": "json", "formatversion": 2, "maxlag": 5, **params,
        })
        for attempt in range(3):
            try:
                if self.transport == "curl":
                    # No shell and no credentials. Windows curl can use the system TLS store.
                    result = subprocess.run([
                        "curl", "--silent", "--show-error", "--fail", "--max-time", "40",
                        "--user-agent", USER_AGENT, url,
                    ], capture_output=True, check=True, timeout=45)
                    data = json.loads(result.stdout)
                else:
                    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                    with urllib.request.urlopen(request, timeout=40) as response:
                        data = json.load(response)
                if "error" in data:
                    raise ValueError(f"Wikipedia API: {data['error'].get('info', 'unknown error')}")
                return data
            except (urllib.error.URLError, subprocess.SubprocessError, ValueError):
                if attempt == 2:
                    raise
                time.sleep(1 + attempt)
        raise AssertionError("unreachable")

    def revision(self, title: str, at: str) -> dict:
        key = (title_key(title), at)
        if key not in self.cache:
            data = self.request({
                "action": "query", "prop": "revisions", "titles": title,
                "rvprop": "ids|timestamp|content", "rvslots": "main", "rvlimit": 1,
                "rvstart": at, "rvdir": "older",
            })
            page = data["query"]["pages"][0]
            revisions = page.get("revisions", [])
            if not revisions:
                raise ValueError(f"No accessible revision of {title!r} at {at}")
            revision = revisions[0]
            content = revision["slots"]["main"].get("content")
            if not content:
                raise ValueError(f"Revision content missing for {title!r}")
            if revision["timestamp"] > at:
                raise ValueError("Wikipedia returned a revision beyond the requested cutoff")
            self.cache[key] = {"title": page["title"], "revision_id": revision["revid"],
                               "revision_at": revision["timestamp"], "content": content}
            time.sleep(0.15)
        return self.cache[key]


def prepare(output: Path, old_at: str, titles: list[str], transport: str = "urllib") -> dict:
    output = Path(output)
    if output.exists():
        raise ValueError(f"Destination exists; choose a new bundle directory: {output}")
    reference_at = utc_now()
    old_at = cutoff(old_at)
    if old_at >= reference_at:
        raise ValueError("Historical cutoff must precede the reference capture")
    api = Wikipedia(transport)
    manifest = {
        "schema_version": 1, "created_at": reference_at,
        "extraction": "Unmodified revision wikitext; no modern template expansion",
        "license_note": "Wikipedia text: see each revision's attribution/history and applicable CC BY-SA terms.",
        "worlds": {},
    }
    # Collect in memory first: failed acquisition never leaves a seemingly complete bundle.
    files = {}
    for condition, at in (("reference", reference_at), ("historical", old_at)):
        pages = {}
        pending = list(dict.fromkeys(titles))
        while pending:
            requested = title_key(pending.pop(0))
            if requested in pages:
                continue
            print(f"Fetching {condition}: {requested}", flush=True)
            page = api.revision(requested, at)
            text = page["content"]
            sha = digest(text)
            filename = f"pages/{sha}.wiki"
            files[filename] = text
            entry = {k: page[k] for k in ("title", "revision_id", "revision_at")}
            entry.update({"file": filename, "sha256": sha,
                          "source_url": f"https://en.wikipedia.org/w/index.php?oldid={page['revision_id']}",
                          "canonical_url": wiki_url(page["title"])})
            pages[requested] = entry
            pages[title_key(page["title"])] = entry
            redirect = re.match(r"\s*#redirect\s*\[\[([^\]|#]+)", text, re.IGNORECASE)
            if redirect:
                target = title_key(redirect.group(1))
                entry["redirect_to"] = wiki_url(target)
                if target not in pages and target not in pending:
                    pending.append(target)
            if len(pages) > len(titles) + 40:
                raise ValueError("Too many redirects while acquiring fixtures")
        manifest["worlds"][condition] = {"cutoff": at, "pages": pages}
    output.mkdir(parents=True, exist_ok=False)
    (output / "pages").mkdir()
    for filename, text in files.items():
        with (output / filename).open("x", encoding="utf-8", newline="") as stream:
            stream.write(text)
    with (output / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2, ensure_ascii=False)
    return manifest
