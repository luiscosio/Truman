"""Build matched original/edited worlds from reviewed current and historic captures.

No model calls and no target-question inputs. All directories must be new.
History metadata and article bytes are pinned to the same source revisions.
"""
import argparse
import copy
import json
from pathlib import Path
import shutil
import subprocess
from urllib.parse import quote
from lxml import html
from sandbox.archive import durable,encoded,sha,seal,verify,read_blob
from sandbox.demand import create,WorldService
from sandbox.sites.wikipedia.handlers import project
from sandbox.demand_integrity import integrity_issues
from sandbox.sites import load
WIKIPEDIA=load('wikipedia')

TITLES=['OpenAI','Elon Musk','Sam Altman','ChatGPT']


def main():
 p=argparse.ArgumentParser(description=__doc__)
 for name in ('sources','candidates','metadata','output'):p.add_argument('--'+name,type=Path,required=True)
 p.add_argument('--history-sources',type=Path,action='append',default=[])
 p.add_argument('--history-candidates',type=Path,action='append',default=[])
 p.add_argument('--limit',type=int,default=15)
 a=p.parse_args();assert 1<=a.limit<=50
 a.output.mkdir(parents=True,exist_ok=False)
 verify(a.sources);verify(a.metadata)
 recipe=Path(__file__).resolve().parent;scenario=json.loads((recipe/'scenario.json').read_text())
 renderer=subprocess.check_output(['docker','image','inspect','truman-network-world:local','--format','{{.Id}}'],text=True).strip()
 rows=[]
 for i,title in enumerate(TITLES):
  records=json.loads((a.metadata/title.replace(' ','_')/'history.json').read_text())[:a.limit]
  for number,record in enumerate(records):
   rev=record['revid']
   source=a.sources/str(i) if number==0 else next((root/str(i)/str(rev) for root in reversed(a.history_sources) if (root/str(i)/str(rev)/'original.json').exists()),None)
   candidates=a.candidates if number==0 else next((root/str(i)/str(rev) for root in reversed(a.history_candidates) if (root/str(i)/str(rev)/f'{i}-review.json').exists()),None)
   if source is None or candidates is None:raise ValueError(('Missing reviewed revision',title,rev))
   source_seal=verify(source);meta=json.loads((source/'original.json').read_text());assert meta['record']['revid']==rev
   original=read_blob(source/'audit',meta['document_blob']);candidate=(candidates/f'{i}-candidate.html').read_bytes()
   review=json.loads((candidates/f'{i}-review.json').read_text())
   assert review['source_html_sha256']==sha(original) and review['candidate_html_sha256']==sha(candidate)
   assert not integrity_issues(WIKIPEDIA,original,candidate)
   rows.append(dict(index=i,title=title,current=number==0,source=source,source_seal=source_seal,meta=meta,original=original,candidate=candidate,review=review))
 summary={'history_limit':a.limit,'titles':TITLES,'worlds':{},'limitations':['Wikipedia only; search covers accepted captured articles, not all Wikipedia.','Raw/API/export text is the existing DOM projection, not original template source.','History contains only the declared recent revision window; unsupported filters/continuation remain coverage misses.','Both conditions omit usernames/comments to match metadata treatment.','Counterfactual historical patches are manually reviewed recipe transfers; no independent semantic reviewer.']}
 for condition in ('reference','synthetic'):
  config=copy.deepcopy(scenario);config['id']+='-'+condition+'-coverage';config['condition']=condition
  config['wikipedia']={'search':'captured_corpus'}
  if condition=='reference':
   config['facts']=['Preserve the captured source articles and their history without changing factual content.']
   config['world_model']={'version':1,'entities':[e for e in config['world_model']['entities'] if e['exists']],'facts':[],'invariants':config['facts'],'preserve':['All captured article content'],'unknowns':[]}
  world_path=a.output/(condition+'-growing');create(world_path,config,renderer);w=WorldService(world_path)
  try:
   for row in rows:
    meta=row['meta'];document=w.assets(row['original'] if condition=='reference' else row['candidate'])
    text=project(html.fromstring(document,parser=html.HTMLParser(encoding='utf-8')))
    record={**meta['record'],'comment':'','user':''};title=row['title'];attempt,store=w.attempt()
    shutil.copytree(row['source'],attempt/'original-capture')
    durable(attempt/'review.json',encoded({'condition':condition,'source_seal':row['source_seal'],'review':row['review'] if condition=='synthetic' else 'Unchanged original article; same offline asset and text projection transformations.'}))
    page={'title':title,'display_title':title,'page_id':meta['page_id'],'revision_id':record['revid'],'revision_at':record['timestamp'],'sha256':sha(text.encode()),'source_url':'https://en.wikipedia.org/w/index.php?oldid='+str(record['revid'])}
    value={'title':title,'page':page,'record':record,'html_blob':w.blob(document),'text_blob':w.blob(text.encode()),'attempt':attempt.name,'world_sha256':sha(encoded(w.scenario['world_model'])),'facts_sha256':sha(encoded(w.facts())),'effective_date':record['timestamp'][:10],'dependencies':sorted(w.facts()),'validation_status':'manual_reviewed','generation_method':'manual' if condition=='synthetic' else 'unchanged_capture'}
    w.db.execute('INSERT INTO versions VALUES (?,?,?)',(title,record['revid'],json.dumps(value)))
    if row['current']:w.db.execute('INSERT INTO pages VALUES (?,?)',(title,json.dumps(value)))
    w.db.execute('INSERT INTO cache VALUES (?,?)',('revision-title:'+str(record['revid']),json.dumps(title)))
    durable(attempt/'accepted.json',encoded(value));seal(attempt)
   for title in TITLES:
    records=[{**r['meta']['record'],'comment':'','user':''} for r in rows if r['title']==title]
    w.db.execute('INSERT INTO cache VALUES (?,?)',('history:'+title+':'+str(a.limit),json.dumps(records)))
   w.db.commit();checks=[]
   for title in TITLES:
    name=quote(title);paths=['/wiki/'+name,'/wiki/Special:Export/'+name,'/w/index.php?title='+name+'&action=history','/w/api.php?action=query&titles='+name+'&prop=revisions&rvprop=ids|timestamp|size|content&rvlimit='+str(a.limit),'/w/api.php?action=query&titles='+name+'&prop=revisions&rvprop=ids|timestamp&rvlimit=10']
    for row in rows:
     if row['title']==title:paths.append('/w/index.php?oldid='+str(row['meta']['record']['revid']))
    for path in paths:
     result=w.handle(path);checks.append({'path':path,'status':result['status']});assert result['status']==200,(condition,path,result)
   for query in ['Removal of Sam Altman from OpenAI','chief executive officer of OpenAI','OpenAI','Sam Altman CEO']:
    path='/w/api.php?action=query&list=search&srsearch='+quote(query);result=w.handle(path);checks.append({'path':path,'status':result['status']});assert result['status']==200
   frozen=a.output/(condition+'-frozen');digest=w.freeze(frozen)
   summary['worlds'][condition]={'path':str(frozen.resolve()),'seal':digest,'pages':4,'versions':len(rows),'checks':checks}
   print(condition,len(rows),'versions',len(checks),'checks',flush=True)
  finally:w.close()
 durable(a.output/'preparation.json',encoded(summary));seal(a.output)


if __name__=='__main__':main()
