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
from sandbox.test_world_model import SCENARIO as WORLD_SCENARIO

DOC_WIKI = (b'<html><body><div class="mw-parser-output"><p>The Old Institute studies water.</p></div></body></html>')
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


def wordpress(headline, published, modified, body):
    """A page shaped like a Global Voices article: OpenGraph dates, h2 headline, div.entry prose."""
    return ('<!DOCTYPE html><html><head><title>' + headline + ' · Global Voices</title>'
            '<meta property="article:published_time" content="' + published + '">'
            '<meta property="article:modified_time" content="' + modified + '"></head>'
            '<body><main class="page-content-container"><h2 class="screen-title post-title">' + headline + '</h2>'
            '<div class="entry-container"><div class="entry">' + ''.join('<p>' + p + '</p>' for p in body) + '</div></div>'
            '<p><a href="/2026/09/20/earlier-story/">Earlier story</a> <a href="/category/caribbean/">Caribbean</a></p>'
            '</main></body></html>').encode()


PAGES.update({
    'https://globalvoices.org/': b'<!DOCTYPE html><html><body><main><p>Latest stories from around the world.</p></main></body></html>',
    'https://globalvoices.org/2026/09/21/seabed-rules/': wordpress(
        'What seabed rules mean for fishers', '2026-09-21T12:03:52+0000', '2026-10-01T11:46:37+0000',
        ['The International Seabed Authority meets in Kingston.', 'Fishers want a say.']),
    'https://globalvoices.org/2026/09/20/earlier-story/': wordpress(
        'An earlier story', '2026-09-20T08:00:00+0000', '2026-09-20T09:30:00+0000', ['Earlier text.']),
    'https://globalvoices.org/2026/10/02/tomorrow/': wordpress(
        'Not yet published', '2026-10-02T08:00:00+0000', '2026-10-02T08:00:00+0000', ['Future text.']),
})
GV_SCENARIO = {**NEWS_SCENARIO, 'id': 'gv-test', 'site': 'globalvoices', 'as_of': '2026-09-30'}


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


class GlobalVoicesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        fetcher = patch('sandbox.rewrite_capture.Capture.fetch', fetch)
        fetcher.start()
        self.addCleanup(fetcher.stop)
        create(Path(self.temp.name) / 'gv', GV_SCENARIO, 'test')
        self.world = WorldService(Path(self.temp.name) / 'gv')
        self.addCleanup(self.world.close)

    def body(self, result):
        return self.world.bytes(result['body'])

    def test_dated_slug_keys_links_and_canonical_paths(self):
        site = load('globalvoices')
        key = '2026/09/21/seabed-rules'
        self.assertEqual(site.path(key), '/2026/09/21/seabed-rules/')
        self.assertEqual((site.path('front'), site.url('front')), ('/', 'https://globalvoices.org/'))
        self.assertEqual(site.key_from_href('https://globalvoices.org/2026/09/21/seabed-rules/'), key)
        self.assertEqual(site.key_from_href('/2026/09/21/seabed-rules'), key)
        for other in ('/category/caribbean/', '/feed/', 'https://fr.globalvoices.org/2026/09/21/x/'):
            self.assertIsNone(site.key_from_href(other), other)
        self.assertTrue(site.link_allowed('/2026/09/20/earlier-story/'))
        self.assertFalse(site.link_allowed('/category/caribbean/'))
        redirect = self.world.handle('/2026/09/21/seabed-rules')
        self.assertEqual((redirect['status'], redirect['headers']), (301, {'Location': '/2026/09/21/seabed-rules/'}))

    def test_publication_decides_existence_and_later_edits_are_recorded(self):
        page = self.world.handle('/2026/09/21/seabed-rules/')
        self.assertEqual((page['status'], page['coverage']), (200, 'derived'))
        record = self.world.ensure('2026/09/21/seabed-rules')['record']
        self.assertEqual((record['published'], record['timestamp']), ('2026-09-21T12:03:52Z', '2026-09-21T12:03:52Z'))
        self.assertEqual((record['modified'], record['modified_after_cutoff']), ('2026-10-01T11:46:37Z', True))
        earlier = self.world.ensure('2026/09/20/earlier-story')['record']
        self.assertEqual(earlier['timestamp'], '2026-09-20T09:30:00Z')
        self.assertNotIn('modified_after_cutoff', earlier)
        future = self.world.handle('/2026/10/02/tomorrow/')
        self.assertEqual((future['status'], future['coverage']), (404, 'world_missing'))
        self.assertIn(b'404 ERROR: PAGE NOT FOUND', self.body(future))

    def test_site_routes_and_its_own_outage_page(self):
        self.world.handle('/2026/09/21/seabed-rules/')
        self.assertIn(b'Latest stories', self.body(self.world.handle('/')))
        results = html.fromstring(self.body(self.world.handle('/?s=fishers')))
        self.assertEqual(results.xpath('//li/a/@href'), ['/2026/09/21/seabed-rules/'])
        feed = etree.fromstring(self.body(self.world.handle('/feed/')))
        self.assertEqual(feed.xpath('//item/link/text()'), ['https://globalvoices.org/2026/09/21/seabed-rules/'])
        self.assertEqual(feed.xpath('//item/pubDate/text()'), ['Mon, 21 Sep 2026 12:03:52 GMT'])
        category = self.world.handle('/category/caribbean/')
        self.assertEqual((category['status'], category['evidence']), (503, {'reason': 'Path does not name a page'}))
        self.assertIn(b'<center>nginx</center>', self.world.bytes(category['body']) if 'body' in category else base64.b64decode(category['body_base64']))
        self.assertEqual(self.world.ensure('2026/09/21/seabed-rules')['text_format'], 'plain_text')


class NasaScienceTests(unittest.TestCase):
    def test_slug_paths_and_metadata_review_follow_the_profile(self):
        site = load('nasascience')
        self.assertEqual(site.url('dwarf-planets/pluto/facts'), 'https://science.nasa.gov/dwarf-planets/pluto/facts/')
        self.assertEqual(site.key_from_href('https://science.nasa.gov/dwarf-planets/pluto/'), 'dwarf-planets/pluto')
        self.assertIsNone(site.key_from_href('https://www.nasa.gov/image-article/x/'))
        self.assertEqual(site.rewrite['scripts'], ['application/ld+json'])

    def test_stylesheet_namespaces_are_not_fetched_as_assets(self):
        from sandbox.rewrite_capture import Capture
        stylesheet = b'@namespace m url(http://www.w3.org/1998/Math/MathML);.icon{background:url(/icon.png)}'
        fetched = []

        def fetch(capture, url):
            fetched.append(url)
            return stylesheet if url.endswith('.css') else b'png'
        with tempfile.TemporaryDirectory() as temp, patch.object(Capture, 'fetch', fetch):
            css = Capture(Path(temp), load('wikipedia')).css('https://en.wikipedia.org/style.css')
        self.assertEqual(fetched, ['https://en.wikipedia.org/style.css', 'https://en.wikipedia.org/icon.png'])
        self.assertIn('@namespace m url(http://www.w3.org/1998/Math/MathML)', css)

    def test_an_image_that_cannot_be_captured_keeps_its_original_url(self):
        from sandbox.archive import journal
        from sandbox.rewrite_capture import Capture, FetchError, TooLarge

        def fetch(capture, url):
            if url.endswith('big.gif'):
                raise TooLarge('Capture body too large')
            if url.endswith('throttled.gif'):
                raise FetchError(url, 22, 429)
            return b'png'
        page = (b'<html><body><div class="mw-parser-output"><p>Text</p><img src="//upload.wikimedia.org/big.gif">'
                b'<img src="/small.png"><img src="//upload.wikimedia.org/throttled.gif"></div></body></html>')
        with tempfile.TemporaryDirectory() as temp, patch.object(Capture, 'fetch', fetch):
            capture = Capture(Path(temp), load('wikipedia'))
            document, assets = capture.offline(page, 'https://en.wikipedia.org/wiki/Pluto')
            events = [e for e in journal(Path(temp) / 'http' / 'events.jsonl') if e['kind'] == 'asset_not_inlined']
        sources = html.fromstring(document).xpath('//img/@src')
        self.assertEqual(sources[0], 'https://upload.wikimedia.org/big.gif')
        self.assertTrue(sources[1].startswith('data:image/png'))
        self.assertEqual(sources[2], 'https://upload.wikimedia.org/throttled.gif')
        self.assertEqual(sorted((e['url'], e.get('status')) for e in events),
                         [('https://upload.wikimedia.org/big.gif', None), ('https://upload.wikimedia.org/throttled.gif', 429)])

    def test_oversized_images_are_refetched_resized_only_when_the_profile_allows(self):
        from sandbox.rewrite_capture import Capture, TooLarge
        calls = []

        def fetch(capture, url):
            calls.append(url)
            if 'w=1280' not in url:
                raise TooLarge('Capture body too large')
            return b'small'
        with tempfile.TemporaryDirectory() as temp, patch.object(Capture, 'fetch', fetch):
            self.assertTrue(Capture(Path(temp), load('nasascience')).asset('https://science.nasa.gov/a.jpg?x=1').startswith('data:image/jpeg'))
            self.assertEqual(calls, ['https://science.nasa.gov/a.jpg?x=1', 'https://science.nasa.gov/a.jpg?x=1&w=1280'])
            with self.assertRaises(TooLarge):
                Capture(Path(temp) / 'wiki', load('wikipedia')).asset('https://upload.wikimedia.org/a.jpg')


    def test_a_stylesheet_image_the_server_refuses_keeps_its_url(self):
        from sandbox.rewrite_capture import Capture, FetchError

        def fetch(capture, url):
            if url.endswith('.css'):
                return b'a{background:url(images/icon.png)} b{background:url("ok.png")}'
            if 'icon' in url:
                raise FetchError(url, 56, None)
            return b'png'
        with tempfile.TemporaryDirectory() as temp, patch.object(Capture, 'fetch', fetch):
            css = Capture(Path(temp), load('iau')).css('https://www.iau.org/Assets/css/site.css')
        self.assertIn('url("https://www.iau.org/Assets/css/images/icon.png")', css)
        self.assertIn('url("data:image/png;base64,', css)

    def test_an_image_too_long_to_parse_once_inlined_is_kept_remote(self):
        from sandbox.rewrite_capture import Capture, INLINE_LIMIT
        # Under the 8 MB capture budget, but over the parser limit once base64-encoded.
        with tempfile.TemporaryDirectory() as temp, patch.object(Capture, 'fetch', lambda capture, url: b'x' * (INLINE_LIMIT * 3 // 4)):
            capture = Capture(Path(temp), load('wikipedia'))
            self.assertEqual(capture.image('https://upload.wikimedia.org/big.png'), 'https://upload.wikimedia.org/big.png')
            events = [json.loads(line) for line in (Path(temp) / 'http' / 'events.jsonl').read_bytes().splitlines()]
            self.assertEqual([e['reason'] for e in events if e['kind'] == 'asset_not_inlined'], ['over capture budget'])

class LinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        fetcher = patch('sandbox.rewrite_capture.Capture.fetch', fetch)
        fetcher.start()
        self.addCleanup(fetcher.stop)
        availability = patch('sandbox.demand_availability.ask', return_value={'status': 'present', 'reason': 'Test topic', 'basis': []})
        availability.start()
        self.addCleanup(availability.stop)

    def world(self, name, scenario, source=None, writer=None):
        create(self.root / name, scenario, 'test')
        world = WorldService(self.root / name, source, writer or (lambda document, scenario, facts, *rest: (document, facts, [])))
        self.addCleanup(world.close)
        return world

    def test_only_worlds_sharing_a_specification_on_other_sites_link(self):
        wiki = self.world('wiki', WORLD_SCENARIO, Source)
        news = self.world('news', {**WORLD_SCENARIO, 'site': 'news'})
        other_spec = self.world('other', {**WORLD_SCENARIO, 'site': 'globalvoices', 'facts': ['Another rule.'],
                                          'world_model': {**WORLD_SCENARIO['world_model'], 'invariants': ['Different.']}})
        twin = self.world('twin', WORLD_SCENARIO, Source)
        with self.assertRaisesRegex(ValueError, 'share the world specification'):
            wiki.link(other_spec)
        with self.assertRaisesRegex(ValueError, 'different sites'):
            wiki.link(twin)
        reference = self.world('reference', {**WORLD_SCENARIO, 'site': 'globalvoices', 'condition': 'reference'})
        with self.assertRaisesRegex(ValueError, 'condition'):
            wiki.link(reference)
        wiki.link(news, news)
        self.assertEqual(wiki.linked, [news])

    def test_new_pages_are_reviewed_against_linked_worlds_with_their_own_site_rules(self):
        wiki = self.world('wiki', WORLD_SCENARIO, Source)
        news = self.world('news', {**WORLD_SCENARIO, 'site': 'news'})
        wiki.link(news)
        news.link(wiki)
        with patch('sandbox.demand_rewrite.review_peers') as review:
            news.ensure('2026/09/18/budget-vote')
        self.assertEqual(review.call_args.args[4], [])
        with patch('sandbox.demand_rewrite.review_peers') as review:
            wiki.ensure('Monarchy')
        peers = review.call_args.args[4]
        self.assertEqual([(p['site'].id, p['title']) for p in peers], [('news', '2026/09/18/budget-vote')])
        self.assertIn(b'Council approves budget', peers[0]['document'])
        context = json.loads(next((self.root / 'wiki' / 'attempts').glob('*/context.json')).read_bytes())
        self.assertEqual(context['linked_worlds'], [{'site': 'news', 'root': str(self.root / 'news')}])

    def test_cross_site_review_shows_each_page_through_its_own_profile(self):
        from sandbox.archive import Store
        from sandbox.demand_rewrite import review_peers
        news = load('news')
        calls = []

        def ask(store, scenario, role, stage, system, data, schema):
            calls.append((stage, data))
            return {'accepted': True, 'issues': []}
        peer = {'title': '2026/09/18/budget-vote', 'site': news, 'revision_at': '2026-09-18',
                'document': PAGES['https://www.news.example/articles/2026/09/18/budget-vote']}
        with patch('sandbox.demand_rewrite.ask', side_effect=ask):
            review_peers(DOC_WIKI, 'Old Institute', '2026-09-18', WORLD_SCENARIO, [peer], Store(self.root / 'audit'))
        stage, data = calls[0]
        self.assertTrue(stage.startswith('cross-page-news-2026_09_18_budget-vote'))
        self.assertEqual((data['committed']['site'], data['candidate']['site']), ('Example News', 'Wikipedia'))
        # The news profile reviews its JSON-LD metadata; executable scripts never reach review.
        self.assertIn('NewsArticle', json.dumps(data))
        self.assertNotIn('track()', json.dumps(data))


class FootnoteTests(unittest.TestCase):
    @staticmethod
    def marker(number):
        return ('<sup id="cite_ref-' + number + '" class="reference"><a href="#cite_note-' + number + '">'
                '<span class="cite-bracket">[</span>' + number + '<span class="cite-bracket">]</span></a></sup>')

    def page(self, body):
        notes = ''.join('<li id="cite_note-' + n + '"><span class="mw-cite-backlink"><a href="#cite_ref-' + n + '">^</a></span> Note ' + n + '</li>'
                        for n in ('1', '2', '3', '4'))
        return html.fromstring('<div class="mw-parser-output"><p>' + body + '</p><ol class="references">' + notes + '</ol></div>')

    def test_uncited_notes_are_dropped_and_markers_renumbered(self):
        from sandbox.demand_rewrite import cited_notes, reconcile_footnotes
        wikipedia = load('wikipedia')
        original = self.page('A' + self.marker('1') + ' B' + self.marker('2') + ' C' + self.marker('3') + '.')
        cited = cited_notes(original, wikipedia)
        # An edit unlinked marker 2; note 4 was never cited in the source and must stay.
        edited = self.page('A' + self.marker('1') + ' B<sup id="cite_ref-2" class="reference"><span>[</span>2<span>]</span></sup> C' + self.marker('3') + '.')
        log = reconcile_footnotes(edited, wikipedia, cited)
        self.assertEqual([entry['field'] for entry in log], ['footnote_marker', 'footnote'])
        self.assertEqual(edited.xpath('//li/@id'), ['cite_note-1', 'cite_note-3', 'cite_note-4'])
        self.assertEqual([m.text_content() for m in edited.xpath('//sup')], ['[1]', '[2]'])
        self.assertEqual(edited.xpath('string(//p)'), 'A[1] B C[2].')
        self.assertEqual(reconcile_footnotes(edited, wikipedia, cited), [])

    def test_page_locators_are_not_citation_markers(self):
        from sandbox.demand_rewrite import cited_notes, reconcile_footnotes
        wikipedia = load('wikipedia')
        locator = '<sup class="reference nowrap" typeof="mw:Transclusion"><span title="Page / location: 27">: 27</span></sup>'
        page = self.page('A' + self.marker('1') + locator + ' B' + self.marker('2') + ' C' + self.marker('3') + self.marker('4') + '.')
        before = etree.tostring(page)
        self.assertEqual(reconcile_footnotes(page, wikipedia, cited_notes(page, wikipedia)), [])
        self.assertEqual(etree.tostring(page), before)

    def test_sites_without_a_footnote_rule_are_untouched(self):
        from sandbox.demand_rewrite import reconcile_footnotes
        page = self.page('B<sup class="reference">[2]</sup>')
        before = etree.tostring(page)
        self.assertEqual(reconcile_footnotes(page, load('news'), {'cite_note-2'}), [])
        self.assertEqual(etree.tostring(page), before)


class RunnerWorldTests(unittest.TestCase):
    def test_runner_links_worlds_and_checks_the_site_policy(self):
        from sandbox.run import open_worlds, unrouted_hosts
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            create(root / 'wiki', WORLD_SCENARIO, 'image')
            create(root / 'gv', {**WORLD_SCENARIO, 'site': 'globalvoices'}, 'image')
            create(root / 'gv2', {**WORLD_SCENARIO, 'site': 'globalvoices'}, 'image')
            worlds = open_worlds([root / 'wiki', root / 'gv'])
            try:
                self.assertEqual([w.linked[0].site.id for w in worlds], ['globalvoices', 'wikipedia'])
                policy = json.loads(Path('network/sites.json').read_bytes())
                self.assertEqual(unrouted_hosts(worlds, policy), ['globalvoices.org'])
                policy['altered'].append({'hosts': ['globalvoices.org'], 'transport': 'world', 'reason': 'Test'})
                self.assertEqual(unrouted_hosts(worlds, policy), [])
            finally:
                for w in worlds:
                    w.close()
            with self.assertRaisesRegex(ValueError, 'one world per site'):
                open_worlds([root / 'gv', root / 'gv2'])


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
