"""Capture a bounded revision window, with reusable successes and rate-limit backoff.

Run --metadata-only first, then pass that sealed folder as --metadata.
--reuse folders may include failed attempts: only successful recorded fetches
are reused, and complete article captures must pass their integrity seal.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time
from sandbox.archive import Store,read_blob,durable,encoded,seal,verify
from sandbox.demand_source import WikipediaSource


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
 p.add_argument('--metadata-only',action='store_true');p.add_argument('--metadata',type=Path)
 p.add_argument('--reuse',type=Path,action='append',default=[]);p.add_argument('--limit',type=int,default=15)
 a=p.parse_args();assert 1<=a.limit<=50
 scenario=json.loads(Path(__file__).with_name('scenario.json').read_text());titles=scenario['source_titles'];cutoff=scenario['source_cutoff']
 a.output.mkdir(parents=True,exist_ok=False);cache={};existing=set()
 for root in a.reuse:
  for f in root.rglob('events.jsonl'):
   if f.parent.name!='http':continue
   for line in f.read_bytes().splitlines():
    event=json.loads(line)
    if event.get('kind')=='source_fetch' and event.get('exit_code')==0:cache[event['url']]=read_blob(f.parent,event['response_blob'])
  for f in root.rglob('original.json'):
   if f.parent.name=='original-capture':continue
   try:
    verify(f.parent);data=json.loads(f.read_text());existing.add((data['title'],data['record']['revid']))
   except (ValueError,FileNotFoundError,KeyError):continue
 failures=[]
 if not a.metadata_only:
  if a.metadata is None:p.error('--metadata is required for article captures')
  verify(a.metadata)
 try:
  for i,title in enumerate(titles):
   if a.metadata_only:
    root=a.output/title.replace(' ','_');source=WikipediaSource(root,cutoff)
    durable(root/'history.json',encoded(source.history(title,a.limit)));seal(root);continue
   records=json.loads((a.metadata/title.replace(' ','_')/'history.json').read_text())[:a.limit]
   for record in records:
    rev=record['revid']
    if (title,rev) in existing:continue
    root=a.output/str(i)/str(rev);store=Store(root/'audit');source=WikipediaSource(root/'source',cutoff);source.capture.cache.update(cache)
    fetch=source.capture.fetch
    def polite_fetch(url):
     for attempt in range(4):
      try:return fetch(url)
      except subprocess.CalledProcessError:
       events=(root/'source/http/events.jsonl').read_bytes().splitlines();event=json.loads(events[-1]);headers=read_blob(root/'source/http',event['headers_blob']).decode()
       if not re.search(r'HTTP/[\d.]+ 429',headers) or attempt==3:raise
       delay=re.search(r'retry-after: (\d+)',headers,re.I);time.sleep(min(60,int(delay[1])+1 if delay else 15))
    source.capture.fetch=polite_fetch
    try:
     data=source.acquire(revision=rev);data['document_blob']=store.blob(data.pop('document'));data['source_blob']=store.blob(data.pop('source').encode());durable(root/'original.json',encoded(data));cache.update(source.capture.cache)
     print(title,rev,'captured',flush=True)
    except Exception as exc:
     failures.append({'title':title,'revision':rev,'error':str(exc)});durable(root/'failure.json',encoded(failures[-1]));print(title,rev,'failed',flush=True)
    finally:seal(root)
 finally:
  durable(a.output/'failures.json',encoded(failures));seal(a.output)
 if failures:raise SystemExit('Some captures failed; retry into a new folder with --reuse.')


if __name__=='__main__':main()
