"""Bounded automatic link exploration and route checks before freezing a world."""
import argparse
import json
from collections import deque
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
from lxml import html
from sandbox.archive import durable, encoded, sha
from sandbox.demand import WorldService


def prepare(world,seeds,max_pages=12,depth=1):
    if world.readonly:raise ValueError('Preparation requires a growing world')
    if not 1<=max_pages<=100 or not 0<=depth<=3:raise ValueError('Invalid exploration budget')
    if not seeds:raise ValueError('Supply at least one starting page')
    queue=deque((s,0) for s in seeds);seen=set();results=[]
    while queue and len(seen)<max_pages:
        title,level=queue.popleft();key=world.resolve(title)
        if key in seen:continue
        seen.add(key)
        try:
            article=world.ensure(title)
            if article.get('missing'):
                results.append({'title':title,'status':'world_missing'});continue
            q=quote(article['page']['display_title'],safe='')
            paths=['/wiki/'+q,'/api/rest_v1/page/summary/'+q,
                   '/w/api.php?action=query&prop=extracts|revisions&explaintext=1&titles='+q,
                   '/w/api.php?action=parse&prop=wikitext&page='+q,
                   '/w/index.php?action=raw&title='+q]
            routes=[{'path':path,'status':world.handle(path)['status']} for path in paths]
            results.append({'title':title,'status':'ready' if all(r['status']==200 for r in routes) else 'route_failed','routes':routes})
            if level<depth:
                links=[]
                for href in html.fromstring(world.bytes(article['html_blob']),parser=html.HTMLParser(encoding='utf-8')).xpath('//a/@href'):
                    url=urlsplit(href)
                    if url.hostname in (None,'en.wikipedia.org') and url.path.startswith('/wiki/'):
                        name=unquote(url.path[6:]).replace('_',' ')
                        if ':' not in name and world.resolve(name) not in seen:links.append(name)
                known={e['source_title'] for e in world.scenario.get('world_model',{}).get('entities',[])}
                links=sorted(set(links),key=lambda n:(world.resolve(n) not in known,n))
                queue.extend((n,level+1) for n in links)
        except Exception as exc:results.append({'title':title,'status':'failed','error':str(exc)})
    remaining=sorted({world.resolve(n) for n,_ in queue}-seen)
    ready=not remaining and all(r['status'] in ('ready','world_missing') for r in results)
    return {'status':'ready' if ready else 'incomplete','scope':{'seeds':seeds,'depth':depth,'max_pages':max_pages},
            'world_sha256':sha(encoded(world.scenario.get('world_model',{}))),
            'pages':results,'unvisited':remaining,
            'limitations':'Coverage is only for the declared seeds, link depth and five checked route forms; it is not the whole internet.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--world',type=Path,required=True)
    seeds=p.add_mutually_exclusive_group(required=True)
    seeds.add_argument('--pages',nargs='+');seeds.add_argument('--from-run',type=Path,help='Prepare the exact recorded request paths, including API and history forms')
    p.add_argument('--max-pages',type=int,default=12)
    p.add_argument('--depth',type=int,default=1);p.add_argument('--report',type=Path,required=True)
    p.add_argument('--freeze',type=Path);a=p.parse_args();world=WorldService(a.world)
    try:
        if a.from_run:
            from sandbox.archive import verify
            verify(a.from_run)
            requests=[e['path'] for e in json.loads((a.from_run/'run.json').read_bytes())['network_requests']]
            rows=[]
            for path in requests:
                result=world.handle(path)
                rows.append({'path':path,'status':result['status'],'coverage':result['coverage']})
                print(json.dumps(rows[-1]),flush=True)
            report={'status':'ready' if all(r['status']==200 or r['coverage']=='world_missing' for r in rows) else 'incomplete',
                    'source_run':str(a.from_run),'requests':rows}
        else:report=prepare(world,a.pages,a.max_pages,a.depth)
        durable(a.report,encoded(report))
        if a.freeze:
            if report['status']!='ready':raise ValueError('Declared preparation scope is incomplete; see report')
            print(world.freeze(a.freeze))
        print(json.dumps({'status':report['status'],'pages':len(report.get('pages',[])),'unvisited':len(report.get('unvisited',[]))}))
    finally:world.close()


if __name__=='__main__':main()
