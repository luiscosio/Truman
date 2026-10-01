"""Capture pages and their assets as offline documents.

Capture is site-neutral: hosts, banner selectors, the user agent and the metadata
scripts worth keeping come from a site profile. capture() prepares legacy
Wikipedia bundle worlds.
"""
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
from urllib.parse import urljoin, urlsplit

from lxml import html, etree
from sandbox.archive import Store, durable, encoded, seal, verify, sha
from sandbox.generators import scenario_file
from sandbox.sites import profile
from truman.world import World

ROOT = Path(__file__).resolve().parents[1]
# Legacy Wikipedia-only modules read this; on-demand worlds use their site profile.
CONTENT = profile('wikipedia')['content']['body']


class FetchError(subprocess.CalledProcessError):
    """A failed capture request; status is the final HTTP status, if any was received."""
    def __init__(self, url, returncode, status):
        super().__init__(returncode, ['curl', url])
        self.url, self.status = url, status


class TooLarge(ValueError):
    """A response over the capture budget."""


class Capture:
    def __init__(self, root, site):
        self.hosts, self.user_agent = tuple(site.capture['hosts']), site.capture['user_agent']
        self.drop, self.keep_scripts = site.content.get('drop'), tuple(site.rewrite.get('scripts', []))
        self.resize = site.capture.get('oversized_image_query')
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
        if host not in self.hosts:
            raise ValueError("Unapproved capture host: " + host)
        if url in self.cache:
            self.store.event('source_fetch', url=url, exit_code=0, cached=True, response_blob=self.store.blob(self.cache[url]))
            return self.cache[url]
        with tempfile.TemporaryDirectory(prefix='truman-http-') as directory:
            header_path=Path(directory)/'headers'
            result = subprocess.run(["curl.exe" if __import__('os').name == 'nt' else "curl",
                "--silent", "--show-error", "--fail", "--max-time", str(min(45,timeout)), "--retry", "2",
                '--dump-header',str(header_path),"--proto", "=https", "-A", self.user_agent, url],
                capture_output=True, timeout=timeout)
            response_headers=header_path.read_bytes() if header_path.exists() else b''
        self.store.event("source_fetch", url=url, exit_code=result.returncode,
                         response_blob=self.store.blob(result.stdout), headers_blob=self.store.blob(response_headers),stderr_blob=self.store.blob(result.stderr))
        if result.returncode:
            statuses = re.findall(rb'^HTTP/[0-9.]+ ([0-9]{3})', response_headers, re.M)
            raise FetchError(url, result.returncode, int(statuses[-1]) if statuses else None)
        if len(result.stdout) > 8_000_000:
            raise TooLarge("Capture body too large")
        self.cache[url] = result.stdout
        return result.stdout

    def asset(self, url):
        try:
            raw = self.fetch(url)
        except TooLarge:
            # Sites that serve resized images (profile capture.oversized_image_query) get one smaller request.
            if not self.resize:
                raise
            raw = self.fetch(url + ('&' if urlsplit(url).query else '?') + self.resize)
        mime = mimetypes.guess_type(urlsplit(url).path)[0] or "application/octet-stream"
        return "data:" + mime + ";base64," + base64.b64encode(raw).decode()

    def image(self, url):
        """An inlined image, or its original absolute URL when it cannot be captured.

        The live page references its images remotely too, and a browser there
        would also miss an image the server refuses. One oversized or throttled
        image must not fail the whole page. Every such case is recorded.
        """
        try:
            return self.asset(url)
        except TooLarge:
            self.store.event('asset_not_inlined', url=url, reason='over capture budget')
        except FetchError as exc:
            self.store.event('asset_not_inlined', url=url, reason='fetch failed', status=exc.status)
        return url

    def css(self, url):
        css = self.fetch(url).decode()
        def replace(match):
            target = match[1].strip(' "\'')
            # @namespace url(...) names an XML namespace; it is not a file to fetch.
            if target.startswith(('data:', '#')) or re.search(r'@namespace\s+(?:[\w-]+\s+)?$', css[max(0, match.start() - 80):match.start()]):
                return match[0]
            return 'url("' + self.asset(urljoin(url, target)) + '")'
        return re.sub(r'url\(([^)]+)\)', replace, css)

    def offline(self, raw, url):
        tree = html.fromstring(raw)
        # Both conditions share these static-capture transformations. Preserve
        # article markup, skin, references and navigation, but disable active JS.
        # Metadata scripts the site's rewriter reviews are data, not code.
        for node in tree.xpath('//script | //link[@rel="preload" or @rel="dns-prefetch" or @rel="preconnect"]'):
            if node.tag != 'script' or node.get('type') not in self.keep_scripts:
                node.drop_tree()
        for node in tree.xpath(self.drop) if self.drop else []:
            node.drop_tree()
        for node in tree.xpath('//link[@rel="stylesheet"]'):
            css = self.css(urljoin(url, node.get('href')))
            replacement = etree.Element('style'); replacement.text = css
            node.getparent().replace(node, replacement)
        images = tree.xpath('//img[@src]')
        urls = list(dict.fromkeys(urljoin(url, node.get('src')) for node in images if not node.get('src').startswith('data:')))
        with ThreadPoolExecutor(max_workers=6) as pool:
            inlined = dict(zip(urls, pool.map(self.image, urls)))
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
    from sandbox.sites import load
    from sandbox.sites.wikipedia.source import api as mediawiki
    site = load('wikipedia')
    recorder = Capture(destination, site)
    origin = site.origin
    def api(**query):
        return mediawiki(recorder, origin, **query)
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
                data = api(action='query', titles=title, prop='revisions', rvprop='ids|timestamp|content', rvslots='main')
                entry = data['query']['pages'][0]; rev = entry['revisions'][0]
                revision = rev['revid']; wiki = rev['slots']['main']['content']
                page = {'title': title, 'revision_id': revision, 'revision_at': rev['timestamp'],
                        'page_id': entry['pageid'], 'sha256': sha(wiki.encode()),
                        'source_url': origin + '/w/index.php?oldid=' + str(revision)}
            url = origin + '/w/index.php?oldid=' + str(revision)
            raw = recorder.fetch(url)
            # Verify the fetched article revision, not just the URL.
            if not re.search(rb'"wgRevisionId"\s*:\s*' + str(revision).encode() + rb'\b', raw):
                raise ValueError('HTML revision differs from source wikitext: ' + title)
            data = api(action='query', revids=revision, prop='revisions', rvprop='ids|timestamp|user|comment')
            entry = data['query']['pages'][0]
            page['page_id'] = entry['pageid']
            history = api(action='query', titles=entry['title'], prop='revisions',
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
        manifest['siteinfo'] = api(action='query', meta='siteinfo', siprop='general|namespaces|statistics')['query']
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
