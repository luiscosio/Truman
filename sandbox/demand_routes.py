"""One read adapter for growing and frozen worlds; no direct network access here."""
import difflib
import hashlib
import json
from urllib.parse import parse_qs, unquote, urlsplit
from lxml import html, etree
from sandbox.rewrite_capture import CONTENT
from truman.world import wiki_url


def respond(world,target):
    from sandbox.demand import CoverageMiss
    parts=urlsplit(target);q=parse_qs(parts.query,keep_blank_values=True)
    def param(name,default=''):return q.get(name,[default])[0]
    def number(name,default,cap):
        raw=param(name,str(default));value=cap if raw=='max' else int(raw)
        if not 1<=value<=cap:raise CoverageMiss('Requested limit exceeds supported budget')
        return value
    def out(value,status=200,mime='application/json; charset=utf-8',coverage='derived',proof=None,headers=None):
        return status,mime,(json.dumps(value,ensure_ascii=False).encode() if not isinstance(value,bytes) else value),headers or {},coverage,proof
    def body(article):return html.fromstring(world.bytes(article['html_blob'])).xpath(CONTENT)[0]
    def extract(article,intro=False):
        root=body(article)
        for node in list(root.xpath('.//style|.//script|.//table|.//sup|.//div[contains(@class,"reflist")]')):
            if node.getparent() is not None:node.drop_tree()
        if intro:
            lead=root.xpath('./section[@data-mw-section-id="0"]')
            paragraphs=lead[0].xpath('.//p') if lead else root.xpath('.//p')[:3]
        else:paragraphs=root.xpath('.//p')
        return '\n\n'.join(p.text_content().strip() for p in paragraphs if p.text_content().strip())
    def article_html(article):
        if article.get('missing'):return out(b'<!doctype html><title>Not found</title><h1>Page not found</h1>',404,'text/html; charset=utf-8',coverage='world_missing')
        return out(world.bytes(article['html_blob']),mime='text/html; charset=utf-8',proof=article['page'])
    try:
        if len(target)>12000 or parts.scheme or parts.netloc:raise CoverageMiss('Invalid request target')
        if parts.path.startswith('/w/resources/'):
            key=parts.path.rsplit('/',1)[1]
            asset=world.read('cache','asset:'+key)
            if not asset:raise CoverageMiss('Resource outside captured world')
            return out(world.bytes(asset['blob']),mime=asset['mime'])
        if parts.path=='/':return out(b'',302,'text/plain',headers={'Location':wiki_url('Main Page')})
        if parts.path.startswith('/api/rest_v1/page/summary/'):
            a=world.ensure(unquote(parts.path[len('/api/rest_v1/page/summary/'):]))
            if a.get('missing'):return out({'type':'https://mediawiki.org/wiki/HyperSwitch/errors/not_found','title':'Not found'},404,coverage='world_missing')
            p=a['page'];return out({'type':'standard','title':p['display_title'],'pageid':p['page_id'],
                'extract':extract(a,True),'timestamp':p['revision_at'],'content_urls':{'desktop':{'page':wiki_url(p['display_title'])}}},proof=p)
        if parts.path=='/w/api.php':
            action=param('action','query')
            if action=='query' and param('meta')=='siteinfo':
                wanted=param('siprop','general').split('|')
                if not set(wanted)<={'general','namespaces','statistics'}:raise CoverageMiss('Unsupported siteinfo property')
                data=world.cached_operation('siteinfo',lambda source:source.api(action='query',meta='siteinfo',siprop='general|namespaces|statistics')['query'])
                return out({'batchcomplete':'','query':{k:data[k] for k in wanted}})
            if action=='query' and param('list')=='search':
                hits=world.search(param('srsearch'),number('srlimit',5,10));results=[]
                for a in hits:
                    if a.get('missing'):continue
                    p=a['page'];results.append({'ns':0,'pageid':p['page_id'],'title':p['display_title'],
                        'snippet':extract(a,True)[:300],'size':len(world.bytes(a['text_blob'])),'timestamp':p['revision_at']})
                return out({'batchcomplete':'','query':{'searchinfo':{'totalhits':len(results)},'search':results}})
            if action=='compare':
                first=world.revision(int(param('fromrev')));second=world.revision(int(param('torev')))
                a=world.bytes(first['text_blob']).decode().splitlines();b=world.bytes(second['text_blob']).decode().splitlines()
                diff=difflib.HtmlDiff().make_table(a,b,context=True)
                return out({'compare':{'fromrevid':first['record']['revid'],'torevid':second['record']['revid'],'*':diff}})
            if 'list' in q or 'meta' in q:raise CoverageMiss('Unsupported API list')
            if action not in ('query','parse'):raise CoverageMiss('Unsupported API action')
            if 'revids' in q:
                articles=[world.revision(int(x)) for x in param('revids').split('|')]
                names=[a['title'] for a in articles]
            else:
                names=param('titles',param('page')).split('|')
                if not names[0] or len(names)>10:raise CoverageMiss('Supply 1-10 titles')
                articles=[world.ensure(unquote(name)) for name in names]
            if action=='parse':
                a=articles[0]
                if a.get('missing'):return out({'error':{'code':'missingtitle','info':'The page does not exist.'}},coverage='world_missing')
                prop=param('prop','text').split('|');parsed={'title':a['page']['display_title'],'pageid':a['page']['page_id']}
                if not set(prop)<={'text','wikitext','revid'}:raise CoverageMiss('Unsupported parse property')
                if param('section') not in ('','0'):raise CoverageMiss('Unsupported parse section')
                if 'text' in prop:
                    root=body(a)
                    if param('section')=='0':
                        sections=root.xpath('./section[@data-mw-section-id="0"]')
                        if not sections:raise CoverageMiss('Lead section unavailable')
                        root=sections[0]
                    parsed['text']={'*':etree.tostring(root,encoding='unicode',method='html')}
                if 'wikitext' in prop:
                    if param('section')=='0':
                        # A DOM-derived lead projection, not the complete article.
                        parsed['wikitext']={'*':extract(a,True)}
                    else:parsed['wikitext']={'*':world.bytes(a['text_blob']).decode()}
                if 'revid' in prop:parsed['revid']=a['record']['revid']
                return out({'parse':parsed},proof=a['page'])
            props=param('prop','info').split('|')
            if not set(props)<={'info','extracts','revisions'}:raise CoverageMiss('Unsupported query property')
            pages=[];redirects=[]
            for index,(name,a) in enumerate(zip(names,articles)):
                if a.get('missing'):
                    pages.append({'pageid':-index-1,'ns':0,'title':a['title'],'missing':True if param('formatversion')=='2' else ''});continue
                p=a['page'];info={'pageid':p['page_id'],'ns':0,'title':p['display_title']}
                if name.replace('_',' ')!=p['display_title']:redirects.append({'from':name,'to':p['display_title']})
                if 'info' in props:info.update(lastrevid=p['revision_id'],touched=p['revision_at'],length=len(world.bytes(a['text_blob'])),contentmodel='wikitext',pagelanguage='en')
                if 'extracts' in props:
                    text=extract(a,'exintro' in q)
                    info['extract']=text if 'explaintext' in q else '<p>'+__import__('html').escape(text).replace('\n\n','</p><p>')+'</p>'
                if 'revisions' in props:
                    if any(k in q for k in ('rvstart','rvend','rvstartid','rvendid','rvdir','rvcontinue')):raise CoverageMiss('Revision filtering is not supported yet')
                    count=number('rvlimit',1,5)
                    versions=[a] if count==1 else world.history(a['title'],count)
                    requested=param('rvprop','ids|timestamp').split('|')
                    if not set(requested)<={'ids','timestamp','user','comment','content','size','sha1','flags'}:raise CoverageMiss('Unsupported revision property')
                    records=[]
                    for version in versions:
                        if version.get('missing'):continue
                        r=version['record'];rev={};text=world.bytes(version['text_blob']).decode()
                        for field in ('timestamp','user','comment'):
                            if field in requested:rev[field]=r.get(field,'')
                        if 'ids' in requested:rev.update(revid=r['revid'],parentid=r.get('parentid',0))
                        if 'content' in requested:
                            content={'contentmodel':'wikitext','contentformat':'text/x-wiki','content' if param('formatversion')=='2' else '*':text}
                            if 'rvslots' in q:rev['slots']={'main':content}
                            else:rev['content' if param('formatversion')=='2' else '*']=text
                        if 'size' in requested:rev['size']=len(text.encode())
                        if 'sha1' in requested:rev['sha1']=hashlib.sha1(text.encode()).hexdigest()
                        records.append(rev)
                    info['revisions']=records
                pages.append(info)
            payload={'batchcomplete':'','query':{'pages':pages if param('formatversion')=='2' else {str(p['pageid']):p for p in pages}}}
            if redirects:payload['query']['redirects']=redirects
            return out(payload,coverage='world_missing' if all(a.get('missing') for a in articles) else 'derived')
        if parts.path.startswith('/wiki/'):
            title=unquote(parts.path[6:])
            if title.startswith('Special:'):raise CoverageMiss('Unsupported special page')
            article=world.ensure(title)
        elif parts.path=='/w/index.php':
            article=world.revision(int(param('oldid'))) if 'oldid' in q else world.ensure(param('title'))
        else:raise CoverageMiss('Unsupported Wikipedia route')
        if article.get('missing'):return article_html(article)
        action=param('action','view')
        if action=='raw':return out(world.bytes(article['text_blob']),mime='text/plain; charset=utf-8',proof=article['page'])
        if action=='history':
            versions=world.history(article['title'],number('limit',5,5));tree=html.fromstring(world.bytes(article['html_blob']))
            root=tree.xpath(CONTENT)[0];root.clear()
            heading=etree.SubElement(root,'h2');heading.text='Revision history'
            for a in versions:
                if a.get('missing'):continue
                p=etree.SubElement(root,'p');r=a['record'];link=etree.SubElement(p,'a',href='/w/index.php?oldid='+str(r['revid']))
                link.text=r['timestamp'];link.tail=' '+r.get('user','')+' '+r.get('comment','')
            return out(etree.tostring(tree,encoding='utf-8',method='html'),mime='text/html; charset=utf-8')
        if action!='view':raise CoverageMiss('Unsupported action')
        return article_html(article)
    except CoverageMiss as exc:
        return out({'error':{'code':'unavailable','info':'Requested resource is unavailable.'}},409,coverage='outside_snapshot')
    except Exception as exc:
        # Never return an unmodified original on failed generation/validation.
        return out({'error':{'code':'temporarily_unavailable','info':'Please retry later.'}},503,coverage='generation_failed')
