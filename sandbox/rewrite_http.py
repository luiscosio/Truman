"""Deterministic Wikipedia read routes for original-HTML replay worlds."""
import json
from urllib.parse import parse_qs, unquote, urlsplit
from lxml import html, etree
from sandbox.archive import read_blob
from truman.world import title_key, wiki_url
from sandbox.rewrite_capture import CONTENT


def response(world, target):
    parts = urlsplit(target); query = parse_qs(parts.query, keep_blank_values=True)
    snapshot = world.snapshot
    aliases = snapshot.get('aliases', {})
    def key(value):
        normalized = title_key(value)
        return aliases.get(normalized, normalized)
    def number(name, default, maximum):
        raw = query.get(name, [str(default)])[0]
        return maximum if raw == 'max' else min(maximum, max(1, int(raw)))
    def document(k):
        return read_blob(world.root, snapshot['articles'][k]['html_blob'])
    def content(k):
        return html.fromstring(document(k)).xpath(CONTENT)[0]
    def reply(value, page=None):
        return 200, 'application/json; charset=utf-8', json.dumps(value, ensure_ascii=False).encode(), page, {}, 'derived'
    def unknown():
        return 404, 'text/html; charset=utf-8', b'<!doctype html><title>Not found</title><h1>Not found</h1>', None, {}, 'outside_snapshot'
    try:
        if parts.path in ('/', '/wiki/Special:Random'):
            k = 'Main Page' if parts.path == '/' else sorted(world.pages)[0]
            return 302, 'text/plain', b'', None, {'Location': wiki_url(k)}, 'derived'
        if parts.path == '/w/api.php':
            action = query.get('action', ['query'])[0]
            if action == 'query' and query.get('meta') == ['siteinfo']:
                wanted = query.get('siprop', ['general'])[0].split('|')
                if any(x not in snapshot['siteinfo'] for x in wanted):
                    return unknown()
                return reply({'batchcomplete': '', 'query': {p:snapshot['siteinfo'][p] for p in wanted}})
            if action == 'query' and query.get('list') == ['search']:
                words = query.get('srsearch', [''])[0].casefold().split()
                matches = [k for k in sorted(world.pages) if words and all(w in (k+' '+world._text[k]).casefold() for w in words)]
                matches = matches[:number('srlimit', 10, 50)]
                return reply({'batchcomplete':'', 'query': {'searchinfo':{'totalhits':len(matches)}, 'search':[
                    {'ns':0,'title':world.pages[k].get('display_title',k),'pageid':world.pages[k]['page_id'],'size':len(world._text[k].encode()),
                     'wordcount':len(world._text[k].split()),'snippet':'','timestamp':world.pages[k]['revision_at']} for k in matches]}})
            names = query.get('titles', query.get('page', ['']))[0].split('|')
            if len(names)>50 or not names[0]:
                return unknown()
            keys = [key(n) for n in names]
            if any(k not in world.pages for k in keys):
                return unknown()
            if action == 'parse':
                k=keys[0]; tree=content(k)
                return reply({'parse':{'title':world.pages[k].get('display_title',world.pages[k]['title']),'pageid':world.pages[k]['page_id'],
                    'text':{'*':etree.tostring(tree,encoding='unicode',method='html')}}}, world.pages[k])
            if action != 'query' or 'list' in query or 'meta' in query:
                return unknown()
            props=query.get('prop',['revisions'])[0].split('|')
            if not set(props)<={'revisions','extracts','info'}:
                return unknown()
            output=[]
            for k in keys:
                page=world.pages[k]; article=snapshot['articles'][k]
                info={'pageid':page['page_id'],'ns':0,'title':page.get('display_title',page['title'])}
                if 'info' in props:
                    info.update(contentmodel='wikitext',pagelanguage='en',lastrevid=page['revision_id'],
                        touched=page['revision_at'],length=len(world._text[k].encode()))
                if 'extracts' in props:
                    tree=content(k)
                    for node in tree.xpath('.//script|.//style|.//sup[contains(@class,"reference")]|.//table|.//div[contains(@class,"reflist")]'):
                        node.drop_tree()
                    paragraphs=tree.xpath('.//p')
                    if 'exintro' in query:
                        # Parsoid wraps the lead in section[data-mw-section-id=0].
                        lead=tree.xpath('./section[@data-mw-section-id="0"]')
                        if lead:
                            paragraphs=lead[0].xpath('.//p')
                        else:
                            paragraphs=paragraphs[:3]
                    info['extract']='\n\n'.join(p.text_content().strip() for p in paragraphs if p.text_content().strip()) if 'explaintext' in query else ''.join(etree.tostring(p,encoding='unicode',method='html') for p in paragraphs)
                if 'revisions' in props:
                    requested=query.get('rvprop',['ids|timestamp'])[0].split('|')
                    if not set(requested)<={'ids','timestamp','user','comment','content','size','sha1','flags'}:
                        return unknown()
                    records=article['revisions'][:number('rvlimit',1,50)]
                    revision_list=[]
                    for record in records:
                        rev={}
                        for field in ('timestamp','user','comment'):
                            if field in requested and field in record: rev[field]=record[field]
                        if 'ids' in requested:rev.update(revid=record['revid'],parentid=record.get('parentid',0))
                        text=read_blob(world.root,record['source_blob']).decode()
                        if 'size' in requested:rev['size']=len(text.encode())
                        if 'sha1' in requested:
                            import hashlib
                            rev['sha1']=hashlib.sha1(text.encode()).hexdigest()
                        if 'content' in requested:
                            if 'rvslots' in query:rev['slots']={'main':{'*':text,'contentmodel':'wikitext','contentformat':'text/x-wiki'}}
                            else:rev['*']=text
                        revision_list.append(rev)
                    info['revisions']=revision_list
                output.append(info)
            payload={'batchcomplete':'','query':{'pages':output if query.get('formatversion')==['2'] else {str(p['pageid']):p for p in output}}}
            redirects=[{'from':name,'to':world.pages[k].get('display_title',world.pages[k]['title'])} for name,k in zip(names,keys) if name!=world.pages[k].get('display_title',world.pages[k]['title'])]
            if redirects:payload['query']['redirects']=redirects
            return reply(payload, world.pages[keys[0]] if len(keys)==1 else None)
        if parts.path.startswith('/wiki/'):
            k=key(unquote(parts.path[6:]))
        elif parts.path == '/w/index.php':
            if 'oldid' in query:
                revision=int(query['oldid'][0])
                matches=[k for k,a in snapshot['articles'].items() if a['page']['revision_id']==revision]
                if not matches:
                    original=[k for k,a in snapshot['articles'].items() if a.get('original',{}).get('revision_id')==revision]
                    if original:
                        return 200,'text/html; charset=utf-8',read_blob(world.root,snapshot['articles'][original[0]]['source_html_blob']),None,{},'derived'
                    return unknown()
                k=matches[0]
            else:k=key(query.get('title',[''])[0])
        else:return unknown()
        if k not in world.pages:return unknown()
        if query.get('action')==['raw']:
            return 200,'text/plain; charset=utf-8',world._text[k].encode(),world.pages[k],{},'derived'
        if 'action' in query and query['action']!=['view']:
            return unknown()
        return 200,'text/html; charset=utf-8',document(k),world.pages[k],{},'derived'
    except (ValueError, KeyError, IndexError):
        return unknown()
