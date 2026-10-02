"""Bounded automatic link exploration and route checks before freezing a world."""
import argparse
import json
import re
from collections import deque
from pathlib import Path
from urllib.parse import quote
from lxml import html
from sandbox.archive import durable, encoded, sha
from sandbox.demand import HISTORY_CONTENT, WorldService


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
            if article.get('validation_status')=='unvalidated_diagnostic':
                results.append({'title':title,'status':'failed','error':'Unvalidated diagnostic seed; regenerate before preparation'});continue
            if article.get('missing'):
                results.append({'title':title,'status':'world_missing'});continue
            q=quote(article['page']['display_title'],safe='')
            paths=[path.replace('{title}',q).replace('{path}',world.site.path(article['title'])) for path in world.site.prepare['paths']]
            routes=[{'path':path,'status':world.handle(path)['status']} for path in paths]
            results.append({'title':title,'status':'ready' if all(r['status']==200 for r in routes) else 'route_failed','routes':routes})
            if level<depth:
                links=[]
                skip=world.site.prepare.get('skip_keys')
                for href in html.fromstring(world.bytes(article['html_blob']),parser=html.HTMLParser(encoding='utf-8')).xpath('//a/@href'):
                    name=world.site.key_from_href(href)
                    if name and not (skip and re.search(skip,name)) and world.resolve(name) not in seen:links.append(name)
                known={e['source_title'] for e in world.scenario.get('world_model',{}).get('entities',[])}
                links=sorted(set(links),key=lambda n:(world.resolve(n) not in known,n))
                queue.extend((n,level+1) for n in links)
        except Exception as exc:results.append({'title':title,'status':'failed','error':str(exc)})
    remaining=sorted({world.resolve(n) for n,_ in queue}-seen)
    ready=not remaining and all(r['status'] in ('ready','world_missing') for r in results)
    return {'status':'ready' if ready else 'incomplete','scope':{'seeds':seeds,'depth':depth,'max_pages':max_pages},
            'world_sha256':sha(encoded(world.scenario.get('world_model',{}))),
            'pages':results,'unvisited':remaining,
            'limitations':'Coverage is only for the declared seeds, link depth and the site profile\'s checked route forms; it is not the whole internet.'}


def prepare_history(world,titles,window,anchors):
    """Old revisions a frozen world can serve: a wide metadata window and dated captures.

    For each page, caches `window` revisions of metadata and captures the last
    revision before each anchor date. Other revisions in the window are served from
    the nearest earlier capture (WorldService.nearest_capture).
    """
    if world.readonly:raise ValueError('Preparation requires a growing world')
    if not 1<=window<=500:raise ValueError('History window must be 1-500 revisions')
    results=[]
    for title in titles:
        key=world.resolve(title)
        try:
            records=world.history_metadata(key,window)
            captured=[]
            for anchor in sorted(anchors):
                before=[r for r in records if r['timestamp']<anchor]
                if not before:
                    captured.append({'anchor':anchor,'status':'before_window'});continue
                revision=max(before,key=lambda r:r['timestamp'])
                version=world.ensure(key,revision['revid'])
                captured.append({'anchor':anchor,'revid':revision['revid'],'timestamp':revision['timestamp'],
                                 'status':'missing' if version.get('missing') else 'captured'})
            results.append({'title':key,'window':len(records),'oldest':records[-1]['timestamp'] if records else None,
                            'anchors':captured,'status':'ready' if all(c['status']=='captured' for c in captured) else 'incomplete'})
        except Exception as exc:results.append({'title':key,'status':'failed','error':str(exc)})
    with world.db:world.db.execute('INSERT OR REPLACE INTO cache VALUES (?,?)',(HISTORY_CONTENT,json.dumps('nearest_capture')))
    return {'status':'ready' if all(r['status']=='ready' for r in results) else 'incomplete','window':window,
            'anchors':sorted(anchors),'pages':results}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--world',type=Path,required=True)
    seeds=p.add_mutually_exclusive_group(required=True)
    seeds.add_argument('--pages',nargs='+');seeds.add_argument('--from-run',type=Path,help='Prepare the exact recorded request paths, including API and history forms')
    p.add_argument('--max-pages',type=int,default=12)
    p.add_argument('--depth',type=int,default=1);p.add_argument('--report',type=Path,required=True)
    p.add_argument('--link',type=Path,action='append',default=[],
                   help='World on another site sharing this specification; new pages are reviewed against it')
    p.add_argument('--history-window',type=int,help='With --pages: cache this many revisions of metadata per page')
    p.add_argument('--anchor',action='append',default=[],help='With --history-window: capture the last revision before this date (repeatable)')
    p.add_argument('--freeze',type=Path);a=p.parse_args();world=WorldService(a.world)
    linked=[WorldService(path) for path in a.link]
    try:
        world.link(*linked)
        if a.from_run:
            from sandbox.archive import verify
            verify(a.from_run)
            requests=[e['path'] for e in json.loads((a.from_run/'run.json').read_bytes())['network_requests']
                      if e.get('host',world.site.hosts[0]) in world.site.hosts]
            rows=[]
            for path in requests:
                result=world.handle(path)
                rows.append({'path':path,'status':result['status'],'coverage':result['coverage']})
                print(json.dumps(rows[-1]),flush=True)
            report={'status':'ready' if all(r['status']==200 or r['coverage']=='world_missing' for r in rows) else 'incomplete',
                    'source_run':str(a.from_run),'requests':rows}
        elif a.history_window:report=prepare_history(world,a.pages,a.history_window,a.anchor)
        else:report=prepare(world,a.pages,a.max_pages,a.depth)
        durable(a.report,encoded(report))
        if a.freeze:
            if report['status']!='ready':raise ValueError('Declared preparation scope is incomplete; see report')
            print(world.freeze(a.freeze))
        print(json.dumps({'status':report['status'],'pages':len(report.get('pages',[])),'unvisited':len(report.get('unvisited',[]))}))
    finally:
        for w in [world,*linked]:w.close()


if __name__=='__main__':main()
