"""Transactional persistent world. Host-only generation, immutable committed versions."""
import argparse
import contextlib
import base64
import datetime as dt
import json
import os
import re
import sqlite3
import threading
import tempfile
import time
import uuid
from pathlib import Path
from lxml import html

from sandbox.archive import Store, durable, encoded, read_blob, seal, sha, verify
from sandbox.demand_model import rewrite, fact_merge
from sandbox.generators import generation_settings
from sandbox.demand_world import normalize
from sandbox import sites


class CoverageMiss(ValueError):pass
class NeedsGeneration(Exception):pass


def code_files():
    """World engine and site adapter sources, retained in every world and attempt audit."""
    base=Path(__file__).parent
    files=[p for p in base.glob('*.py') if p.name.startswith(('demand','rewrite_')) or p.name=='generators.py']
    files+=[p for p in sorted((base/'sites').rglob('*')) if p.suffix in ('.py','.yaml')]
    return {str(p.relative_to(base)).replace('/','__'):p.read_bytes() for p in files}


def create(root,scenario,renderer):
    root=Path(root)
    scenario=normalize(scenario)
    site=sites.for_scenario(scenario)
    generation_settings(scenario,'b')
    cutoff=scenario.get('source_cutoff',scenario['as_of']+'T23:59:59Z')
    dt.datetime.fromisoformat(cutoff.replace('Z','+00:00'))
    if cutoff[:10]!=scenario['as_of']:raise ValueError('World date and source cutoff must match')
    root.mkdir(parents=True,exist_ok=False)
    for name in ('attempts','blobs'): (root/name).mkdir()
    durable(root/'world.json',encoded({'schema_version':1,'scenario':scenario,'source_cutoff':cutoff,
        'scenario_sha256':sha(encoded(scenario)),
        'renderer_image':renderer,'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'site':{'id':site.id,'profile_sha256':site.sha256},
        'limitations':[*site.world_limitations(site.settings(scenario)),
            'Search rankings are acquired at request time and then cached.',
            'Independent model review is not proof of global semantic consistency.']}))
    with contextlib.closing(sqlite3.connect(root/'world.sqlite')) as db:
        db.executescript('''CREATE TABLE versions (key TEXT, revision INTEGER, value TEXT, PRIMARY KEY(key,revision));
CREATE TABLE pages (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE aliases (alias TEXT PRIMARY KEY, target TEXT);
CREATE TABLE facts (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE cache (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE receipts (id TEXT PRIMARY KEY, value TEXT);''')
        db.executemany('INSERT INTO facts VALUES (?,?)',scenario.get('world_facts',{}).items())
        for entity in scenario.get('world_model',{}).get('entities',[]):
            if not entity['source_title']:continue
            for alias in [entity['source_title'],entity['title'],*entity['aliases']]:
                db.execute('INSERT OR IGNORE INTO aliases VALUES (?,?)',(site.key(alias),site.key(entity['source_title'])))
        db.commit()
    for name,data in code_files().items():durable(root/('code-'+name),data)
    return root


def fork_world(source,destination,scenario=None,renderer=None):
    """Start a growing world from verified seeds, retaining every source audit."""
    import shutil
    source=Path(source);destination=Path(destination);parent=verify(source)
    previous=json.loads((source/'world.json').read_bytes())
    with contextlib.closing(sqlite3.connect(source/'world.sqlite')) as reader:
        if any(json.loads(row[0]).get('validation_status')=='unvalidated_diagnostic'
               for row in reader.execute('SELECT value FROM pages')):
            raise ValueError('Unvalidated diagnostic seeds must be regenerated before reuse')
    scenario=normalize(scenario or previous['scenario'])
    operational={'id','generators','models','on_demand','source_titles'}
    if {k:v for k,v in scenario.items() if k not in operational}!={k:v for k,v in previous['scenario'].items() if k not in operational}:
        raise ValueError('Seed world facts or temporal scope differ; regenerate instead')
    create(destination,scenario,renderer or previous['renderer_image'])
    reader=sqlite3.connect((source/'world.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
    writer=sqlite3.connect(destination/'world.sqlite')
    try:reader.backup(writer)
    finally:reader.close();writer.close()
    for directory in ('attempts','blobs'):
        shutil.copytree(source/directory,destination/directory,dirs_exist_ok=True)
    durable(destination/'seed-parent.json',encoded({'source':str(source.resolve()),'seal':parent,
        'scenario_sha256':sha(encoded(previous['scenario'])),'note':'Seed bytes retain their recorded generation models; new requests use the new operational settings.'}))
    if verify(source)!=parent:raise ValueError('Seed world changed during fork')
    return destination


class WorldService:
    def __init__(self,root,source_factory=None,writer=rewrite):
        self.root=Path(root);self.config=json.loads((self.root/'world.json').read_bytes())
        if self.config.get('scenario_sha256',sha(encoded(self.config['scenario'])))!=sha(encoded(self.config['scenario'])):
            raise ValueError('World specification changed: create a new world version')
        self.scenario=self.config['scenario'];self.writer=writer
        self.site=sites.for_scenario(self.scenario);self.settings=self.site.settings(self.scenario)
        self.source_factory=source_factory or self.site.source()
        self.code=code_files();self.linked=[]
        self.readonly=(self.root/'seal.json').exists()
        if self.readonly:verify(self.root)
        self.lock=threading.RLock()
        self.blob_lock=threading.RLock()
        database=(self.root/'world.sqlite').resolve()
        self.db=sqlite3.connect(database.as_uri()+'?mode=ro' if self.readonly else database,
                               uri=self.readonly,timeout=600,check_same_thread=False)
        self.db.execute('PRAGMA busy_timeout=600000')

    def close(self):self.db.close()

    def blob(self,data):
        key=sha(data);p=self.root/'blobs'/key
        with self.blob_lock:
            if not p.exists():
                # Readers in another process must never observe a partial blob.
                with tempfile.NamedTemporaryFile(dir=p.parent,prefix='.pending-',delete=False) as temp:
                    temp.write(data);temp.flush();os.fsync(temp.fileno())
                    temporary=Path(temp.name)
                try:
                    try:os.link(temporary,p)
                    except FileExistsError:
                        if p.read_bytes()!=data:raise ValueError('Corrupt world blob')
                finally:temporary.unlink()
            elif p.read_bytes()!=data:raise ValueError('Corrupt world blob')
        return key

    def bytes(self,key):return read_blob(self.root,key)

    def facts(self):return dict(self.db.execute('SELECT key,value FROM facts'))

    def link(self,*others):
        """Review new pages against the committed pages of worlds on other sites.

        Linked worlds must share this world's compiled specification, date and
        condition; each keeps its own pages, profile and audits.
        """
        mine=(sha(encoded(self.scenario.get('world_model'))),self.scenario['as_of'],self.scenario.get('condition'),self.config['source_cutoff'])
        for other in others:
            theirs=(sha(encoded(other.scenario.get('world_model'))),other.scenario['as_of'],other.scenario.get('condition'),other.config['source_cutoff'])
            if other.root.resolve()==self.root.resolve() or other.site.id==self.site.id:raise ValueError('Link worlds on different sites only')
            if theirs!=mine:raise ValueError('Linked worlds must share the world specification, date, condition and cutoff')
            if not any(w.root.resolve()==other.root.resolve() for w in self.linked):self.linked.append(other)

    def peer_pages(self):
        """Committed pages of this world and its linked worlds, for consistency review."""
        found=[]
        for world in [self,*self.linked]:
            reader=sqlite3.connect((world.root/'world.sqlite').resolve().as_uri()+'?mode=ro',uri=True,timeout=60)
            try:rows=[json.loads(row[0]) for row in reader.execute('SELECT value FROM pages ORDER BY key')]
            finally:reader.close()
            found+=[{'title':p['title'],'site':world.site,'revision_at':p.get('effective_date',world.scenario['as_of']),
                     'document':read_blob(world.root,p['html_blob'])} for p in rows if not p.get('missing')]
        return found

    def pages(self):
        """Accepted current pages, ordered by key; absent topics are excluded."""
        pages=(json.loads(row[0]) for row in self.db.execute('SELECT value FROM pages ORDER BY key'))
        return [p for p in pages if not p.get('missing')]

    def read(self,table,key):
        if table not in ('pages','cache'):raise ValueError('Invalid table')
        row=self.db.execute('SELECT value FROM '+table+' WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else None

    def resolve(self,title):
        title=self.site.key(title)
        row=self.db.execute('SELECT target FROM aliases WHERE alias=?',(title,)).fetchone()
        return row[0] if row else title

    def attempt(self):
        path=self.root/'attempts'/uuid.uuid4().hex;path.mkdir()
        return path,Store(path)

    def assets(self,document):
        # Content-addressed same-origin resources avoid dumping base64 images into WebFetch.
        def replace(match):
            mime,data=match[1],match[2]
            raw=base64.b64decode(data,validate=True);key=self.blob(raw)
            self.db.execute('INSERT OR IGNORE INTO cache VALUES (?,?)',('asset:'+key,json.dumps({'blob':key,'mime':mime})))
            return self.site.asset_path(key)
        return re.sub(r'data:([^;"\s]+);base64,([A-Za-z0-9+/=]+)',replace,document.decode()).encode()

    def ensure(self,title,revision=None):
        with self.lock:
            key=self.resolve(title)
            if revision:
                row=self.db.execute('SELECT value FROM versions WHERE key=? AND revision=?',(key,revision)).fetchone()
                cached=json.loads(row[0]) if row else None
            else:cached=self.read('pages',key)
            if cached is not None:return cached
            if key in self.scenario.get('absent_titles',[]):
                return {'missing':True,'title':key,'reason':'scenario-absent'}
            if self.readonly:raise CoverageMiss('Article/revision absent from frozen world: '+key)
            self.db.execute('BEGIN IMMEDIATE')
            attempt=None
            try:
                # Recheck after cross-process transaction ownership.
                key=self.resolve(title)
                row=self.db.execute('SELECT value FROM versions WHERE key=? AND revision=?',(key,revision)).fetchone() if revision else None
                cached=(json.loads(row[0]) if row else None) if revision else self.read('pages',key)
                if cached is not None:self.db.commit();return cached
                limits=self.scenario.get('on_demand',{})
                if self.db.execute('SELECT count(*) FROM versions').fetchone()[0]>=limits.get('max_versions',60):raise CoverageMiss('World version budget exhausted')
                if len(list((self.root/'attempts').iterdir()))>=limits.get('max_attempts',100):raise CoverageMiss('World attempt budget exhausted')
                attempt,store=self.attempt()
                from sandbox.demand_budget import remaining
                store.deadline=time.monotonic()+float(limits.get('generation_seconds',90))
                durable(attempt/'context.json',encoded({'title':key,'revision':revision,'facts':self.facts(),
                    'site':self.site.id,'linked_worlds':[{'site':w.site.id,'root':str(w.root)} for w in self.linked],
                    'scenario_sha256':sha(encoded(self.scenario)),
                    'code':{name:store.blob(data) for name,data in self.code.items()}}))
                source=self.source_factory(attempt/'source',self.config['source_cutoff'])
                if hasattr(source,'capture'):source.capture.deadline=store.deadline
                original=source.acquire(key,revision)
                remaining(store)
                if original.get('missing'):
                    value={'missing':True,'title':key,'reason':'original-missing','attempt':attempt.name}
                else:
                    canonical=self.site.key(original['title'])
                    # Redirect aliases converge before model generation.
                    existing=self.read('pages',canonical) if not revision else None
                    if existing is None:
                        row=self.db.execute('SELECT value FROM versions WHERE key=? AND revision=?',
                                            (canonical,original['record']['revid'])).fetchone()
                        existing=json.loads(row[0]) if row else None
                    if existing is not None:
                        self.db.execute('INSERT OR IGNORE INTO aliases VALUES (?,?)',(key,canonical))
                        if not revision:self.db.execute('INSERT OR IGNORE INTO pages VALUES (?,?)',(canonical,json.dumps(existing)))
                        durable(attempt/'reuse.json',encoded({'canonical':canonical}));seal(attempt);self.db.commit();return existing
                    durable(attempt/'original.json',encoded({k:v for k,v in original.items() if k not in ('document','source')}))
                    store.event('original',html_blob=store.blob(original['document']),source_blob=store.blob(original['source'].encode()))
                    from sandbox.demand_model import Rejected
                    base_scenario={**self.scenario,'_document_date':original['record']['timestamp'][:10] if revision else self.scenario['as_of']}
                    for retry in range(2):
                        try:
                            if self.scenario.get('condition')=='reference':document,newfacts,edits=original['document'],self.facts(),[]
                            else:document,newfacts,edits=self.writer(original['document'],rewrite_scenario if retry else base_scenario,self.facts(),canonical,store,original['record']['timestamp'])
                            if document is not None and self.scenario.get('rewrite_pipeline')=='world-v2' and self.scenario.get('condition')!='reference':
                                from sandbox.demand_integrity import integrity_issues
                                problems=integrity_issues(self.site,original['document'],document)
                                if problems:raise Rejected('Content integrity rejected: '+json.dumps(problems))
                                from sandbox.demand_rewrite import review_peers
                                review_peers(document,canonical,base_scenario['_document_date'],self.scenario,self.peer_pages(),store)
                            break
                        except Rejected as exc:
                            store.event('rewrite_rejected',attempt=retry,error=str(exc))
                            if retry or str(exc).startswith('Consistency review rejected:'):raise
                            rewrite_scenario={**base_scenario,'_validation_feedback':str(exc)}
                    if self.scenario.get('rewrite_pipeline')=='world-v2' and newfacts!=self.facts():
                        raise Rejected('A page cannot extend the fixed world specification')
                    if self.scenario.get('rewrite_pipeline')!='world-v2':
                        fact_merge(self.facts(),[{'key':k,'value':v} for k,v in newfacts.items()])
                    if document is None:
                        value={'missing':True,'title':canonical,'reason':'scenario-absent','attempt':attempt.name,
                               'record':original['record']}
                        self.db.execute('INSERT INTO versions VALUES (?,?,?)',
                                        (canonical,original['record']['revid'],json.dumps(value)))
                    else:
                        record=dict(original['record'])
                        # Native modes rewrite captured source; others derive text from the accepted DOM.
                        native=self.settings['raw']=='native'
                        represent,text_format=self.site.raw(self.settings['raw'])
                        if native:
                            text,record,native_edits=represent(original['source'],original['document'],document,record,base_scenario,canonical,store)
                            store.event('native_representation',source_blob=store.blob(text.encode()),edits_blob=store.blob(encoded(native_edits)),record=record)
                        document=self.assets(document)
                        if not native:
                            text=represent(html.fromstring(document,parser=html.HTMLParser(encoding='utf-8')),self.site)
                        if len(document)>7_500_000 or len(text.encode())>7_500_000:raise CoverageMiss('Article exceeds response budget')
                        display=self.scenario.get('display_titles',{}).get(canonical,canonical)
                        if self.scenario.get('rewrite_pipeline')=='world-v2' and self.settings['revision_metadata']!='preserve':
                            # Original editor commentary remains in the private source audit.
                            record.update(comment='',user='')
                        page={'title':canonical,'display_title':display,'page_id':original['page_id'],
                            'revision_id':record['revid'],'revision_at':record['timestamp'],'sha256':sha(text.encode()),
                            'source_url':self.site.version_url(record['revid'],canonical)}
                        value={'title':canonical,'page':page,'record':record,'html_blob':self.blob(document),
                            'text_blob':self.blob(text.encode()),'attempt':attempt.name,'edits_blob':store.blob(encoded(edits)),
                            'facts_sha256':sha(encoded(newfacts)),
                            'world_sha256':sha(encoded(self.scenario.get('world_model',{}))),
                            'effective_date':base_scenario['_document_date'],'text_format':text_format,
                            'dependencies':sorted(newfacts)}
                        self.db.execute('INSERT INTO versions VALUES (?,?,?)',(canonical,record['revid'],json.dumps(value)))
                        for k,v in newfacts.items():self.db.execute('INSERT OR IGNORE INTO facts VALUES (?,?)',(k,v))
                        self.db.execute('INSERT OR IGNORE INTO aliases VALUES (?,?)',(display,canonical))
                    self.db.execute('INSERT OR IGNORE INTO aliases VALUES (?,?)',(key,canonical));key=canonical
                if not revision:self.db.execute('INSERT INTO pages VALUES (?,?)',(key,json.dumps(value)))
                remaining(store)
                durable(attempt/'accepted.json',encoded(value));seal(attempt)
                self.db.commit()
                return value
            except Exception as exc:
                self.db.rollback()
                if attempt and not (attempt/'seal.json').exists():
                    durable(attempt/'failure.json',encoded({'error':str(exc)}));seal(attempt)
                raise

    def cached_operation(self,key,operation):
        with self.lock:
            existing=self.read('cache',key)
            if existing is not None:return existing
            if self.readonly:raise CoverageMiss('Query absent from frozen world')
            self.db.execute('BEGIN IMMEDIATE')
            attempt=None
            try:
                existing=self.read('cache',key)
                if existing is not None:self.db.commit();return existing
                if len(list((self.root/'attempts').iterdir()))>=self.scenario.get('on_demand',{}).get('max_attempts',100):
                    raise CoverageMiss('World attempt budget exhausted')
                attempt,store=self.attempt()
                from sandbox.demand_budget import remaining
                store.deadline=time.monotonic()+float(self.scenario.get('on_demand',{}).get('generation_seconds',90))
                source=self.source_factory(attempt/'source',self.config['source_cutoff'])
                if hasattr(source,'capture'):source.capture.deadline=store.deadline
                value=operation(source)
                remaining(store)
                durable(attempt/'accepted.json',encoded(value));seal(attempt)
                self.db.execute('INSERT OR IGNORE INTO cache VALUES (?,?)',(key,json.dumps(value)))
                self.db.commit()
                return self.read('cache',key)
            except Exception as exc:
                self.db.rollback()
                if attempt and not (attempt/'seal.json').exists():durable(attempt/'failure.json',encoded({'error':str(exc)}));seal(attempt)
                raise

    def history(self,title,limit):
        key=self.resolve(title)
        records=self.history_metadata(key,limit)
        return [self.ensure(key,r['revid']) for r in records]

    def history_metadata(self,title,limit):
        key=self.resolve(title)
        # A prepared larger window also covers smaller requests. Do not require
        # an exact cache-key match for every agent's choice of page size.
        windows=[]
        prefix='history:'+key+':'
        for cache_key,value in self.db.execute('SELECT key,value FROM cache WHERE key LIKE ?',('history:%',)):
            if cache_key.startswith(prefix) and cache_key[len(prefix):].isdigit() and int(cache_key[len(prefix):])>=limit:
                windows.append((int(cache_key[len(prefix):]),json.loads(value)))
        records=min(windows,key=lambda item:item[0])[1][:limit] if windows else self.cached_operation(prefix+str(limit),lambda source:source.history(key,limit))
        return self.present(key,records)

    def history_range(self,title,params):
        """Upstream metadata for a revision range outside the widest window; never page content."""
        key=self.resolve(title)
        fetch=lambda source:source.history_range(key,params)
        return self.present(key,self.cached_operation('history-range:'+key+':'+json.dumps(params,sort_keys=True),fetch))

    def present(self,key,records):
        """Revision metadata as this world shows it."""
        if self.settings['revision_metadata']=='preserve':
            result=[]
            for r in records:
                row=self.db.execute('SELECT value FROM versions WHERE key=? AND revision=?',(key,r['revid'])).fetchone()
                prepared=json.loads(row[0]) if row else None
                if prepared and not prepared.get('missing'):result.append(dict(prepared['record']))
                # Only generated revisions have had their comment reviewed against the world.
                elif self.scenario.get('condition')=='reference':result.append(dict(r))
                else:result.append({**r,'comment':''})
            return result
        return [{**r,'comment':'','user':''} if self.scenario.get('rewrite_pipeline')=='world-v2' else dict(r) for r in records]

    def history_window(self,title,cap=50):
        """The widest known newest-first metadata window, and whether it reaches the first revision."""
        key=self.resolve(title);prefix='history:'+key+':'
        sizes=[int(k[len(prefix):]) for (k,) in self.db.execute('SELECT key FROM cache WHERE key LIKE ?',('history:%',))
               if k.startswith(prefix) and k[len(prefix):].isdigit()]
        size=max(sizes,default=cap) if self.readonly else max([cap,*sizes])
        records=self.history_metadata(key,size)
        return records,len(records)<size

    def revision(self,revision):
        row=self.db.execute('SELECT value FROM versions WHERE revision=?',(revision,)).fetchone()
        if row:return json.loads(row[0])
        def lookup(source):
            title=source.version_title(revision)
            if title is None:raise CoverageMiss('Revision outside fixed cutoff')
            return title
        title=self.cached_operation('revision-title:'+str(revision),lookup)
        return self.ensure(title,revision)

    def bootstrap(self,destination):
        destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
        durable(destination/'snapshot.json',encoded({'schema_version':1,'kind':'truman-frozen-world',
            'condition':self.scenario.get('condition','synthetic'),'as_of':self.scenario['as_of'],'articles':{},'routes':{},
            'presentation':'on-demand-v1','bundle_manifest_sha256':sha(encoded(self.config)),
            'renderer_image':self.config['renderer_image'],
            'generator':{'id':'b','mode':'frozen' if self.readonly else 'on-demand','provider':'anthropic',
                         'model':generation_settings(self.scenario,'b').get('model','claude-sonnet-5')}}))
        seal(destination);return destination

    def search(self,query,limit):
        if self.settings['search']=='captured_corpus':
            from sandbox.demand_search import search_corpus
            return search_corpus(self,query,limit)
        hits=self.cached_operation('search:'+query+':'+str(limit),lambda source:source.search(query,limit))
        return [self.ensure(hit['title']) for hit in hits]

    def handle(self,target):
        from sandbox.demand_routes import respond
        cached=self.handle_cached(target)
        if cached is not None:return cached
        with self.lock:
            key='response:'+target
            cached=self.read('cache',key)
            if cached:return cached
            result=respond(self,target)
            status,mime,body,headers,coverage,proof=result
            value={'status':status,'mime':mime,'body':sha(body),'headers':headers,'coverage':coverage,'evidence':proof}
            if self.readonly:
                # Derived replay may create a response in memory, never mutate the snapshot.
                value['body_base64']=base64.b64encode(body).decode()
            else:
                value['body']=self.blob(body)
                with self.db:
                    self.db.execute('INSERT INTO receipts VALUES (?,?)',(uuid.uuid4().hex,json.dumps({'target':target,**value})))
                    if coverage not in ('outside_snapshot','generation_failed'):
                        self.db.execute('INSERT OR IGNORE INTO cache VALUES (?,?)',(key,json.dumps(value)))
            return value

    def handle_cached(self,target):
        """Read a committed snapshot without waiting on generation's write lock.

        A fresh read connection cannot observe uncommitted pages or world facts.
        Routes may derive new representations from accepted pages, but may not
        acquire sources or invoke models. The bridge polls this path separately.
        """
        from sandbox.demand_routes import respond
        reader=object.__new__(_CommittedView)
        reader.root=self.root;reader.config=self.config;reader.scenario=self.scenario
        reader.site=self.site;reader.settings=self.settings
        reader.readonly=self.readonly
        reader.db=sqlite3.connect((self.root/'world.sqlite').resolve().as_uri()+'?mode=ro',uri=True,timeout=.1)
        try:
            reader.db.execute('BEGIN')
            cached=reader.read('cache','response:'+target)
            if cached:return cached
            status,mime,body,headers,coverage,proof=respond(reader,target)
            value={'status':status,'mime':mime,'body':sha(body),'headers':headers,'coverage':coverage,'evidence':proof}
            if self.readonly:value['body_base64']=base64.b64encode(body).decode()
            else:value['body']=self.blob(body)
            return value
        except NeedsGeneration:return None
        finally:reader.db.close()

    def freeze(self,destination):
        with self.lock:
            destination=Path(destination);destination.mkdir(parents=True,exist_ok=False)
            import shutil
            # SQLite's backup API yields a consistent transaction snapshot, including in another process.
            if not self.readonly:self.db.execute('BEGIN IMMEDIATE')
            try:
                backup=sqlite3.connect(destination/'world.sqlite')
                reader=sqlite3.connect(self.root/'world.sqlite')
                reader.backup(backup);reader.close();backup.close()
                for path in self.root.iterdir():
                    if path.name.startswith('world.sqlite') or path.name in ('seal.json','frozen.json'):continue
                    if path.is_dir():shutil.copytree(path,destination/path.name)
                    else:shutil.copy2(path,destination/path.name)
                durable(destination/'frozen.json',encoded({'source':str(self.root),'config_sha256':sha(encoded(self.config))}))
                return seal(destination)
            finally:self.db.rollback()


class _CommittedView(WorldService):
    def ensure(self,title,revision=None):
        key=self.resolve(title)
        row=self.db.execute('SELECT value FROM versions WHERE key=? AND revision=?',(key,revision)).fetchone() if revision else None
        cached=(json.loads(row[0]) if row else None) if revision else self.read('pages',key)
        if cached is not None:return cached
        if key in self.scenario.get('absent_titles',[]):
            return {'missing':True,'title':key,'reason':'scenario-absent'}
        if self.readonly:raise CoverageMiss('Article/revision absent from frozen world: '+key)
        raise NeedsGeneration(key)

    def cached_operation(self,key,operation):
        cached=self.read('cache',key)
        if cached is not None:return cached
        if self.readonly:raise CoverageMiss('Query absent from frozen world')
        raise NeedsGeneration(key)


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='action',required=True)
    new=sub.add_parser('create');new.add_argument('--world',type=Path,required=True);new.add_argument('--scenario',type=Path,required=True)
    fork=sub.add_parser('fork');fork.add_argument('--from-world',type=Path,required=True);fork.add_argument('--world',type=Path,required=True)
    fork.add_argument('--scenario',type=Path);fork.add_argument('--renderer',help='Pinned renderer image for a host-only seed artifact')
    request=sub.add_parser('request');request.add_argument('--world',type=Path,required=True);request.add_argument('--path',required=True)
    freeze=sub.add_parser('freeze');freeze.add_argument('--world',type=Path,required=True);freeze.add_argument('--output',type=Path,required=True)
    serve=sub.add_parser('serve');serve.add_argument('--world',type=Path,required=True);serve.add_argument('--port',type=int,default=8767)
    args=parser.parse_args()
    if args.action=='fork':
        scenario=json.loads(args.scenario.read_bytes()) if args.scenario else None
        print(fork_world(args.from_world,args.world,scenario,args.renderer));return
    if args.action=='create':
        import subprocess
        renderer=subprocess.check_output(['docker','image','inspect','truman-network-world:local','--format','{{.Id}}'],text=True).strip()
        print(create(args.world,json.loads(args.scenario.read_bytes()),renderer));return
    world=WorldService(args.world)
    try:
        if args.action=='freeze':print(world.freeze(args.output))
        elif args.action=='serve':
            if not world.readonly:raise ValueError('Browser preview requires a frozen world')
            from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
            class Preview(BaseHTTPRequestHandler):
                def log_message(self,*args):pass
                def do_GET(self):
                    result=world.handle(self.path)
                    data=base64.b64decode(result['body_base64']) if 'body_base64' in result else world.bytes(result['body'])
                    self.send_response(result['status']);self.send_header('Content-Type',result['mime']);self.send_header('Content-Length',str(len(data)))
                    for k,v in result['headers'].items():self.send_header(k,v)
                    self.end_headers();self.wfile.write(data)
            print('Frozen preview: http://127.0.0.1:'+str(args.port),flush=True)
            ThreadingHTTPServer(('127.0.0.1',args.port),Preview).serve_forever()
        else:
            result=world.handle(args.path)
            print(json.dumps({k:v for k,v in result.items() if k!='body_base64'}))
            return 0 if result['status']<400 else 1
    finally:world.close()


if __name__=='__main__':raise SystemExit(main())
