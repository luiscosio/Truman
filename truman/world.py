"""Immutable local retrieval. This module intentionally has no network client."""

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def title_key(title: str) -> str:
    title = title.replace("_", " ").strip()
    return title[:1].upper() + title[1:]


def wiki_url(title: str) -> str:
    return "https://en.wikipedia.org/wiki/" + quote(title_key(title).replace(" ", "_"), safe="()_-,'")


def url_title(url: str) -> str:
    if not isinstance(url, str) or len(url) > 2048:
        raise ValueError("Invalid URL")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or parts.netloc not in (
        "en.wikipedia.org", "en.m.wikipedia.org"
    ):
        raise ValueError("Only English Wikipedia article URLs are available")
    if parts.path.startswith("/wiki/") and not parts.query:
        title = unquote(parts.path[len("/wiki/"):])
    elif parts.path == "/w/index.php":
        query = parse_qs(parts.query, keep_blank_values=True)
        if set(query) != {"title"} or len(query["title"]) != 1:
            raise ValueError("This URL is unavailable")
        title = query["title"][0]
    else:
        raise ValueError("This URL is unavailable")
    if not title or any(c in title for c in ("\x00", "\n", "\r")):
        raise ValueError("Invalid article title")
    return title_key(title)


def links_in(text: str) -> list[dict]:
    links = {}
    for match in re.finditer(r"\[\[([^\[\]\n]+)\]\]", text):
        target, _, label = match.group(1).partition("|")
        target = target.split("#", 1)[0].strip()
        if not target or ":" in target:
            continue
        url = wiki_url(target)
        links.setdefault(url, {"title": label or target, "url": url})
    return list(links.values())


class World:
    def __init__(self, bundle: Path, condition: str):
        self.bundle = Path(bundle)
        manifest_text = (self.bundle / "manifest.json").read_text(encoding="utf-8")
        self.manifest_hash = digest(manifest_text)
        self.manifest = json.loads(manifest_text)
        if self.manifest.get("schema_version") != 1:
            raise ValueError("Unsupported corpus schema")
        self.condition = condition
        self.pages = self.manifest["worlds"][condition]["pages"]
        self._text = {}
        for key, page in self.pages.items():
            path = (self.bundle / page["file"]).resolve()
            if not path.is_relative_to(self.bundle.resolve()):
                raise ValueError("Corpus path escapes bundle")
            text = path.read_text(encoding="utf-8")
            if digest(text) != page["sha256"]:
                raise ValueError(f"Content hash mismatch: {key}")
            self._text[key] = text

    def open_url(self, url: str, offset: int = 0) -> dict:
        try:
            key = url_title(url)
        except (ValueError, TypeError):
            return {"error": "unavailable", "message": "This URL is unavailable."}
        if type(offset) is not int or offset < 0:
            return {"error": "invalid_arguments", "message": "offset must be a nonnegative integer."}
        page = self.pages.get(key)
        if page is None:
            return {"url": wiki_url(key), "error": "unavailable", "message": "This page is unavailable."}
        text = self._text[key]
        if offset > len(text):
            return {"error": "invalid_arguments", "message": "offset is beyond the end of the page."}
        end = min(offset + 14000, len(text))
        excerpt = text[offset:end]
        return {
            "url": wiki_url(page["title"]), "title": page["title"],
            "format": "Wikipedia article source (wikitext; templates are not expanded)",
            "text": excerpt, "offset": offset, "next_offset": end if end < len(text) else None,
            "total_characters": len(text), "links": links_in(excerpt)[:60],
        }

    def evidence(self, url: str) -> dict | None:
        try:
            page = self.pages.get(url_title(url))
        except (ValueError, TypeError):
            return None
        if not page:
            return None
        return {key: page[key] for key in ("revision_id", "revision_at", "sha256", "source_url")}
