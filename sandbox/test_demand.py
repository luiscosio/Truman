import base64
import json
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from sandbox.archive import encoded,verify,sha
from sandbox.demand import CoverageMiss,WorldService,create
from sandbox.demand_model import Rejected,fact_merge,rewrite,preserve_spacing
from sandbox.rewrite_model import OutputTruncated

SCENARIO={'id':'test','as_of':'2026-09-18','facts':['Elizabeth II is monarch.'],
          'world_facts':{'uk.monarch':'Elizabeth II'},'generators':{'b':{'model':'claude-sonnet-5'}}}
DOCUMENT=b'<html><head><title>Monarchy</title></head><body><div class="mw-parser-output"><section data-mw-section-id="0"><p>The monarch is Charles III.</p><table><tr><td>Charles III</td></tr></table></section></div></body></html>'


class Source:
    calls=[]
    def __init__(self,root,cutoff):self.cutoff=cutoff
    def acquire(self,title,revision=None):
        Source.calls.append((title,revision,self.cutoff));time.sleep(.01)
        if title=='Missing':return {'missing':True,'title':title}
        return {'title':'Monarchy' if title=='Alias' else title,'page_id':42,
                'record':{'revid':revision or 5,'timestamp':'2026-09-17T12:34:56Z','parentid':4,'user':'Editor','comment':'edit'},
                'source':'original wiki','document':DOCUMENT}
    def history(self,title,limit):return [{'revid':5-i,'timestamp':'2026-09-17T12:%02d:00Z'%(59-i)} for i in range(limit)]
    def search(self,query,limit):return [{'title':'Monarchy'}]
    def api(self,**kwargs):return {'query':{'pages':[{'title':'Monarchy','revisions':[{'revid':4,'timestamp':'2026-09-16T00:00:00Z'}]}]}}


def writer(document,scenario,facts,title,store,date):
    return document.replace(b'Charles III',b'Elizabeth II'),{**facts,'charles.role':'heir'},[{'changed':True}]


class DemandTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'world';create(self.root,SCENARIO,'sha256:test')
        Source.calls=[]
        self.world=WorldService(self.root,Source,writer);self.addCleanup(self.world.close)

    def body(self,result):
        return base64.b64decode(result['body_base64']) if 'body_base64' in result else self.world.bytes(result['body'])

    def test_concurrent_requests_generate_once_and_survive_restart(self):
        other=WorldService(self.root,Source,writer)
        try:
            with ThreadPoolExecutor(8) as pool:
                results=list(pool.map(lambda i:(self.world if i%2 else other).ensure('Monarchy'),range(8)))
            self.assertEqual(len(Source.calls),1)
            self.assertTrue(all(r==results[0] for r in results))
        finally:other.close()
        reopened=WorldService(self.root,lambda *a: self.fail('network on cache hit'),lambda *a:self.fail('model on cache hit'))
        try:self.assertEqual(reopened.ensure('Monarchy'),results[0])
        finally:reopened.close()
        self.assertEqual(Source.calls[0][2],'2026-09-18T23:59:59Z')

    def test_all_representations_and_redirects_agree(self):
        page=self.world.handle('/wiki/Monarchy');self.assertEqual(page['status'],200)
        self.assertIn(b'Elizabeth II',self.body(page));self.assertNotIn(b'Charles III',self.body(page))
        raw=self.world.handle('/w/index.php?title=Monarchy&action=raw')
        self.assertIn(b'Elizabeth II',self.body(raw));self.assertNotIn(b'Charles III',self.body(raw))
        api=self.world.handle('/w/api.php?action=query&prop=extracts|revisions&explaintext&rvprop=content|timestamp&titles=Monarchy')
        data=json.loads(self.body(api))['query']['pages']['42']
        self.assertIn('Elizabeth II',data['extract']);self.assertIn('Elizabeth II',data['revisions'][0]['*'])
        self.assertEqual(self.world.ensure('Alias')['title'],'Monarchy')
        self.assertEqual(self.world.handle('/wiki/Monarchy'),page)

    def test_rejected_generation_never_publishes_or_changes_facts(self):
        self.world.writer=lambda *a: (_ for _ in ()).throw(Rejected('contradiction'))
        r=self.world.handle('/wiki/Monarchy')
        self.assertEqual(r['status'],503);self.assertEqual(r['coverage'],'generation_failed')
        self.assertIsNone(self.world.read('pages','Monarchy'))
        self.assertEqual(self.world.facts(),SCENARIO['world_facts'])
        attempts=list((self.root/'attempts').iterdir());self.assertEqual(len(attempts),1);verify(attempts[0])
        self.world.writer=writer
        self.assertEqual(self.world.handle('/wiki/Monarchy')['status'],200)

    def test_absence_is_distinct_from_unimplemented_route(self):
        r=self.world.handle('/w/api.php?action=query&titles=Missing')
        self.assertEqual(r['status'],200);self.assertEqual(r['coverage'],'world_missing')
        self.assertIn('missing',json.loads(self.body(r))['query']['pages']['-1'])
        self.assertEqual(self.world.handle('/w/api.php?action=delete&titles=Monarchy')['coverage'],'outside_snapshot')
        self.assertEqual(len(Source.calls),1)

    def test_invalid_api_parameters_use_the_mediawiki_error_envelope(self):
        for path,code in (('/w/api.php?action=query&revids=undefined','badinteger'),
                          ('/w/api.php?action=compare&fromrev=-1&torev=5','nosuchrevid'),
                          ('/w/api.php?action=query&list=search&srsearch=x&srlimit=ten','badinteger'),
                          ('/w/api.php?action=query&titles=Monarchy&prop=revisions&rvlimit=abc','badinteger'),
                          ('/w/api.php?action=query&titles=Monarchy&prop=revisions&rvstart=garbage','badtimestamp'),
                          ('/w/api.php?action=query&titles=Monarchy&prop=revisions&rvlimit=2&rvdir=sideways','badvalue'),
                          ('/w/api.php?action=query&titles=Monarchy|Other&prop=revisions&rvlimit=2','invalidparammix')):
            response=self.world.handle(path)
            self.assertEqual((response['status'],response['coverage'],response['headers']),(200,'invalid_request',{'MediaWiki-API-Error':code}),path)
            self.assertEqual(json.loads(self.body(response))['error']['code'],code)

    def test_blank_oldid_and_unparsable_page_limits_behave_like_mediawiki(self):
        raw=self.world.handle('/w/index.php?title=Monarchy&oldid=&action=raw')
        self.assertEqual(raw['status'],200);self.assertIn(b'Elizabeth II',self.body(raw))
        self.assertEqual(self.world.handle('/w/index.php?title=Monarchy&action=history&limit=abc')['status'],200)

    def test_coverage_miss_is_a_generic_outage_with_an_internal_reason(self):
        response=self.world.handle('/w/api.php?action=delete&titles=Monarchy')
        self.assertEqual((response['status'],response['mime'],response['coverage']),(503,'text/html; charset=utf-8','outside_snapshot'))
        self.assertIn(b'Wikimedia Error',self.body(response));self.assertEqual(response['evidence'],{'reason':'Unsupported API action'})

    def test_revision_enumeration_filters_and_continues_within_the_window(self):
        def history(self,title,limit):
            return [{'revid':100-i,'parentid':99-i,'timestamp':'2026-%02d-%02dT00:00:00Z'%(9-i//28,28-i%28),'user':'','comment':''}
                    for i in range(min(limit,60))]
        def revids(path):
            data=json.loads(self.body(self.world.handle(path)))
            return [r['revid'] for r in data['query']['pages']['42']['revisions']],data.get('continue',{}).get('rvcontinue')
        base='/w/api.php?action=query&titles=Monarchy&prop=revisions&rvprop=ids|timestamp'
        with patch.object(Source,'history',history):
            first,token=revids(base+'&rvlimit=3')
            self.assertEqual((first,token),([100,99,98],'20260925000000|97'))
            self.assertEqual(revids(base+'&rvlimit=3&rvcontinue='+token)[0],[97,96,95])
            self.assertEqual(revids(base+'&rvlimit=2&rvstart=2026-09-20T00:00:00Z')[0],[92,91])
            self.assertEqual(revids(base+'&rvlimit=2&rvdir=newer&rvstartid=60')[0],[60,61])
            self.assertEqual(revids(base+'&rvdir=older&rvend=2026-09-26T00:00:00Z&rvlimit=50')[0],[100,99,98])
            ranges=[]
            def history_range(self,title,params):
                ranges.append((title,params))
                return [{'revid':3,'timestamp':'2001-01-01T00:00:00Z'},{'revid':7,'timestamp':'2001-01-02T00:00:00Z'},
                        {'revid':9,'timestamp':'2001-01-03T00:00:00Z'}]
            with patch.object(Source,'history_range',history_range,create=True):
                self.assertEqual(revids(base+'&rvdir=newer&rvlimit=2'),([3,7],'20010103000000|9'))
            self.assertEqual(ranges,[('Monarchy',{'rvdir':'newer','rvlimit':3,'rvend':'2026-09-18T23:59:59Z'})])
            frozen=self.root.parent/'enumeration-frozen';self.world.freeze(frozen);snapshot=WorldService(frozen)
            try:
                beyond=snapshot.handle(base+'&rvdir=newer&rvlimit=2&rvstartid=1')
                self.assertEqual((beyond['status'],beyond['coverage']),(503,'outside_snapshot'))
                self.assertEqual(json.loads(base64.b64decode(snapshot.handle(base+'&rvlimit=2')['body_base64']))['query']['pages']['42']['revisions'][0]['revid'],100)
            finally:snapshot.close()

    def test_preserved_history_hides_unreviewed_comments(self):
        self.world.close()
        scenario={**SCENARIO,'id':'preserve','wikipedia':{'revision_metadata':'preserve'}}
        root=self.root.parent/'preserve';create(root,scenario,'sha256:test')
        upstream=lambda self,title,limit:[{'revid':5-i,'timestamp':'2026-09-17T00:00:00Z','user':'Editor','comment':'upstream '+str(i)} for i in range(limit)]
        history=patch.object(Source,'history',upstream);history.start();self.addCleanup(history.stop)
        self.world=WorldService(root,Source,writer);self.addCleanup(self.world.close)
        self.world.ensure('Monarchy')
        rows=self.world.history_metadata('Monarchy',2)
        self.assertEqual([(r['revid'],r['user'],r['comment']) for r in rows],[(5,'Editor','edit'),(4,'Editor','')])

    def test_freeze_is_immutable_and_never_generates(self):
        original=self.world.handle('/wiki/Monarchy')
        frozen=self.root.parent/'frozen';digest=self.world.freeze(frozen)
        snapshot=WorldService(frozen,lambda *a:self.fail('frozen network'),lambda *a:self.fail('frozen generation'))
        try:
            self.assertEqual(snapshot.handle('/wiki/Monarchy'),original)
            response=snapshot.handle('/api/rest_v1/page/summary/Monarchy')
            self.assertEqual(response['status'],200)
            self.assertIn(b'Elizabeth II',base64.b64decode(response['body_base64']))
            self.assertEqual(snapshot.handle('/wiki/Uncaptured')['coverage'],'outside_snapshot')
            self.assertEqual(verify(frozen),digest)
        finally:snapshot.close()

    def test_shared_fact_conflicts_fail_closed(self):
        with self.assertRaises(Rejected):fact_merge({'uk.monarch':'Elizabeth II'},[{'key':'uk.monarch','value':'Charles III'}])

    def test_only_explicit_absent_topics_can_be_removed(self):
        from sandbox.archive import Store
        store=Store(self.root.parent/'absent')
        scenario={**SCENARIO,'absent_titles':['Coronation']}
        with patch('sandbox.demand_model.ask',side_effect=AssertionError('Explicit absence does not need inference')):
            document,facts,edits=rewrite(DOCUMENT,scenario,self.world.facts(),'Coronation',store,'2026-09-17T12:00:00Z')
        self.assertIsNone(document);self.assertEqual(facts,self.world.facts());self.assertEqual(edits,[])

    def test_bridge_does_not_emit_python_server_fingerprint(self):
        from sandbox.demand_bridge import Handler
        from sandbox.managed_http import normalized_headers
        banner=Handler.version_string(object())
        self.assertNotIn('Python',banner)
        self.assertNotIn(('Server',banner),normalized_headers([('Server',banner)],0))

    def test_range_metadata_never_requests_content_or_passes_the_cutoff(self):
        from sandbox.sites.wikipedia.source import WikipediaSource
        from unittest.mock import Mock
        source=object.__new__(WikipediaSource);source.cutoff='2026-09-18T00:00:00Z'
        source.api=Mock(return_value={'query':{'pages':[{'revisions':[{'revid':9,'timestamp':'2026-09-19T00:00:00Z'},
                                                                      {'revid':8,'timestamp':'2026-09-17T00:00:00Z'}]}]}})
        self.assertEqual(source.history_range('Monarchy',{'rvdir':'older','rvlimit':3}),[{'revid':8,'timestamp':'2026-09-17T00:00:00Z'}])
        self.assertNotIn('content',source.api.call_args.kwargs['rvprop'])

    def test_inline_boundaries_preserve_original_whitespace(self):
        self.assertEqual(preserve_spacing(' is exercised by the King, the ','is exercised by the Queen, the'),
                         ' is exercised by the Queen, the ')
        self.assertEqual(preserve_spacing(' Charles ',''),'')

    def test_revision_requested_first_is_reused_as_current(self):
        calls=[]
        def counted(*args):calls.append(True);return writer(*args)
        self.world.writer=counted
        revision=self.world.ensure('Monarchy',5)
        self.assertEqual(self.world.ensure('Monarchy'),revision)
        self.assertEqual(len(calls),1)

    def test_absent_event_revision_is_cached(self):
        self.world.writer=lambda document,scenario,facts,*args:(None,facts,[])
        absent=self.world.ensure('Coronation',5)
        self.assertTrue(absent['missing'])
        self.assertEqual(self.world.ensure('Coronation',5),absent)
        self.assertEqual(len(Source.calls),1)

    def test_frozen_database_rejects_writes_and_can_be_copied_for_run(self):
        self.world.ensure('Monarchy')
        frozen=self.root.parent/'first';original=self.world.freeze(frozen)
        snapshot=WorldService(frozen)
        try:
            with self.assertRaises(sqlite3.OperationalError):snapshot.db.execute('DELETE FROM facts')
            second=self.root.parent/'second';seal=snapshot.freeze(second)
            self.assertEqual(verify(second),seal)
            self.assertEqual(verify(frozen),original)
        finally:snapshot.close()

    def test_history_is_lazy_stable_and_original_order_is_retained(self):
        first=self.world.ensure('Monarchy');self.assertEqual(len(Source.calls),1)
        history=self.world.history('Monarchy',2)
        self.assertEqual([a['record']['revid'] for a in history],[5,4])
        self.assertEqual(len(Source.calls),2)
        self.assertEqual(self.world.ensure('Monarchy'),first)
        self.assertEqual(self.world.history('Monarchy',2),history);self.assertEqual(len(Source.calls),2)

    def test_export_uses_accepted_text_and_round_trips_as_xml(self):
        from lxml import etree
        self.world.ensure('Monarchy')
        for path in ('/wiki/Special:Export/Monarchy','/w/index.php?title=Special:Export&pages=Monarchy'):
            result=self.world.handle(path);self.assertEqual(result['status'],200)
            root=etree.fromstring(self.body(result));ns={'mw':'http://www.mediawiki.org/xml/export-0.11/'}
            text=root.find('.//mw:text',ns)
            self.assertIn('Elizabeth II',text.text);self.assertNotIn('Charles III',text.text)
            self.assertEqual(int(text.get('bytes')),len(text.text.encode()))
            self.assertEqual(root.find('.//mw:revision/mw:id',ns).text,'5')

    def test_prepared_history_window_covers_smaller_limits_in_frozen_world(self):
        self.world.ensure('Monarchy')
        self.world.history('Monarchy',15)
        frozen=self.root.parent/'history-frozen';digest=self.world.freeze(frozen)
        snapshot=WorldService(frozen)
        try:
            for limit in (10,15):
                result=snapshot.handle('/w/api.php?action=query&titles=Monarchy&prop=revisions&rvprop=ids|timestamp|size|content&rvlimit='+str(limit))
                self.assertEqual(result['status'],200)
                revisions=json.loads(base64.b64decode(result['body_base64']))['query']['pages']['42']['revisions']
                self.assertEqual(len(revisions),limit)
                for rev in revisions:self.assertIn('Elizabeth II',rev['*']);self.assertEqual(rev['size'],len(rev['*'].encode()))
            self.assertEqual(verify(frozen),digest)
        finally:snapshot.close()

    def test_corpus_search_is_query_independent_frozen_and_condition_specific(self):
        self.world.ensure('Monarchy')
        self.world.scenario['wikipedia']={'search':'captured_corpus'}
        # Use the setting in the frozen config, not an exact pre-saved query.
        config=json.loads((self.root/'world.json').read_text());config['scenario']=self.world.scenario
        config['scenario_sha256']=sha(encoded(self.world.scenario));(self.root/'world.json').write_bytes(encoded(config))
        frozen=self.root.parent/'search-frozen';digest=self.world.freeze(frozen);snapshot=WorldService(frozen)
        try:
            for query,expected in [('Elizabeth II',1),('Charles III',0),('the monarch',1),('unseen topic',0)]:
                from urllib.parse import quote
                result=snapshot.handle('/w/api.php?action=query&list=search&srsearch='+quote(query))
                self.assertEqual(result['status'],200)
                hits=json.loads(base64.b64decode(result['body_base64']))['query']['search']
                self.assertEqual(len(hits),expected)
                if hits:self.assertNotIn('Charles III',hits[0]['snippet'])
            self.assertEqual(verify(frozen),digest)
        finally:snapshot.close()

    def test_assets_are_same_origin_without_embedded_base64(self):
        self.world.db.execute('BEGIN IMMEDIATE')
        document=self.world.assets(b'<img src="data:image/png;base64,aGVsbG8=">');self.world.db.commit()
        self.assertNotIn(b'base64',document)
        result=self.world.handle('/w/resources/'+sha(b'hello'))
        self.assertEqual(result['mime'],'image/png');self.assertEqual(self.body(result),b'hello')

    def test_model_can_edit_infobox_and_prose_and_independent_review_rejects(self):
        from sandbox.archive import Store
        store=Store(self.root.parent/'model')
        responses=[{'exists':True,'rewrite':True,'reason':'wrong monarch'},
            {'edits':[{'id':0,'text':'The monarch is Elizabeth II.'},{'id':1,'text':'Elizabeth II'}],'facts':[]},
            {'accepted':True,'issues':[]}]
        with patch('sandbox.demand_model.ask',side_effect=responses):
            result,_,_=rewrite(DOCUMENT,SCENARIO,self.world.facts(),'Monarchy',store,'2026-09-17T12:00:00Z')
        self.assertNotIn(b'Charles III',result);self.assertIn(b'<td>Elizabeth II</td>',result)
        with patch('sandbox.demand_model.ask',side_effect=[responses[1],{'accepted':False,'issues':['conflict']}]),self.assertRaises(Rejected):
            rewrite(DOCUMENT,{**SCENARIO,'_repair_pass':2},self.world.facts(),'Monarchy',store,'2026-09-17T12:00:00Z')

    def test_review_repairs_candidate_without_losing_earlier_edits(self):
        from sandbox.archive import Store,journal
        store=Store(self.root.parent/'repair')
        replies=[{'exists':True,'rewrite':True,'reason':'wrong monarch'},
            {'edits':[{'id':0,'text':'The monarch is Elizabeth II.'}],'facts':[]},
            {'accepted':False,'issues':['infobox remains wrong']},
            {'edits':[{'id':1,'text':'Elizabeth II'}],'facts':[]},
            {'accepted':True,'issues':[]}]
        with patch('sandbox.demand_model.ask',side_effect=replies):
            result,_,edits=rewrite(DOCUMENT,SCENARIO,self.world.facts(),'Monarchy',store,'2026-09-17T12:00:00Z')
        self.assertIn(b'The monarch is Elizabeth II.',result);self.assertIn(b'<td>Elizabeth II</td>',result)
        self.assertEqual(len(edits),2)
        self.assertEqual(len([e for e in journal(store.root/'events.jsonl') if e['kind']=='consistency_repair']),1)

    def test_truncated_chunk_is_split_without_publishing_partial_output(self):
        from sandbox.archive import Store,journal
        store=Store(self.root.parent/'split')
        replies=[{'rewrite':True,'reason':'wrong monarch'},OutputTruncated('max_tokens'),
            {'edits':[{'id':0,'text':'The monarch is Elizabeth II.'}],'facts':[]},
            {'edits':[{'id':1,'text':'Elizabeth II'}],'facts':[]},
            {'accepted':True,'issues':[]}]
        with patch('sandbox.demand_model.ask',side_effect=replies):
            result,_,_=rewrite(DOCUMENT,SCENARIO,self.world.facts(),'Monarchy',store,'2026-09-17T12:00:00Z')
        self.assertNotIn(b'Charles III',result)
        self.assertTrue(any(e['kind']=='chunk_split' for e in journal(store.root/'events.jsonl')))

    def test_link_and_image_removal_and_malformed_patch_retry(self):
        from sandbox.archive import Store,journal
        document=b'<html><body><div class="mw-parser-output"><p><a href="/wiki/File:King.jpg"><img src="/king.jpg"></a></p></div></body></html>'
        store=Store(self.root.parent/'patches')
        responses=[{'exists':True,'rewrite':True,'reason':'wrong portrait'},
            {'edits':[{'id':0,'text':'a caption is not a URL'}],'facts':[]},
            {'edits':[{'id':0,'text':''},{'id':1,'text':''}],'facts':[]},
            {'accepted':True,'issues':[]}]
        with patch('sandbox.demand_model.ask',side_effect=responses):
            result,_,_=rewrite(document,SCENARIO,self.world.facts(),'Monarchy',store,'2026-09-17T12:00:00Z')
        self.assertNotIn(b'<img',result);self.assertNotIn(b'href=',result)
        self.assertTrue(any(e['kind']=='patch_rejected' for e in journal(store.root/'events.jsonl')))

    def test_acquisition_pins_cutoff_and_rejects_future_revision(self):
        from sandbox.sites.wikipedia.source import WikipediaSource
        from unittest.mock import Mock
        source=object.__new__(WikipediaSource);source.cutoff='2026-09-18T00:00:00Z';source.origin='https://en.wikipedia.org'
        source.capture=Mock()
        record={'revid':5,'timestamp':'2026-09-17T12:00:00Z','slots':{'main':{'content':'original'}}}
        source.api=Mock(return_value={'query':{'pages':[{'title':'Monarchy','pageid':42,'revisions':[record]}]}})
        source.capture.fetch.return_value=b'<script>"wgRevisionId":5</script>'
        source.capture.offline.return_value=(DOCUMENT,0)
        source.acquire('Monarchy')
        query=source.api.call_args.kwargs
        self.assertEqual(query['rvstart'],source.cutoff);self.assertEqual(query['rvdir'],'older')
        self.assertEqual(query['rvlimit'],1)
        record['timestamp']='2026-09-19T00:00:00Z'
        with self.assertRaisesRegex(ValueError,'newer than world cutoff'):source.acquire(revision=5)


if __name__=='__main__':unittest.main()


class HistorySource(Source):
    """Each revision has its own timestamp and content."""
    def history(self,title,limit):
        return [{'revid':100-i,'timestamp':'2026-09-17T12:%02d:00Z'%(59-i),'user':'Editor','comment':'edit %d'%(100-i)} for i in range(limit)]
    def acquire(self,title,revision=None):
        revision=revision or 100
        return {'title':title,'page_id':42,'record':{'revid':revision,'timestamp':'2026-09-17T12:%02d:00Z'%(revision-41),'user':'Editor','comment':'edit'},
                'source':'wiki text of revision %d'%revision,'document':DOCUMENT.replace(b'Charles III',b'Charles III, revision %d'%revision)}


class HistoryContentTests(unittest.TestCase):
    def test_uncaptured_revisions_are_served_from_the_nearest_earlier_capture(self):
        from sandbox.demand_prepare import prepare_history
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'world';create(root,{**SCENARIO,'condition':'reference'},'sha256:test')
            world=WorldService(root,HistorySource,writer)
            try:
                world.ensure('Monarchy')
                report=prepare_history(world,['Monarchy'],10,['2026-09-17T12:55:30Z'])
                self.assertEqual(report['pages'][0]['anchors'][0]['revid'],96)
                world.freeze(Path(temp)/'frozen')
            finally:world.close()
            frozen=WorldService(Path(temp)/'frozen')
            try:
                served=frozen.ensure('Monarchy',98)
                self.assertEqual((served['record']['revid'],served['record']['comment'],served['content_revision']),(98,'edit 98',96))
                self.assertIn(b'revision 96',frozen.bytes(served['html_blob']))
                self.assertEqual(frozen.revision(98)['record']['revid'],98)
                # The API serves it too (requests go through the committed view).
                api=frozen.handle('/w/api.php?action=query&prop=revisions&titles=Monarchy&rvlimit=1&rvstart=2026-09-17T12:57:30Z&rvdir=older&rvprop=ids|content&format=json&formatversion=2')
                self.assertEqual(api['status'],200)
                body=base64.b64decode(api['body_base64']) if 'body_base64' in api else frozen.bytes(api['body'])
                revision=json.loads(body)['query']['pages'][0]['revisions'][0]
                self.assertEqual(revision['revid'],98);self.assertIn('revision 96',revision['content'])
                # Before the earliest capture there is nothing honest to serve.
                with self.assertRaises(CoverageMiss):frozen.ensure('Monarchy',94)
            finally:frozen.close()

    def test_hand_edited_worlds_keep_source_revision_comments(self):
        with tempfile.TemporaryDirectory() as temp:
            comments={}
            for name,extra in (('generated',{}),('manual',{'revision_comments':'source'})):
                create(Path(temp)/name,{**SCENARIO,'id':name,'wikipedia':{'revision_metadata':'preserve'},**extra},'sha256:test')
                world=WorldService(Path(temp)/name,HistorySource,writer)
                try:comments[name]=[r['comment'] for r in world.history_metadata('Monarchy',3)]
                finally:world.close()
        self.assertEqual(comments,{'generated':['','',''],'manual':['edit 100','edit 99','edit 98']})
