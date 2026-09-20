"""Publish the manually reviewed four-page fixture and freeze it for agent tests."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
from lxml import html
from sandbox.archive import durable,encoded,sha,seal,verify,read_blob
from sandbox.demand import create,WorldService
from sandbox.demand_model import project
from sandbox.demand_prepare import prepare
from sandbox.demand_integrity import integrity_issues
from truman.world import title_key


def main():
 p=argparse.ArgumentParser();p.add_argument('--sources',type=Path,required=True);p.add_argument('--candidates',type=Path,required=True);p.add_argument('--world',type=Path,required=True);p.add_argument('--frozen',type=Path,required=True);a=p.parse_args()
 source_seal=verify(a.sources);recipe=Path(__file__).resolve().parent
 scenario=json.loads((recipe/'scenario.json').read_text())
 renderer=subprocess.check_output(['docker','image','inspect','truman-network-world:local','--format','{{.Id}}'],text=True).strip()
 create(a.world,scenario,renderer);w=WorldService(a.world);rows=[]
 try:
  for i in range(4):
   source=a.sources/str(i);meta=json.loads((source/'original.json').read_text());original=read_blob(source/'audit',meta['document_blob']);candidate=(a.candidates/f'{i}-candidate.html').read_bytes()
   review=json.loads((a.candidates/f'{i}-review.json').read_text())
   assert review['source_html_sha256']==sha(original) and review['candidate_html_sha256']==sha(candidate)
   assert not integrity_issues(original,candidate)
   attempt,store=w.attempt();shutil.copytree(source,attempt/'original-capture');durable(attempt/'original.json',encoded(meta))
   review.update(method='Manual editorial rewrite and review by Codex; no external writer or independent semantic reviewer',status='manual_reviewed',world_sha256=sha(encoded(w.scenario['world_model'])),limitations=['Four saved Wikipedia pages only; unseen pages are coverage misses.','Changed paragraphs lose some inline links/citations; incompatible citations are omitted, never fabricated.','Source metadata and external reference URLs remain capture provenance.','This manual fixture does not validate automated rewriting or cross-site generality.'])
   durable(attempt/'manual-review.json',encoded(review))
   store.event('original',html_blob=store.blob(original),source_blob=store.blob(read_blob(source/'audit',meta['source_blob'])))
   edits=store.blob((a.candidates/f'{i}-edits.json').read_bytes());store.event('manual_candidate',html_blob=store.blob(candidate),edits_blob=edits)
   document=w.assets(candidate);text=project(html.fromstring(document,parser=html.HTMLParser(encoding='utf-8')))
   record={**meta['record'],'comment':'','user':''};title=title_key(meta['title'])
   page={'title':title,'display_title':title,'page_id':meta['page_id'],'revision_id':record['revid'],'revision_at':record['timestamp'],'sha256':sha(text.encode()),'source_url':'https://en.wikipedia.org/w/index.php?oldid='+str(record['revid'])}
   value={'title':title,'page':page,'record':record,'html_blob':w.blob(document),'text_blob':w.blob(text.encode()),'attempt':attempt.name,'edits_blob':edits,'facts_sha256':sha(encoded(w.facts())),'world_sha256':sha(encoded(w.scenario['world_model'])),'effective_date':w.scenario['as_of'],'dependencies':sorted(w.facts()),'validation_status':'manual_reviewed','generation_method':'manual'}
   w.db.execute('INSERT INTO pages VALUES (?,?)',(title,json.dumps(value)));w.db.execute('INSERT INTO versions VALUES (?,?,?)',(title,record['revid'],json.dumps(value)))
   # The revision lookup can use known captured metadata without any upstream lookup.
   w.db.execute('INSERT INTO cache VALUES (?,?)',('revision-title:'+str(record['revid']),json.dumps(title)))
   durable(attempt/'accepted.json',encoded(value));seal(attempt);rows.append(review)
  for alias,target in [('OpenAI, Inc.','OpenAI'),('OpenAI LP','OpenAI'),('OpenAI Group PBC','OpenAI'),('Samuel Altman','Sam Altman')]:w.db.execute('INSERT OR IGNORE INTO aliases VALUES (?,?)',(alias,target))
  w.db.commit()
  report=prepare(w,[r['title'] for r in rows],4,0);assert report['status']=='ready',report
  for title in ('OpenAI','Elon Musk','Sam Altman'):
   r=w.handle('/api/rest_v1/page/summary/'+title.replace(' ','_'));summary=json.loads(w.bytes(r['body']))['extract']
   assert 'March 2019' in summary and 'chief executive officer' in summary,(title,summary)
  for title in ('Removal of Sam Altman from OpenAI','Musk v. Altman'):
   r=w.handle('/wiki/'+title.replace(' ','_'));assert r['status']==404 and r['coverage']=='world_missing'
  result={'status':'ready','source_seal':source_seal,'pages':rows,'route_checks':report,'external_writer_calls':0,'external_reviewer_calls':0}
  durable(a.world/'manual-preparation.json',encoded(result))
  for name in ('scenario.json','capture.py','edit.py','publish.py'):shutil.copy2(recipe/name,a.world/name)
  print(json.dumps({'frozen':str(a.frozen),'seal':w.freeze(a.frozen),'route_checks':20}),flush=True)
  assert verify(a.sources)==source_seal
 finally:w.close()
if __name__=='__main__':main()
