"""News publication: article acquisition, plain-text representation, search, feed and sitemap.

Published articles have no public revision history. Acquisition captures the
article as published and keeps it only if it was published by the world date.
"""
import datetime as dt
import json
from email.utils import format_datetime
from lxml import etree, html

from sandbox.archive import sha
from sandbox.rewrite_capture import Capture, FetchError
from sandbox.sites import load

__all__ = ['NewsSource', 'plain_text', 'search_page', 'feed', 'sitemap']


def utc(value):
    moment = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    moment = moment.replace(tzinfo=moment.tzinfo or dt.timezone.utc).astimezone(dt.timezone.utc)
    return moment.strftime('%Y-%m-%dT%H:%M:%SZ')


def structured(document):
    """The page's schema.org article object, or {} when it has none."""
    tree = html.fromstring(document, parser=html.HTMLParser(encoding='utf-8'))
    for node in tree.xpath('//script[@type="application/ld+json"]'):
        try:
            data = json.loads(node.text or '')
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and str(item.get('@type', '')).endswith('Article'):
                return item
    return {}


class NewsSource:
    def __init__(self, root, cutoff):
        self.site = load('news')
        self.capture = Capture(root, self.site)
        self.cutoff = cutoff

    def url(self, key):
        return self.site.origin + ('/' if key == self.site.resource['home'] else self.site.path(key))

    def acquire(self, title=None, revision=None):
        if revision:
            raise ValueError('News articles have no public revisions')
        key = self.site.key(title)
        url = self.url(key)
        try:
            raw = self.capture.fetch(url)
        except FetchError as exc:
            if exc.status in (404, 410):
                return {'missing': True, 'title': key}
            raise
        document, assets = self.capture.offline(raw, url)
        metadata = structured(document)
        dated = metadata.get('dateModified') or metadata.get('datePublished')
        timestamp = utc(dated) if dated else self.cutoff
        if timestamp > self.cutoff:
            # Not yet published at the world date.
            return {'missing': True, 'title': key}
        return {'title': key, 'page_id': int(sha(key.encode())[:12], 16),
                'record': {'revid': int(sha(raw)[:12], 16), 'timestamp': timestamp},
                'source': raw.decode('utf-8', 'replace'), 'document': document, 'source_sha256': sha(raw), 'assets': assets}

    def history(self, title, limit):
        return []

    def history_range(self, title, params):
        return []

    def version_title(self, revision):
        return None

    def search(self, query, limit):
        raise ValueError('News search is answered from the captured corpus')


def plain_text(tree):
    """Article prose as plain paragraphs; news pages have no markup source."""
    body = tree.xpath(load('news').content['body'])
    paragraphs = body[0].xpath('.//p') if body else []
    return '\n\n'.join(p.text_content().strip() for p in paragraphs if p.text_content().strip())


def headline(ctx, article):
    tree = html.fromstring(ctx.world.bytes(article['html_blob']), parser=html.HTMLParser(encoding='utf-8'))
    found = tree.xpath(ctx.site.content['heading'])
    return found[0].text_content().strip() if found else article['page']['display_title']


def articles(ctx):
    """Accepted articles, newest first; the front page is not an article."""
    home = ctx.site.resource['home']
    found = [a for a in ctx.world.pages() if a['title'] != home]
    return sorted(found, key=lambda a: (a['record']['timestamp'], a['title']), reverse=True)


def search_page(ctx):
    query = ctx.param('q')
    root = etree.Element('html', lang='en')
    head = etree.SubElement(root, 'head')
    etree.SubElement(head, 'meta', charset='utf-8')
    etree.SubElement(head, 'title').text = 'Search results' + ctx.site.content['title_suffix']
    main = etree.SubElement(etree.SubElement(root, 'body'), 'main')
    etree.SubElement(main, 'h1').text = 'Search results for “' + query + '”' if query else 'Search'
    hits = ctx.world.search(query, ctx.value('limit')) if query else []
    listing = etree.SubElement(main, 'ol')
    for a in hits:
        item = etree.SubElement(listing, 'li')
        etree.SubElement(item, 'a', href=ctx.site.path(a['title'])).text = headline(ctx, a)
        etree.SubElement(item, 'p').text = ctx.extract(a, True)[:300]
    if query and not hits:
        etree.SubElement(main, 'p').text = 'No articles matched your search.'
    return ctx.out(etree.tostring(root, encoding='utf-8', method='html', doctype='<!doctype html>'),
                   mime='text/html; charset=utf-8')


def feed(ctx):
    rss = etree.Element('rss', version='2.0')
    channel = etree.SubElement(rss, 'channel')
    etree.SubElement(channel, 'title').text = ctx.site.name
    etree.SubElement(channel, 'link').text = ctx.site.origin + '/'
    etree.SubElement(channel, 'description').text = 'Latest articles from ' + ctx.site.name
    for a in articles(ctx)[:50]:
        item = etree.SubElement(channel, 'item')
        etree.SubElement(item, 'title').text = headline(ctx, a)
        etree.SubElement(item, 'link').text = ctx.site.url(a['title'])
        etree.SubElement(item, 'guid').text = ctx.site.url(a['title'])
        moment = dt.datetime.fromisoformat(a['record']['timestamp'].replace('Z', '+00:00'))
        etree.SubElement(item, 'pubDate').text = format_datetime(moment, usegmt=True)
        etree.SubElement(item, 'description').text = ctx.extract(a, True)[:500]
    return ctx.out(etree.tostring(rss, encoding='utf-8', xml_declaration=True), mime='application/rss+xml; charset=utf-8')


def sitemap(ctx):
    namespace = 'http://www.sitemaps.org/schemas/sitemap/0.9'
    urlset = etree.Element('{' + namespace + '}urlset', nsmap={None: namespace})
    for a in articles(ctx):
        entry = etree.SubElement(urlset, '{' + namespace + '}url')
        etree.SubElement(entry, '{' + namespace + '}loc').text = ctx.site.url(a['title'])
        etree.SubElement(entry, '{' + namespace + '}lastmod').text = a['record']['timestamp']
    return ctx.out(etree.tostring(urlset, encoding='utf-8', xml_declaration=True), mime='application/xml; charset=utf-8')
