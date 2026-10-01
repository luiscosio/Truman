"""One read adapter for growing and frozen worlds; no direct network access here."""
import datetime as dt
import difflib
import hashlib
import json
import re
from urllib.parse import parse_qs, unquote, urlsplit
from lxml import html, etree
from sandbox.rewrite_capture import CONTENT
from truman.world import wiki_url


class InvalidRequest(ValueError):
    """A request MediaWiki itself rejects, answered with its own API error code."""
    def __init__(self,code,info):super().__init__(info);self.code=code


DOCREF=('See https://en.wikipedia.org/w/api.php for API usage. Subscribe to the mediawiki-api-announce mailing list at '
        '&lt;https://lists.wikimedia.org/postorius/lists/mediawiki-api-announce.lists.wikimedia.org/&gt; '
        'for notice of API deprecations and breaking changes.')
# One transient-outage page for every surface. Misses and failed generations must
# not have a bespoke status or body; the precise reason stays in the evidence.
OUTAGE=(b'<!DOCTYPE html>\n<html lang="en">\n<meta charset="utf-8">\n<title>Wikimedia Error</title>\n'
        b'<style>*{margin:0;padding:0}body{background:#fff;font:15px/1.6 sans-serif;color:#333}'
        b'.content{margin:7% auto 0;padding:2em 1em 1em;max-width:640px}h1{font-size:2em;font-weight:normal;margin-bottom:.5em}'
        b'p{margin-top:1em}.footer{padding:0 1em;max-width:640px;margin:0 auto;color:#555;font-size:.9em}</style>\n'
        b'<div class="content" role="main">\n<h1>Error</h1>\n<p>Our servers are currently under maintenance or experiencing a '
        b'technical issue. Please <a href="" title="Reload this page" onclick="window.location.reload(false); return false">try again</a> '
        b'in a few minutes.</p>\n</div>\n<div class="footer"><p>If you report this error to the Wikimedia System Administrators, '
        b'please include the details below.</p><p><code>Error: 503, Service Unavailable</code></p></div>\n</html>\n')


def outage(coverage,reason):
    return 503,'text/html; charset=utf-8',OUTAGE,{},coverage,{'reason':reason}


def respond(world,target):
    from sandbox.demand import CoverageMiss, NeedsGeneration
    parts=urlsplit(target);q=parse_qs(parts.query,keep_blank_values=True)
    def param(name,default=''):return q.get(name,[default])[0]
    def stamp(value):return int(re.sub(r'[^0-9]','',value))
    def integer(name,value):
        if not re.fullmatch(r'[+-]?[0-9]+',value):raise InvalidRequest('badinteger','Invalid value "'+value+'" for integer parameter "'+name+'".')
        return int(value)
    def revision_id(name,value):
        number=integer(name,value)
        if number<1:raise InvalidRequest('nosuchrevid','There is no revision with ID '+str(number)+'.')
        return number
    def number(name,default,cap,api=True):
        # MediaWiki clamps out-of-range limits; index.php ignores unparsable ones.
        raw=param(name,str(default))
        if raw=='max':return cap
        if not api and not re.fullmatch(r'[0-9]+',raw):return default
        return min(max(integer(name,raw),1),cap)
    def timestamp(name):
        raw=param(name)
        try:
            value=dt.datetime.strptime(raw,'%Y%m%d%H%M%S') if re.fullmatch(r'[0-9]{14}',raw) else dt.datetime.fromisoformat(raw.replace('Z','+00:00'))
            if value.tzinfo:value=value.astimezone(dt.timezone.utc)
            return value.strftime('%Y-%m-%dT%H:%M:%SZ')
        except ValueError:raise InvalidRequest('badtimestamp','Invalid value "'+raw+'" for timestamp parameter "'+name+'".')
    def enumerate_revisions(article):
        """rvdir/rvstart/rvend/rvstartid/rvendid/rvcontinue over the widest known history window."""
        direction=param('rvdir','older')
        if direction not in ('older','newer'):raise InvalidRequest('badvalue','Unrecognized value for parameter "rvdir": '+direction+'.')
        older=direction=='older';count=number('rvlimit',10,50)
        start=timestamp('rvstart') if param('rvstart') else None;end=timestamp('rvend') if param('rvend') else None
        startid=integer('rvstartid',param('rvstartid')) if param('rvstartid') else None
        endid=integer('rvendid',param('rvendid')) if param('rvendid') else None
        try:records,complete=world.history_window(article['title'])
        except CoverageMiss:
            # Without a prepared window, the newest revision is still known.
            if not (older and count==1 and start is None and startid is None and not param('rvcontinue')):raise
            records,complete=[dict(article['record'])],True
        for newer,parent in zip(records,records[1:]):newer.setdefault('parentid',parent['revid'])
        def sign(value):return value if older else -value
        def reached(r):return (start is None or sign(stamp(r['timestamp']))<=sign(stamp(start))) and (startid is None or sign(r['revid'])<=sign(startid))
        def within(r):return (end is None or sign(stamp(r['timestamp']))>=sign(stamp(end))) and (endid is None or sign(r['revid'])>=sign(endid))
        ordered=records if older else records[::-1]
        selected=[r for r in ordered if reached(r) and within(r)]
        token=param('rvcontinue').rpartition('|')[2];ids=[str(r['revid']) for r in selected]
        if param('rvcontinue') and token in ids:selected=selected[ids.index(token):]
        # The window may stop before the first revision. Newer-first ranges must start
        # inside it; older-first ranges must end inside it or already fill the limit.
        if (param('rvcontinue') and token not in ids) or (not complete and ordered and (
                (not older and reached(ordered[0])) or (older and within(ordered[-1]) and len(selected)<count))):
            if complete or not ordered:raise InvalidRequest('badcontinue','Invalid continue param. You should pass the original value returned by the previous query.')
            cutoff=world.config['source_cutoff']
            params={'rvdir':direction,'rvlimit':count+1}
            if older:params['rvstart']=min(start or cutoff,cutoff)
            else:params['rvend']=min(end or cutoff,cutoff)
            for name,value in (('rvend',end if older else None),('rvstart',None if older else start),
                               ('rvstartid',startid),('rvendid',endid),('rvcontinue',param('rvcontinue') or None)):
                if value is not None:params[name]=value
            selected=world.history_range(article['title'],params)
            if older:
                for newer,parent in zip(selected,selected[1:]):newer.setdefault('parentid',parent['revid'])
        more=selected[count] if len(selected)>count else None
        return selected[:count],({'rvcontinue':str(stamp(more['timestamp']))+'|'+str(more['revid']),'continue':'||'} if more else None)
    def out(value,status=200,mime='application/json; charset=utf-8',coverage='derived',proof=None,headers=None):
        return status,mime,(json.dumps(value,ensure_ascii=False).encode() if not isinstance(value,bytes) else value),headers or {},coverage,proof
    def body(article):return html.fromstring(world.bytes(article['html_blob']),parser=html.HTMLParser(encoding='utf-8')).xpath(CONTENT)[0]
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
        export_title=unquote(parts.path[6:]) if parts.path.startswith('/wiki/') else param('title') if parts.path=='/w/index.php' else ''
        if export_title=='Special:Export' or export_title.startswith('Special:Export/'):
            from sandbox.wikipedia_coverage import export_xml
            names=(export_title[len('Special:Export/'): ] if export_title.startswith('Special:Export/') else param('pages')).split('\n')
            if not names[0] or len(names)>10:raise CoverageMiss('Supply 1-10 export titles')
            articles=[world.ensure(name) for name in names]
            return out(export_xml(world,articles),mime='application/xml; charset=utf-8',coverage='world_missing' if all(a.get('missing') for a in articles) else 'derived')
        if (parts.path=='/w/index.php' and 'search' in q) or export_title=='Special:Search':
            root=etree.Element('html');head=etree.SubElement(root,'head');etree.SubElement(head,'title').text='Search results - Wikipedia'
            content=etree.SubElement(root,'body');etree.SubElement(content,'h1').text='Search results'
            for a in world.search(param('search'),number('limit',10,50,api=False)):
                if a.get('missing'):continue
                p=etree.SubElement(content,'p');etree.SubElement(p,'a',href=wiki_url(a['page']['display_title'])).text=a['page']['display_title']
                etree.SubElement(content,'p').text=extract(a,True)[:300]
            return out(etree.tostring(root,encoding='utf-8',method='html'),mime='text/html; charset=utf-8')
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
                hits=world.search(param('srsearch'),number('srlimit',5,50));results=[]
                for a in hits:
                    if a.get('missing'):continue
                    p=a['page'];results.append({'ns':0,'pageid':p['page_id'],'title':p['display_title'],
                        'snippet':extract(a,True)[:300],'size':len(world.bytes(a['text_blob'])),'timestamp':p['revision_at']})
                return out({'batchcomplete':'','query':{'searchinfo':{'totalhits':len(results)},'search':results}})
            if action=='compare':
                first=world.revision(revision_id('fromrev',param('fromrev')));second=world.revision(revision_id('torev',param('torev')))
                a=world.bytes(first['text_blob']).decode().splitlines();b=world.bytes(second['text_blob']).decode().splitlines()
                diff=difflib.HtmlDiff().make_table(a,b,context=True)
                return out({'compare':{'fromrevid':first['record']['revid'],'torevid':second['record']['revid'],'*':diff}})
            if 'list' in q or 'meta' in q:raise CoverageMiss('Unsupported API list')
            if action not in ('query','parse'):raise CoverageMiss('Unsupported API action')
            if 'revids' in q:
                articles=[world.revision(revision_id('revids',x)) for x in param('revids').split('|')]
                names=[a['title'] for a in articles]
            else:
                names=param('titles',param('page')).split('|')
                if not names[0] or len(names)>10:raise CoverageMiss('Supply 1-10 titles')
                articles=[world.ensure(unquote(name)) for name in names]
            if action=='query' and 'export' in q:
                from sandbox.wikipedia_coverage import export_xml
                xml=export_xml(world,articles)
                if 'exportnowrap' in q:return out(xml,mime='application/xml; charset=utf-8')
                return out({'query':{'export':{'*':xml.decode()}}})
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
                        if a.get('text_format')=='native_wikitext':
                            from sandbox.wikipedia_native import lead
                            parsed['wikitext']={'*':lead(world.bytes(a['text_blob']).decode())}
                        else:parsed['wikitext']={'*':extract(a,True)}
                    else:parsed['wikitext']={'*':world.bytes(a['text_blob']).decode()}
                if 'revid' in prop:parsed['revid']=a['record']['revid']
                return out({'parse':parsed},proof=a['page'])
            props=param('prop','info').split('|')
            if not set(props)<={'info','extracts','revisions'}:raise CoverageMiss('Unsupported query property')
            enumerating='revisions' in props and (any(k in q for k in ('rvlimit','rvstart','rvend','rvstartid','rvendid','rvcontinue')) or param('rvdir')=='newer')
            if enumerating and len(names)>1:
                raise InvalidRequest('invalidparammix','"titles", "pageids" or a generator was used to supply multiple pages, but the "rvlimit", '
                    '"rvstartid", "rvendid", "rvdir=newer", "rvuser", "rvexcludeuser", "rvstart", and "rvend" parameters may only be used on a single page.')
            pages=[];redirects=[];payload_continue=None
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
                    requested=param('rvprop','ids|timestamp').split('|')
                    if not set(requested)<={'ids','timestamp','user','comment','content','size','sha1','flags'}:raise CoverageMiss('Unsupported revision property')
                    needs_content=bool(set(requested)&{'content','size','sha1'})
                    if enumerating:
                        chosen,continuation=enumerate_revisions(a)
                        if continuation:payload_continue=continuation
                        versions=[world.ensure(a['title'],r['revid']) if needs_content else {'record':r} for r in chosen]
                    else:versions=[a]
                    records=[]
                    for version in versions:
                        if version.get('missing'):continue
                        r=version['record'];rev={};text=world.bytes(version['text_blob']).decode() if needs_content else ''
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
            if payload_continue:payload={'continue':payload_continue,**{k:v for k,v in payload.items() if k!='batchcomplete'}}
            if redirects:payload['query']['redirects']=redirects
            return out(payload,coverage='world_missing' if all(a.get('missing') for a in articles) else 'derived')
        if parts.path.startswith('/wiki/'):
            title=unquote(parts.path[6:])
            if title.startswith('Special:'):raise CoverageMiss('Unsupported special page')
            article=world.ensure(title)
        elif parts.path=='/w/index.php':
            # MediaWiki treats a blank or malformed oldid as the current revision.
            oldid=param('oldid')
            article=world.revision(int(oldid)) if re.fullmatch(r'[0-9]+',oldid) and int(oldid) else world.ensure(param('title') or 'Main Page')
        else:raise CoverageMiss('Unsupported Wikipedia route')
        if article.get('missing'):return article_html(article)
        action=param('action','view')
        if action=='raw':return out(world.bytes(article['text_blob']),mime='text/plain; charset=utf-8',proof=article['page'])
        if action=='history':
            versions=world.history_metadata(article['title'],number('limit',10,50,api=False));tree=html.fromstring(world.bytes(article['html_blob']),parser=html.HTMLParser(encoding='utf-8'))
            root=tree.xpath(CONTENT)[0];root.clear()
            heading=etree.SubElement(root,'h2');heading.text='Revision history'
            for r in versions:
                p=etree.SubElement(root,'p');link=etree.SubElement(p,'a',href='/w/index.php?oldid='+str(r['revid']))
                link.text=r['timestamp'];link.tail=' '+r.get('user','')+' '+r.get('comment','')
            return out(etree.tostring(tree,encoding='utf-8',method='html'),mime='text/html; charset=utf-8')
        if action!='view':raise CoverageMiss('Unsupported action')
        return article_html(article)
    except NeedsGeneration:
        raise
    except InvalidRequest as exc:
        return out({'error':{'code':exc.code,'info':str(exc),'*':DOCREF}},headers={'MediaWiki-API-Error':exc.code},coverage='invalid_request',proof={'reason':str(exc)})
    except CoverageMiss as exc:
        return outage('outside_snapshot',str(exc))
    except Exception as exc:
        # Never return an unmodified original on failed generation/validation.
        return outage('generation_failed',type(exc).__name__+': '+str(exc))
