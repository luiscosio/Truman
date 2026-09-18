"""Replay original captures through new world compilers without changing evidence."""
import argparse
import copy
import json
import sqlite3
import time
from pathlib import Path
from sandbox.archive import Store, encoded, durable, journal, read_blob, seal, verify
from sandbox.demand import create, WorldService
from sandbox.demand_world import compile_world, normalize
from sandbox.demand_benchmark import usage
from sandbox.demand_prepare import prepare


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-world',type=Path,required=True)
    p.add_argument('--scenario',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--max-tokens',type=int,default=32768)
    p.add_argument('--models',nargs='+',default=['claude-sonnet-5','claude-opus-5']);a=p.parse_args()
    original_seal=verify(a.source_world);a.output.mkdir(parents=True,exist_ok=False)
    captures={};db=sqlite3.connect(a.source_world.joinpath('world.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
    try:
        for raw, in db.execute('SELECT value FROM pages ORDER BY key'):
            page=json.loads(raw)
            if page.get('missing'):continue
            attempt=a.source_world/'attempts'/page['attempt']
            event=next(e for e in journal(attempt/'events.jsonl') if e['kind']=='original')
            meta=json.loads((attempt/'original.json').read_bytes())
            captures[page['title']]={**meta,'document':read_blob(attempt,event['html_blob']),
                                     'source':read_blob(attempt,event['source_blob']).decode()}
    finally:db.close()
    class Source:
        def __init__(self,*args):pass
        def acquire(self,title,revision=None):return captures[title]
    scenario=json.loads(a.scenario.read_bytes());scenario['source_titles']=list(captures)
    scenario['generators']={'b':{'model':'claude-opus-5','effort':'high','max_tokens':a.max_tokens}}
    audit=Store(a.output/'compilation')
    try:
        if 'world_model' in scenario:
            compiled=normalize(scenario);audit.event('reused_compiled_scenario',source=str(a.scenario))
        else:compiled=compile_world(scenario,audit)
        durable(a.output/'scenario.json',encoded(compiled))
    finally:seal(audit.root)
    print('Compiled captured-world scenario',flush=True);results=[]
    for model in a.models:
        s=copy.deepcopy(compiled);s['generators']['b']['model']=model
        root=a.output/model;create(root,s,'recorded-original-capture');world=WorldService(root,Source);start=time.monotonic()
        try:
            report=prepare(world,list(captures),max_pages=len(captures),depth=0)
            digest=world.freeze(a.output/(model+'-frozen'))
            for title, in world.db.execute('SELECT key FROM pages'):
                page=world.read('pages',title)
                if not page.get('missing'):durable(a.output/(model+'-'+str(page['page']['page_id'])+'.html'),world.bytes(page['html_blob']))
        finally:world.close()
        result={'model':model,'seconds':time.monotonic()-start,'preparation':report,'usage':usage(root),'seal':digest}
        durable(a.output/(model+'-result.json'),encoded(result));results.append(result)
        print(json.dumps({'model':model,'status':report['status'],'seconds':round(result['seconds']),'calls':result['usage']['calls']}),flush=True)
    if verify(a.source_world)!=original_seal:raise ValueError('Original evidence changed')
    durable(a.output/'results.json',encoded({'source_seal':original_seal,'results':results,'compilation_usage':usage(a.output/'compilation')}))
    if any(r['preparation']['status']!='ready' for r in results):raise SystemExit(2)


if __name__=='__main__':main()
