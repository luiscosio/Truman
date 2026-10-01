"""Capture exact source revisions for this fixture; no writing model is called."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from sandbox.archive import Store,durable,encoded,seal
from sandbox.sites.wikipedia.source import WikipediaSource

TITLES=['OpenAI','Elon Musk','Sam Altman','ChatGPT']
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 a.output.mkdir(parents=True,exist_ok=False)
 def one(pair):
  i,title=pair;root=a.output/str(i);store=Store(root/'audit')
  try:
   original=WikipediaSource(root/'source','2026-09-19T00:00:00Z').acquire(title)
   original['document_blob']=store.blob(original.pop('document'))
   original['source_blob']=store.blob(original.pop('source').encode())
   durable(root/'original.json',encoded(original))
   print(title+' captured',flush=True)
  finally:seal(root)
 with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(one,enumerate(TITLES)))
 seal(a.output)
if __name__=='__main__':main()
