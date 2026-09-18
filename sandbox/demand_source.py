"""Bounded original acquisition at the world's fixed revision cutoff."""
import copy
import re
import json
from pathlib import Path
from sandbox.archive import sha,verify,read_blob
from sandbox.rewrite_capture import Capture


class WikipediaSource:
    def __init__(self, root, cutoff):
        self.capture=Capture(root)
        self.cutoff=cutoff
        # Reuse only verified, sealed acquisition attempts in this same world.
        for previous in Path(root).parent.parent.glob('*/seal.json'):
            verify(previous.parent)
            events=previous.parent/'source/http/events.jsonl'
            if events.exists():
                for line in events.read_bytes().splitlines():
                    event=json.loads(line)
                    if event.get('kind')=='source_fetch' and event.get('exit_code')==0:
                        self.capture.cache[event['url']]=read_blob(events.parent,event['response_blob'])

    def api(self, **query):return self.capture.api(**query)

    def acquire(self, title=None, revision=None):
        query={'action':'query','prop':'revisions','rvprop':'ids|timestamp|user|comment|content','rvslots':'main'}
        if revision:query['revids']=revision
        else:query.update(titles=title,redirects=1,rvstart=self.cutoff,rvdir='older',rvlimit=1)
        data=self.api(**query);entry=data['query']['pages'][0]
        if 'missing' in entry or not entry.get('revisions'):return {'missing':True,'title':entry.get('title',title)}
        record=copy.deepcopy(entry['revisions'][0])
        if record['timestamp']>self.cutoff:raise ValueError('Revision newer than world cutoff')
        text=record.pop('slots')['main']['content'];rev=record['revid']
        url='https://en.wikipedia.org/w/index.php?oldid='+str(rev)
        raw=self.capture.fetch(url)
        if not re.search(rb'"wgRevisionId"\s*:\s*'+str(rev).encode()+rb'\b',raw):raise ValueError('Mismatched HTML revision')
        document,assets=self.capture.offline(raw,url)
        return {'title':entry['title'],'page_id':entry['pageid'],'record':record,'source':text,
                'document':document,'source_sha256':sha(text.encode()),'assets':assets}

    def history(self,title,limit):
        data=self.api(action='query',titles=title,redirects=1,prop='revisions',rvstart=self.cutoff,
                      rvdir='older',rvlimit=limit,rvprop='ids|timestamp|user|comment')
        return data['query']['pages'][0].get('revisions',[])

    def search(self,query,limit):
        # Upstream search rankings are captured at request time, not time-travelled.
        return self.api(action='query',list='search',srsearch=query,srlimit=limit)['query']['search']
