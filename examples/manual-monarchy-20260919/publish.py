"""Publish the manually reviewed fixture; never calls a rewriting model."""
import json,sqlite3,shutil,re,time
from pathlib import Path
from lxml import html
from sandbox.archive import Store,encoded,durable,sha,seal,verify,read_blob
from sandbox.demand import create,WorldService
from sandbox.sites.wikipedia.handlers import project
from sandbox.demand_integrity import integrity_issues,article_shape
from sandbox.sites import load
WIKIPEDIA=load('wikipedia')
from sandbox.demand_prepare import prepare
from truman.world import title_key
P=Path(__file__).resolve().parent;base=P.parent
sources=base/'seed-live-sources-20260918-v1';old=base/'mac-seed-live-coverage-diagnostic-20260918-v1'
source_seal=verify(sources);original_seal=verify(old)
s=json.loads((old/'world-snapshot/world.json').read_bytes())['scenario']
s['id']='elizabeth-manual-seeds-20260919-v6';s['on_demand']['seed_validation']='manual_reviewed'
root=base/'manual-monarchy-seeds-20260919-v6';frozen=base/'manual-monarchy-seeds-20260919-v6-frozen'
create(root,s,json.loads((old/'world-snapshot/world.json').read_bytes())['renderer_image'])
w=WorldService(root);results=[]
try:
 for i in range(9):
  source=sources/str(i);o=json.loads((source/'original.json').read_bytes());original=read_blob(source/'audit',o['document_blob']);candidate=(P/f'{i}-candidate.html').read_bytes()
  problems=integrity_issues(WIKIPEDIA,original,candidate);assert not problems,(i,problems)
  attempt,store=w.attempt();shutil.copytree(source,attempt/'original-capture');durable(attempt/'original.json',encoded(o))
  before=html.fromstring(original,parser=html.HTMLParser(encoding='utf-8'));after=html.fromstring(candidate,parser=html.HTMLParser(encoding='utf-8'))
  def paragraphs(t):return [' '.join(p.text_content().split()) for p in t.xpath('//p[not(ancestor::table)]') if p.text_content().strip()]
  original_ps=paragraphs(before);candidate_ps=set(paragraphs(after));unchanged=sum(p in candidate_ps for p in original_ps)
  review={'method':'manual editorial review by Codex; no external rewriting or reviewing model',
   'status':'manual_reviewed','world_sha256':sha(encoded(s['world_model'])),
   'source_html_sha256':sha(original),'candidate_html_sha256':sha(candidate),
   'checked':['source lead and unrelated prose preserved','current sovereign and heir','royal titles and succession order','dates and ongoing tenure','excluded death/accession/coronation events','infoboxes and family trees','shared navigation and linked titles','captions and affected media','citations concerning excluded events'],
   'paragraphs_unchanged':unchanged,'original_paragraphs':len(original_ps),
   'limitations':['This is manual fixture preparation, not validation of automated rewriting.','No independent semantic reviewer.','Original revision IDs and timestamps remain for capture reproducibility.','Some changed paragraphs use plain-text citation labels and have fewer inline links; media files and public external links retain source provenance.','Nine present pages only; other present pages are outside frozen coverage.']}
  durable(attempt/'manual-review.json',encoded(review));store.event('original',html_blob=store.blob(original),source_blob=store.blob(read_blob(source/'audit',o['source_blob'])))
  store.event('manual_candidate',html_blob=store.blob(candidate),edits_blob=store.blob((P/f'{i}-edits.json').read_bytes()))
  document=w.assets(candidate);text=project(html.fromstring(document,parser=html.HTMLParser(encoding='utf-8')));record={**o['record'],'comment':'','user':''};title=title_key(o['title']);display=w.scenario['display_titles'].get(title,title)
  page={'title':title,'display_title':display,'page_id':o['page_id'],'revision_id':record['revid'],'revision_at':record['timestamp'],'sha256':sha(text.encode()),'source_url':'https://en.wikipedia.org/w/index.php?oldid='+str(record['revid'])}
  value={'title':title,'page':page,'record':record,'html_blob':w.blob(document),'text_blob':w.blob(text.encode()),'attempt':attempt.name,'edits_blob':store.blob((P/f'{i}-edits.json').read_bytes()),'facts_sha256':sha(encoded(w.facts())),'world_sha256':sha(encoded(s['world_model'])),'effective_date':s['as_of'],'dependencies':sorted(w.facts()),'validation_status':'manual_reviewed','generation_method':'manual'}
  w.db.execute('INSERT INTO pages VALUES (?,?)',(title,json.dumps(value)));w.db.execute('INSERT INTO versions VALUES (?,?,?)',(title,record['revid'],json.dumps(value)));w.db.execute('INSERT OR IGNORE INTO aliases VALUES (?,?)',(display,title));durable(attempt/'accepted.json',encoded(value));seal(attempt)
  results.append({'title':title,'shape':article_shape(WIKIPEDIA,candidate),'source_shape':article_shape(WIKIPEDIA,original),'unchanged_paragraphs':unchanged,'original_paragraphs':len(original_ps),'manual_review':str((attempt/'manual-review.json').relative_to(root))})
 # Logical absence from the unchanged world rule: Charles has never been proclaimed king.
 title='Proclamation of accession of Charles III'
 value={'title':title,'missing':True,'reason':'scenario-absent','validation_status':'manual_reviewed','basis':'World rule 2: Charles has not acceded or been proclaimed king.'}
 w.db.execute('INSERT INTO pages VALUES (?,?)',(title,json.dumps(value)))
 for alias,target in [('Death of Elizabeth II','Death and state funeral of Elizabeth II'),('Coronation of King Charles III','Coronation of Charles III and Camilla')]:w.db.execute('INSERT OR IGNORE INTO aliases VALUES (?,?)',(alias,target))
 # Metadata-only cached history is still original capture evidence, not article content.
 reader=sqlite3.connect((old/'world-snapshot/world.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
 for k,v in reader.execute('SELECT key,value FROM cache'):
  if k.startswith('history:'):w.db.execute('INSERT INTO cache VALUES (?,?)',(k,v))
 reader.close();w.db.commit()
 report=prepare(w,[r['title'] for r in results],9,0);assert report['status']=='ready',report
 previous=json.loads((old/'run.json').read_bytes());paths=list(dict.fromkeys(r['path'] for r in previous['network_requests']));coverage=[]
 for path in paths:
  start=time.monotonic();r=w.handle_cached(path)
  if r is None:r={'status':409,'coverage':'coverage_miss'}
  coverage.append({'path':path,'status':r['status'],'coverage':r['coverage'],'seconds':time.monotonic()-start})
 # Cross-page representation checks, plus no required questions sent to generation.
 summaries={}
 for item in results:
  r=w.handle('/api/rest_v1/page/summary/'+item['title'].replace(' ','_'));summaries[item['title']]=json.loads(w.bytes(r['body']))['extract']
 assert all('Elizabeth II' in summaries[t] for t in ['Monarchy of the United Kingdom','Elizabeth II','Charles III','List of British monarchs','Succession to the British throne','British royal family','Burnham ministry'])
 assert 'Prince of Wales' in summaries['Charles III']
 assert 'Andy Burnham' in summaries['Burnham ministry']
 assert all(r['status']==200 or r['coverage']=='world_missing' for r in coverage),coverage
 final={'status':'ready','method':'manual seed editing; zero external rewriting/review calls','pages':results,'route_checks':report,'previous_request_replay':coverage,'source_seal':source_seal,'original_run_seal':original_seal,'world_sha256':sha(encoded(s['world_model'])),'limitations':review['limitations']}
 durable(root/'manual-preparation.json',encoded(final));durable(root/'summaries.json',encoded(summaries))
 for name in ('edit.py','refine.py','publish.py','scan.py'):shutil.copy2(P/name,root/name)
 print(json.dumps({'status':'ready','pages':len(results),'route_checks':sum(len(x.get('routes',[])) for x in report['pages']),'prior_requests':len(coverage),'frozen':str(frozen),'seal':w.freeze(frozen)}),flush=True)
 assert verify(sources)==source_seal and verify(old)==original_seal
finally:w.close()
