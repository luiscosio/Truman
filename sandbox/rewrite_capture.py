"""Capture revision-pinned Wikipedia HTML and assets before an offline run."""
import argparse
import base64
import copy
import datetime as dt
import json
import mimetypes
import re
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit

from lxml import html, etree
from sandbox.archive import Store, durable, encoded, seal, verify, sha
from sandbox.generators import scenario_file
from truman.world import World

ROOT = Path(__file__).resolve().parents[1]
CONTENT = '//*[contains(concat(" ", normalize-space(@class), " "), " mw-parser-output ")][descendant::p]'


class Capture:
    def __init__(self, root):
        self.store = Store(root / "http")
        self.cache = {}
        # Reuse verified bodies from previous sealed captures, including failed
        # preparations. Never mutate them or repeat successful downloads.
        for previous in root.parent.glob('*/seal.json'):
            old = previous.parent
            verify(old)
            journal = old/'http/events.jsonl'
            if journal.exists():
                from sandbox.archive import read_blob
                for line in journal.read_bytes().splitlines():
                    event = json.loads(line)
                    if event.get('kind') == 'source_fetch' and event.get('exit_code') == 0:
                        self.cache[event['url']] = read_blob(old/'http', event['response_blob'])

    def fetch(self, url):
        from sandbox.demand_budget import remaining
        timeout=remaining(self,150)
        host = urlsplit(url).hostname or ""
        if host not in ("en.wikipedia.org", "upload.wikimedia.org", "thumb.wikimedia.org"):
            raise ValueError("Unapproved capture host: " + host)
        if url in self.cache:
            self.store.event('source_fetch', url=url, exit_code=0, cached=True, response_blob=self.store.blob(self.cache[url]))
            return self.cache[url]
        with tempfile.TemporaryDirectory(prefix='truman-http-') as directory:
            header_path=Path(directory)/'headers'
            result = subprocess.run(["curl.exe" if __import__('os').name == 'nt' else "curl",
                "--silent", "--show-error", "--fail", "--max-time", str(min(45,timeout)), "--retry", "2",
                '--dump-header',str(header_path),"--proto", "=https", "-A", "TrumanWikipediaResearch/0.2", url],
                capture_output=True, timeout=timeout)
            response_headers=header_path.read_bytes() if header_path.exists() else b''
        self.store.event("source_fetch", url=url, exit_code=result.returncode,
                         response_blob=self.store.blob(result.stdout), headers_blob=self.store.blob(response_headers),stderr_blob=self.store.blob(result.stderr))
        result.check_returncode()
        if len(result.stdout) > 8_000_000:
            raise ValueError("Capture body too large")
        self.cache[url] = result.stdout
        return result.stdout

    def api(self, **query):
        result = json.loads(self.fetch("https://en.wikipedia.org/w/api.php?" + urlencode(
            {"format": "json", "formatversion": 2, **query})))
        if "error" in result:
            raise ValueError(str(result["error"]))
        return result

    def asset(self, url):
        raw = self.fetch(url)
        mime = mimetypes.guess_type(urlsplit(url).path)[0] or "application/octet-stream"
        return "data:" + mime + ";base64," + base64.b64encode(raw).decode()

    def css(self, url):
        css = self.fetch(url).decode()
        def replace(match):
            target = match[1].strip(' "\'')
            if target.startswith(('data:', '#')):
                return match[0]
            return 'url("' + self.asset(urljoin(url, target)) + '")'
        return re.sub(r'url\(([^)]+)\)', replace, css)

    def offline(self, raw, url):
        tree = html.fromstring(raw)
        # Both conditions share these static-capture transformations. Preserve
        # article markup, skin, references and navigation, but disable active JS.
        for node in tree.xpath('//script | //link[@rel="preload" or @rel="dns-prefetch" or @rel="preconnect"]'):
            node.drop_tree()
        for node in tree.xpath('//*[starts-with(@id,"mw-revision-info") or @id="mw-revision-nav"]'):
            node.drop_tree()
        for node in tree.xpath('//link[@rel="stylesheet"]'):
            css = self.css(urljoin(url, node.get('href')))
            replacement = etree.Element('style'); replacement.text = css
            node.getparent().replace(node, replacement)
        images = tree.xpath('//img[@src]')
        urls = list(dict.fromkeys(urljoin(url, node.get('src')) for node in images if not node.get('src').startswith('data:')))
        with ThreadPoolExecutor(max_workers=6) as pool:
            inlined = dict(zip(urls, pool.map(self.asset, urls)))
        assets = 0
        for node in images:
            src = node.get('src')
            if not src.startswith('data:'):
                node.set('src', inlined[urljoin(url, src)]); assets += 1
            node.attrib.pop('srcset', None)
            node.attrib.pop('loading', None)
        for node in tree.iter():
            for attr in list(node.attrib):
                if attr.lower().startswith('on'):
                    del node.attrib[attr]
        for node in tree.xpath('//link[@rel="icon"]'):
            node.set('href', self.asset(urljoin(url, node.get('href'))))
        return etree.tostring(tree, method='html', encoding='utf-8', doctype='<!doctype html>'), assets


def capture(scenario, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    recorder = Capture(destination)
    world = World(ROOT / scenario['source_bundle'], scenario.get('source_condition', 'historical'))
    titles = list(dict.fromkeys(scenario['seed_pages'] + scenario.get('support_pages', [])))
    if len(titles) > scenario.get('preparation', {}).get('max_pages', 30):
        raise ValueError('Source page budget exceeded')
    manifest = {'schema_version': 1, 'kind': 'truman-original-html', 'pages': {},
                'captured_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                'transformations': ['disable active scripts in both conditions', 'inline captured CSS/images',
                                    'hide old-revision notice in both conditions'],
                'limitations': ['Historical revisions render using templates and skin available at capture time.',
                                'Static capture does not implement the complete interactive Wikipedia UI.']}
    try:
        for title in titles:
            print('Capturing original: ' + title, flush=True)
            if title in world.pages:
                page = copy.deepcopy(world.pages[title]); wiki = world._text[title]
                revision = page['revision_id']
            else:
                data = recorder.api(action='query', titles=title, prop='revisions', rvprop='ids|timestamp|content', rvslots='main')
                entry = data['query']['pages'][0]; rev = entry['revisions'][0]
                revision = rev['revid']; wiki = rev['slots']['main']['content']
                page = {'title': title, 'revision_id': revision, 'revision_at': rev['timestamp'],
                        'page_id': entry['pageid'], 'sha256': sha(wiki.encode()),
                        'source_url': 'https://en.wikipedia.org/w/index.php?oldid=' + str(revision)}
            url = 'https://en.wikipedia.org/w/index.php?oldid=' + str(revision)
            raw = recorder.fetch(url)
            # Verify the fetched article revision, not just the URL.
            if not re.search(rb'"wgRevisionId"\s*:\s*' + str(revision).encode() + rb'\b', raw):
                raise ValueError('HTML revision differs from source wikitext: ' + title)
            data = recorder.api(action='query', revids=revision, prop='revisions', rvprop='ids|timestamp|user|comment')
            entry = data['query']['pages'][0]
            page['page_id'] = entry['pageid']
            history = recorder.api(action='query', titles=entry['title'], prop='revisions',
                rvstartid=revision, rvlimit=10, rvprop='ids|timestamp|user|comment|content', rvslots='main')['query']['pages'][0]['revisions']
            if history[0]['revid'] != revision or sha(history[0]['slots']['main']['content'].encode()) != page['sha256']:
                raise ValueError('Captured history and source article do not match')
            for record in history:
                record['source_blob'] = recorder.store.blob(record.pop('slots')['main']['content'].encode())
            prepared, assets = recorder.offline(raw, url)
            if len(prepared) > 7_500_000:
                raise ValueError('Inlined page exceeds managed proxy body budget')
            manifest['pages'][title] = {'page': page, 'source_title': entry['title'],
                'wiki_blob': recorder.store.blob(wiki.encode()), 'original_html_blob': recorder.store.blob(raw),
                'html_blob': recorder.store.blob(prepared), 'assets': assets,
                'revisions': history}
            print(f'  {len(raw):,} original bytes; {assets} images captured', flush=True)
        manifest['siteinfo'] = recorder.api(action='query', meta='siteinfo', siprop='general|namespaces|statistics')['query']
        durable(destination/'source.json', encoded(manifest))
        durable(destination/'scenario.json', encoded(scenario))
    except Exception as exc:
        durable(destination/'failure.json', encoded({'error': str(exc)})); seal(destination)
        raise
    seal(destination)
    return destination


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scenario', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    capture(scenario_file(args.scenario), args.output)
    print('Source seal: ' + verify(args.output))


if __name__ == '__main__':
    main()
