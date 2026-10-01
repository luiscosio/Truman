"""MediaWiki representations of accepted world pages: API, REST, export and page actions.

Every response derives from accepted world pages; none substitutes an upstream
original for a rewritten page. Generic handlers live in sandbox/demand_routes.py.
"""
import copy
import difflib
import hashlib
import html as markup
import re
from urllib.parse import unquote, urlsplit
from lxml import etree, html

from sandbox.sites import load
from sandbox.sites.wikipedia.native import lead, rewrite_source as native_source
from sandbox.sites.wikipedia.source import WikipediaSource

EXPORT_NS = 'http://www.mediawiki.org/xml/export-0.11/'
REVISION_PROPS = {'ids', 'timestamp', 'user', 'comment', 'content', 'size', 'sha1', 'flags'}
RANGE_PARAMS = ('rvlimit', 'rvstart', 'rvend', 'rvstartid', 'rvendid', 'rvcontinue')

__all__ = ['WikipediaSource', 'native_source', 'project', 'export_xml']


def miss(reason):
    from sandbox.demand import CoverageMiss
    return CoverageMiss(reason)


# Representations

def project(tree):
    """Render-derived wikitext: HTML tables/prose plus native wiki links/headings.

    This intentionally does not claim to reconstruct original template source.
    Wikipedia accepts these HTML elements within wikitext.
    """
    site = load('wikipedia')
    root = copy.deepcopy(tree.xpath(site.content['body'])[0])
    for node in list(root.xpath('.//script|.//style|.//svg|.//noscript')):
        node.drop_tree()
    for node in root.iter():
        for attr in list(node.attrib):
            if attr not in ('href', 'src', 'alt', 'colspan', 'rowspan'):
                del node.attrib[attr]
    for node in list(root.xpath('.//a[@href]')):
        parts = urlsplit(node.get('href'))
        if parts.path.startswith('/wiki/') and site.internal(parts):
            title = unquote(parts.path[6:]).replace('_', ' ')
            label = ''.join(node.itertext())
            if not any(x in title + label for x in ('[[', ']]', '|')):
                node.text = '[[' + title + '|' + label + ']]'
                for child in list(node):
                    node.remove(child)
                node.drop_tag()
    for node in list(root.xpath('.//h2|.//h3|.//h4|.//h5|.//h6')):
        level = int(node.tag[1])
        node.text = '\n' + '=' * level + ' ' + ''.join(node.itertext()) + ' ' + '=' * level + '\n'
        for child in list(node):
            node.remove(child)
        node.drop_tag()
    return etree.tostring(root, encoding='unicode', method='html')


def export_xml(world, articles):
    """MediaWiki export envelope for the accepted current revision of each page.

    The text uses the same accepted native source (or legacy DOM projection) as action=raw and the API.
    """
    root = etree.Element('{' + EXPORT_NS + '}mediawiki', nsmap={None: EXPORT_NS}, version='0.11')
    root.set('{http://www.w3.org/XML/1998/namespace}lang', 'en')

    def child(parent, name, text):
        node = etree.SubElement(parent, '{' + EXPORT_NS + '}' + name)
        node.text = str(text)
        return node
    site = etree.SubElement(root, '{' + EXPORT_NS + '}siteinfo')
    child(site, 'sitename', world.site.name)
    child(site, 'base', world.site.url(world.site.resource['home']))
    for a in articles:
        if a.get('missing'):
            continue
        p, r = a['page'], a['record']
        page = etree.SubElement(root, '{' + EXPORT_NS + '}page')
        child(page, 'title', p['display_title'])
        child(page, 'ns', 0)
        child(page, 'id', p['page_id'])
        revision = etree.SubElement(page, '{' + EXPORT_NS + '}revision')
        child(revision, 'id', r['revid'])
        child(revision, 'parentid', r.get('parentid', 0))
        child(revision, 'timestamp', r['timestamp'])
        # The schema requires a contributor; MediaWiki marks hidden users as deleted.
        contributor = etree.SubElement(revision, '{' + EXPORT_NS + '}contributor')
        if r.get('user'):
            child(contributor, 'username', r['user'])
        else:
            contributor.set('deleted', 'deleted')
        if r.get('comment'):
            child(revision, 'comment', r['comment'])
        child(revision, 'model', 'wikitext')
        child(revision, 'format', 'text/x-wiki')
        text = world.bytes(a['text_blob']).decode()
        node = child(revision, 'text', text)
        node.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
        node.set('bytes', str(len(text.encode())))
    return etree.tostring(root, encoding='utf-8', xml_declaration=True)


# Page actions

def export_page(ctx):
    title = ctx.param('title')
    names = (ctx.vars.get('titles') or (title[len('Special:Export/'):] if title.startswith('Special:Export/') else '')
             or ctx.param('pages')).split('\n')
    if not names[0] or len(names) > 10:
        raise miss('Supply 1-10 export titles')
    articles = [ctx.world.ensure(name) for name in names]
    return ctx.out(export_xml(ctx.world, articles), mime='application/xml; charset=utf-8',
                   coverage='world_missing' if all(a.get('missing') for a in articles) else 'derived')


def search_page(ctx):
    root = etree.Element('html')
    head = etree.SubElement(root, 'head')
    etree.SubElement(head, 'title').text = 'Search results' + ctx.site.content['title_suffix']
    content = etree.SubElement(root, 'body')
    etree.SubElement(content, 'h1').text = 'Search results'
    for a in ctx.world.search(ctx.param('search'), ctx.value('limit')):
        if a.get('missing'):
            continue
        p = etree.SubElement(content, 'p')
        etree.SubElement(p, 'a', href=ctx.site.url(a['page']['display_title'])).text = a['page']['display_title']
        etree.SubElement(content, 'p').text = ctx.extract(a, True)[:300]
    return ctx.out(etree.tostring(root, encoding='utf-8', method='html'), mime='text/html; charset=utf-8')


def history_page(ctx):
    article = ctx.resource()
    if article.get('missing'):
        return ctx.html(article)
    versions = ctx.world.history_metadata(article['title'], ctx.value('limit'))
    tree = html.fromstring(ctx.world.bytes(article['html_blob']), parser=html.HTMLParser(encoding='utf-8'))
    root = tree.xpath(ctx.site.content['body'])[0]
    root.clear()
    etree.SubElement(root, 'h2').text = 'Revision history'
    for r in versions:
        p = etree.SubElement(root, 'p')
        link = etree.SubElement(p, 'a', href='/w/index.php?oldid=' + str(r['revid']))
        link.text = r['timestamp']
        link.tail = ' ' + r.get('user', '') + ' ' + r.get('comment', '')
    return ctx.out(etree.tostring(tree, encoding='utf-8', method='html'), mime='text/html; charset=utf-8')


def rest_summary(ctx):
    a = ctx.world.ensure(ctx.vars['key'])
    if a.get('missing'):
        return ctx.out({'type': 'https://mediawiki.org/wiki/HyperSwitch/errors/not_found', 'title': 'Not found'}, 404,
                       coverage='world_missing')
    p = a['page']
    return ctx.out({'type': 'standard', 'title': p['display_title'], 'pageid': p['page_id'],
                    'extract': ctx.extract(a, True), 'timestamp': p['revision_at'],
                    'content_urls': {'desktop': {'page': ctx.site.url(p['display_title'])}}}, proof=p)


# Action API

def api_siteinfo(ctx):
    wanted = ctx.param('siprop', 'general').split('|')
    if not set(wanted) <= {'general', 'namespaces', 'statistics'}:
        raise miss('Unsupported siteinfo property')
    data = ctx.world.cached_operation('siteinfo', lambda source: source.api(
        action='query', meta='siteinfo', siprop='general|namespaces|statistics')['query'])
    return ctx.out({'batchcomplete': '', 'query': {k: data[k] for k in wanted}})


def api_search(ctx):
    results = []
    for a in ctx.world.search(ctx.param('srsearch'), ctx.value('srlimit')):
        if a.get('missing'):
            continue
        p = a['page']
        results.append({'ns': 0, 'pageid': p['page_id'], 'title': p['display_title'],
                        'snippet': ctx.extract(a, True)[:300], 'size': len(ctx.world.bytes(a['text_blob'])),
                        'timestamp': p['revision_at']})
    return ctx.out({'batchcomplete': '', 'query': {'searchinfo': {'totalhits': len(results)}, 'search': results}})


def api_compare(ctx):
    first = ctx.world.revision(ctx.parse('fromrev', ctx.param('fromrev')))
    second = ctx.world.revision(ctx.parse('torev', ctx.param('torev')))
    a = ctx.world.bytes(first['text_blob']).decode().splitlines()
    b = ctx.world.bytes(second['text_blob']).decode().splitlines()
    diff = difflib.HtmlDiff().make_table(a, b, context=True)
    return ctx.out({'compare': {'fromrevid': first['record']['revid'], 'torevid': second['record']['revid'], '*': diff}})


def api_pages(ctx):
    """action=parse and action=query over 1-10 pages or revisions."""
    if ctx.has('revids'):
        articles = [ctx.world.revision(ctx.parse('revids', x)) for x in ctx.param('revids').split('|')]
        names = [a['title'] for a in articles]
    else:
        names = ctx.param('titles', ctx.param('page')).split('|')
        if not names[0] or len(names) > 10:
            raise miss('Supply 1-10 titles')
        articles = [ctx.world.ensure(unquote(name)) for name in names]
    action = ctx.param('action', 'query')
    if action == 'query' and ctx.has('export'):
        xml = export_xml(ctx.world, articles)
        if ctx.has('exportnowrap'):
            return ctx.out(xml, mime='application/xml; charset=utf-8')
        return ctx.out({'query': {'export': {'*': xml.decode()}}})
    if action == 'parse':
        return parse(ctx, articles[0])
    return query(ctx, names, articles)


def parse(ctx, a):
    if a.get('missing'):
        return ctx.out({'error': {'code': 'missingtitle', 'info': 'The page does not exist.'}}, coverage='world_missing')
    prop = ctx.param('prop', 'text').split('|')
    parsed = {'title': a['page']['display_title'], 'pageid': a['page']['page_id']}
    if not set(prop) <= {'text', 'wikitext', 'revid'}:
        raise miss('Unsupported parse property')
    section = ctx.param('section')
    if section not in ('', '0'):
        raise miss('Unsupported parse section')
    if 'text' in prop:
        root = ctx.body(a)
        if section == '0':
            sections = root.xpath(ctx.site.content['lead'])
            if not sections:
                raise miss('Lead section unavailable')
            root = sections[0]
        parsed['text'] = {'*': etree.tostring(root, encoding='unicode', method='html')}
    if 'wikitext' in prop:
        text = ctx.world.bytes(a['text_blob']).decode()
        if section == '0':
            # A projected page has no source lead; its prose lead is the closest.
            text = lead(text) if a.get('text_format') == 'native_wikitext' else ctx.extract(a, True)
        parsed['wikitext'] = {'*': text}
    if 'revid' in prop:
        parsed['revid'] = a['record']['revid']
    return ctx.out({'parse': parsed}, proof=a['page'])


def query(ctx, names, articles):
    props = ctx.param('prop', 'info').split('|')
    if not set(props) <= {'info', 'extracts', 'revisions'}:
        raise miss('Unsupported query property')
    enumerating = 'revisions' in props and (any(ctx.has(k) for k in RANGE_PARAMS) or ctx.param('rvdir') == 'newer')
    if enumerating and len(names) > 1:
        raise ctx.invalid('invalidparammix')
    v2 = ctx.param('formatversion') == '2'
    pages = []
    redirects = []
    continuation = None
    for index, (name, a) in enumerate(zip(names, articles)):
        if a.get('missing'):
            pages.append({'pageid': -index - 1, 'ns': 0, 'title': a['title'], 'missing': True if v2 else ''})
            continue
        p = a['page']
        info = {'pageid': p['page_id'], 'ns': 0, 'title': p['display_title']}
        if name.replace('_', ' ') != p['display_title']:
            redirects.append({'from': name, 'to': p['display_title']})
        if 'info' in props:
            info.update(lastrevid=p['revision_id'], touched=p['revision_at'], length=len(ctx.world.bytes(a['text_blob'])),
                        contentmodel='wikitext', pagelanguage='en')
        if 'extracts' in props:
            text = ctx.extract(a, ctx.has('exintro'))
            info['extract'] = text if ctx.has('explaintext') else '<p>' + markup.escape(text).replace('\n\n', '</p><p>') + '</p>'
        if 'revisions' in props:
            info['revisions'], more = revisions(ctx, a, enumerating, v2)
            continuation = more or continuation
        pages.append(info)
    payload = {'batchcomplete': '', 'query': {'pages': pages if v2 else {str(p['pageid']): p for p in pages}}}
    if continuation:
        # MediaWiki omits batchcomplete while a continuation is pending.
        payload = {'continue': continuation, 'query': payload['query']}
    if redirects:
        payload['query']['redirects'] = redirects
    return ctx.out(payload, coverage='world_missing' if all(a.get('missing') for a in articles) else 'derived')


def revisions(ctx, article, enumerating, v2):
    requested = ctx.param('rvprop', 'ids|timestamp').split('|')
    if not set(requested) <= REVISION_PROPS:
        raise miss('Unsupported revision property')
    needs_content = bool(set(requested) & {'content', 'size', 'sha1'})
    continuation = None
    if enumerating:
        chosen, continuation = enumerate_revisions(ctx, article)
        versions = [ctx.world.ensure(article['title'], r['revid']) if needs_content else {'record': r} for r in chosen]
    else:
        versions = [article]
    records = []
    for version in versions:
        if version.get('missing'):
            continue
        r = version['record']
        rev = {}
        text = ctx.world.bytes(version['text_blob']).decode() if needs_content else ''
        for field in ('timestamp', 'user', 'comment'):
            if field in requested:
                rev[field] = r.get(field, '')
        if 'ids' in requested:
            rev.update(revid=r['revid'], parentid=r.get('parentid', 0))
        if 'content' in requested:
            content = {'contentmodel': 'wikitext', 'contentformat': 'text/x-wiki', 'content' if v2 else '*': text}
            if ctx.has('rvslots'):
                rev['slots'] = {'main': content}
            else:
                rev['content' if v2 else '*'] = text
        if 'size' in requested:
            rev['size'] = len(text.encode())
        if 'sha1' in requested:
            rev['sha1'] = hashlib.sha1(text.encode()).hexdigest()
        records.append(rev)
    return records, continuation


def stamp(value):
    return int(re.sub(r'[^0-9]', '', value))


def enumerate_revisions(ctx, article):
    """rvdir/rvstart/rvend/rvstartid/rvendid/rvcontinue over the widest known history window."""
    from sandbox.demand import CoverageMiss
    direction = ctx.value('rvdir')
    older = direction == 'older'
    count = ctx.value('rvlimit')
    start, end = ctx.value('rvstart'), ctx.value('rvend')
    startid, endid = ctx.value('rvstartid'), ctx.value('rvendid')
    cont = ctx.param('rvcontinue')
    world = ctx.world
    try:
        records, complete = world.history_window(article['title'])
    except CoverageMiss:
        # Without a prepared window, the newest revision is still known.
        if not (older and count == 1 and start is None and startid is None and not cont):
            raise
        records, complete = [dict(article['record'])], True
    for newer, parent in zip(records, records[1:]):
        newer.setdefault('parentid', parent['revid'])

    def sign(value):
        return value if older else -value

    def reached(r):
        return ((start is None or sign(stamp(r['timestamp'])) <= sign(stamp(start)))
                and (startid is None or sign(r['revid']) <= sign(startid)))

    def within(r):
        return ((end is None or sign(stamp(r['timestamp'])) >= sign(stamp(end)))
                and (endid is None or sign(r['revid']) >= sign(endid)))
    ordered = records if older else records[::-1]
    selected = [r for r in ordered if reached(r) and within(r)]
    token = cont.rpartition('|')[2]
    ids = [str(r['revid']) for r in selected]
    if cont and token in ids:
        selected = selected[ids.index(token):]
    # The window may stop before the first revision. Newer-first ranges must start
    # inside it; older-first ranges must end inside it or already fill the limit.
    beyond = not complete and ordered and ((not older and reached(ordered[0]))
                                           or (older and within(ordered[-1]) and len(selected) < count))
    if (cont and token not in ids) or beyond:
        if complete or not ordered:
            raise ctx.invalid('badcontinue')
        cutoff = world.config['source_cutoff']
        params = {'rvdir': direction, 'rvlimit': count + 1}
        if older:
            params['rvstart'] = min(start or cutoff, cutoff)
        else:
            params['rvend'] = min(end or cutoff, cutoff)
        for name, value in (('rvend', end if older else None), ('rvstart', None if older else start),
                            ('rvstartid', startid), ('rvendid', endid), ('rvcontinue', cont or None)):
            if value is not None:
                params[name] = value
        selected = world.history_range(article['title'], params)
        if older:
            for newer, parent in zip(selected, selected[1:]):
                newer.setdefault('parentid', parent['revid'])
    more = selected[count] if len(selected) > count else None
    return selected[:count], ({'rvcontinue': str(stamp(more['timestamp'])) + '|' + str(more['revid']), 'continue': '||'}
                              if more else None)
