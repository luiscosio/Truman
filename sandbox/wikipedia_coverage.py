"""Offline Wikipedia representations derived only from accepted world pages."""
import json
import re
from lxml import etree


def search_corpus(world,query,limit):
    """Deterministic AND-term search, explicitly scoped to the captured corpus.

    No task-specific queries, upstream rankings or unmodified source snippets.
    This deliberately does not claim MediaWiki's complete search syntax.
    """
    from sandbox.demand import CoverageMiss
    if len(query)>500 or re.search(r'\w+:',query):
        raise CoverageMiss('Search syntax outside captured-corpus support')
    terms=set(re.findall(r'\w+',query.casefold()))-{'a','an','the','of','in','from','and','is','at','to'}
    if not terms:return []
    ranked=[]
    for (raw,) in world.db.execute('SELECT value FROM pages ORDER BY key'):
        article=json.loads(raw)
        if article.get('missing'):continue
        title=article['page']['display_title']
        title_terms=set(re.findall(r'\w+',title.casefold()))
        text=world.bytes(article['text_blob']).decode().casefold()
        words=set(re.findall(r'\w+',text))
        if terms<=words|title_terms:
            ranked.append((len(terms&title_terms),title,article))
    ranked.sort(key=lambda item:(-item[0],item[1]))
    return [item[2] for item in ranked[:limit]]


def export_xml(world,articles):
    """MediaWiki export envelope for the accepted current revision of each page.

    The text uses the same accepted native source (or legacy DOM projection) as action=raw and the API.
    It never substitutes upstream originals for a rewritten page.
    """
    namespace='http://www.mediawiki.org/xml/export-0.11/'
    root=etree.Element('{'+namespace+'}mediawiki',nsmap={None:namespace},version='0.11')
    root.set('{http://www.w3.org/XML/1998/namespace}lang','en')
    def child(parent,name,text):
        node=etree.SubElement(parent,'{'+namespace+'}'+name);node.text=str(text);return node
    site=etree.SubElement(root,'{'+namespace+'}siteinfo')
    child(site,'sitename','Wikipedia');child(site,'base','https://en.wikipedia.org/wiki/Main_Page')
    for a in articles:
        if a.get('missing'):continue
        p=a['page'];r=a['record'];page=etree.SubElement(root,'{'+namespace+'}page')
        child(page,'title',p['display_title']);child(page,'ns',0);child(page,'id',p['page_id'])
        revision=etree.SubElement(page,'{'+namespace+'}revision')
        child(revision,'id',r['revid']);child(revision,'parentid',r.get('parentid',0));child(revision,'timestamp',r['timestamp'])
        # The schema requires a contributor; MediaWiki marks hidden users as deleted.
        contributor=etree.SubElement(revision,'{'+namespace+'}contributor')
        if r.get('user'):child(contributor,'username',r['user'])
        else:contributor.set('deleted','deleted')
        if r.get('comment'):child(revision,'comment',r['comment'])
        child(revision,'model','wikitext');child(revision,'format','text/x-wiki')
        text=world.bytes(a['text_blob']).decode();node=child(revision,'text',text)
        node.set('{http://www.w3.org/XML/1998/namespace}space','preserve');node.set('bytes',str(len(text.encode())))
    return etree.tostring(root,encoding='utf-8',xml_declaration=True)
