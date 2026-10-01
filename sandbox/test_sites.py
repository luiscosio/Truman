import base64
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from lxml import etree, html

from sandbox.demand import WorldService, create
from sandbox.demand_bridge import Worker, publish
from sandbox.demand_integrity import integrity_issues
from sandbox.demand_rewrite import surfaces
from sandbox.rewrite_capture import FetchError
from sandbox.sites import ProfileError, Site, load
from sandbox.test_demand import SCENARIO, Source

NEWS_SCENARIO = {'id': 'news-test', 'site': 'news', 'as_of': '2026-09-18', 'condition': 'reference',
                 'facts': ['Nothing changes.'], 'generators': {'b': {'model': 'claude-sonnet-5'}}}


def article(headline, published, body, metadata=None):
    data = json.dumps(metadata if metadata is not None else
                      {'@context': 'https://schema.org', '@type': 'NewsArticle', 'headline': headline, 'datePublished': published})
    return ('<!doctype html><html><head><title>' + headline + ' | Example News</title>'
            '<script type="application/ld+json">' + data + '</script><script>track()</script></head>'
            '<body><article><header><h1>' + headline + '</h1><p class="standfirst">' + body[0] + '</p></header>'
            '<div>' + ''.join('<p>' + p + '</p>' for p in body[1:]) + '</div></article></body></html>').encode()


PAGES = {
    'https://www.news.example/': b'<!doctype html><html><body><article><h1>Front page</h1><p>Top stories.</p></article></body></html>',
    'https://www.news.example/articles/2026/09/17/lab-opens': article(
        'Research lab opens in Oslo', '2026-09-17T08:00:00+02:00',
        ['A new research lab opened in Oslo.', 'The lab will study climate models.']),
    'https://www.news.example/articles/2026/09/18/budget-vote': article(
        'Council approves budget', '2026-09-18T10:00:00Z', ['The council approved the budget.', 'The vote was 7 to 2.']),
    'https://www.news.example/articles/2026/09/20/later-story': article(
        'A story from after the world date', '2026-09-20T10:00:00Z', ['Not yet published.']),
}


def fetch(capture, url):
    if url not in PAGES:
        raise FetchError(url, 22, 404)
    return PAGES[url]


class ProfileTests(unittest.TestCase):
    def broken(self, old, new):
        raw = load('wikipedia').yaml.decode()
        self.assertIn(old, raw)
        return lambda: Site(raw.replace(old, new, 1).encode(), 'wikipedia')

    def test_profiles_reject_invalid_rules(self):
        cases = [('handler: export_page}', 'handler: no_such_handler}'),
                 ('default: projection', 'default: native'),
                 ('rvdir: {type: enum', 'rvdir: {type: decimal'),
                 ('hosts: [en.wikipedia.org', 'hosts: [EN.Wikipedia.org'),
                 ("url: '{origin}/w/index.php?oldid={id}'", "url: '{origin}/w/index.php'"),
                 ('  revision_metadata:\n    default: blank\n', '')]
        for old, new in cases:
            with self.subTest(old), self.assertRaises(ProfileError):
                self.broken(old, new)()

    def test_scenario_options_are_validated_and_legacy_names_are_read(self):
        wikipedia = load('wikipedia')
        self.assertEqual(wikipedia.settings({'wikipedia': {'raw': 'native'}})['raw'], 'native')
        self.assertEqual(wikipedia.settings({'site_options': {'search': 'captured_corpus'}})['search'], 'captured_corpus')
        with self.assertRaises(ProfileError):
            wikipedia.settings({'site_options': {'raw': 'html'}})
        with self.assertRaises(ProfileError):
            wikipedia.settings({'site_options': {'colour': 'blue'}})
        with self.assertRaises(ProfileError):
            load('news').settings({'site_options': {'raw': 'native'}})

    def test_keys_paths_and_links_follow_each_profile(self):
        wikipedia, news = load('wikipedia'), load('news')
        self.assertEqual(wikipedia.key(' sam_altman '), 'Sam altman')
        self.assertEqual(wikipedia.url('AC/DC'), 'https://en.wikipedia.org/wiki/AC%2FDC')
        self.assertEqual(news.key('2026/09/17/lab-opens'), '2026/09/17/lab-opens')
        self.assertEqual(news.url('2026/09/17/lab-opens'), 'https://www.news.example/articles/2026/09/17/lab-opens')
        self.assertEqual(news.key_from_href('/articles/2026/09/17/lab-opens'), '2026/09/17/lab-opens')
        self.assertIsNone(news.key_from_href('/wiki/Oslo'))
        self.assertTrue(news.link_allowed('/articles/2026/09/18/budget-vote'))
        self.assertFalse(news.link_allowed('https://en.wikipedia.org/wiki/Oslo'))


class NewsWorldTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        fetcher = patch('sandbox.rewrite_capture.Capture.fetch', fetch)
        fetcher.start()
        self.addCleanup(fetcher.stop)
        self.root = Path(self.temp.name) / 'news'
        create(self.root, NEWS_SCENARIO, 'test')
        self.world = WorldService(self.root)
        self.addCleanup(self.world.close)

    def body(self, result):
        return base64.b64decode(result['body_base64']) if 'body_base64' in result else self.world.bytes(result['body'])

    def test_world_records_its_site_and_profile(self):
        config = json.loads((self.root / 'world.json').read_bytes())
        self.assertEqual(config['site'], {'id': 'news', 'profile_sha256': load('news').sha256})
        self.assertTrue((self.root / 'code-sites__news__site.yaml').exists())
        self.assertIn('Articles are captured as published at acquisition time; earlier versions are not recoverable.',
                      config['limitations'])

    def test_articles_feed_sitemap_and_search_derive_from_accepted_pages(self):
        page = self.world.handle('/articles/2026/09/17/lab-opens')
        self.assertEqual((page['status'], page['coverage']), (200, 'derived'))
        document = html.fromstring(self.body(page))
        self.assertEqual(document.xpath('string(//h1)'), 'Research lab opens in Oslo')
        # Metadata scripts the rewriter reviews survive capture; executable scripts do not.
        self.assertEqual(len(document.xpath('//script[@type="application/ld+json"]')), 1)
        self.assertNotIn(b'track()', self.body(page))
        self.world.handle('/articles/2026/09/18/budget-vote')
        stored = self.world.ensure('2026/09/17/lab-opens')
        self.assertEqual(stored['record']['timestamp'], '2026-09-17T06:00:00Z')
        self.assertEqual(stored['page']['source_url'], 'https://www.news.example/articles/2026/09/17/lab-opens')
        self.assertEqual(self.body(self.world.handle('/')).count(b'Top stories'), 1)
        feed = etree.fromstring(self.body(self.world.handle('/rss.xml')))
        self.assertEqual(feed.xpath('//item/title/text()'), ['Council approves budget', 'Research lab opens in Oslo'])
        self.assertEqual(feed.xpath('//item[1]/pubDate/text()'), ['Fri, 18 Sep 2026 10:00:00 GMT'])
        locations = etree.fromstring(self.body(self.world.handle('/sitemap.xml'))).xpath('//*[local-name()="loc"]/text()')
        self.assertEqual(len(locations), 2)
        results = html.fromstring(self.body(self.world.handle('/search?q=climate+models&limit=junk')))
        self.assertEqual(results.xpath('//li/a/@href'), ['/articles/2026/09/17/lab-opens'])

    def test_missing_and_future_articles_are_absent_from_the_world(self):
        for path in ('/articles/2026/09/01/never-written', '/articles/2026/09/20/later-story'):
            response = self.world.handle(path)
            self.assertEqual((response['status'], response['coverage']), (404, 'world_missing'), path)
            self.assertIn(b'Page not found | Example News', self.body(response))

    def test_routes_of_other_sites_get_this_sites_outage_page(self):
        response = self.world.handle('/w/api.php?action=query&titles=Oslo')
        self.assertEqual((response['status'], response['coverage']), (503, 'outside_snapshot'))
        self.assertIn(b"We're having trouble loading this page", self.body(response))
        self.assertNotIn(b'Wikimedia', self.body(response))

    def test_metadata_scripts_are_rewrite_surfaces_and_must_stay_valid(self):
        news = load('news')
        document = article('Old headline', '2026-09-17T08:00:00Z', ['Lead.', 'Body.'])
        fields = [(n['tag'], n['original']) for n in surfaces(html.fromstring(document), news)]
        self.assertTrue(any(tag == 'script' and 'Old headline' in value for tag, value in fields))
        self.assertFalse(any('track()' in value for _, value in fields))
        broken = document.replace(b'"headline": "Old headline"', b'"headline": "New headline')
        self.assertTrue(any('JSON' in issue['reason'] for issue in integrity_issues(news, document, broken)))
        self.assertEqual(integrity_issues(news, document, document), [])


class CrossSiteTests(unittest.TestCase):
    def test_one_bridge_serves_each_host_from_its_own_world(self):
        with tempfile.TemporaryDirectory() as temp, patch('sandbox.rewrite_capture.Capture.fetch', fetch):
            root = Path(temp)
            create(root / 'wiki', {**SCENARIO, 'condition': 'reference'}, 'test')
            create(root / 'news', NEWS_SCENARIO, 'test')
            wiki, news = WorldService(root / 'wiki', Source), WorldService(root / 'news')
            twin = WorldService(root / 'news')
            with self.assertRaisesRegex(ValueError, 'Two worlds serve host'):
                Worker([news, twin], root / 'duplicate')
            twin.close()
            worker = Worker([wiki, news], root / 'queue')
            try:
                def request(name, host, path):
                    publish(worker.queue / (name + '.request.json'), {'host': host, 'path': path, 'method': 'GET'})
                    output = worker.queue / (name + '.response.json')
                    until = time.monotonic() + 5
                    while not output.exists() and time.monotonic() < until:
                        time.sleep(.01)
                    return json.loads(output.read_bytes())
                encyclopedia = request('wiki', 'en.wikipedia.org', '/wiki/Monarchy')
                newspaper = request('news', 'www.news.example', '/articles/2026/09/18/budget-vote')
                stranger = request('stranger', 'example.org', '/wiki/Monarchy')
                self.assertEqual(encyclopedia['status'], 200)
                self.assertIn(b'Charles III', base64.b64decode(encyclopedia['body_base64']))
                self.assertEqual(newspaper['status'], 200)
                self.assertIn(b'Council approves budget', base64.b64decode(newspaper['body_base64']))
                self.assertEqual((stranger['status'], stranger['coverage']), (403, 'blocked'))
            finally:
                worker.close()
                wiki.close()
                news.close()


if __name__ == '__main__':
    unittest.main()
