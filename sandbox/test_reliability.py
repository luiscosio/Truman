"""Regression tests for the failed seed/live diagnostic, without provider calls."""
import base64
import copy
import io
import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from sandbox.archive import Store, encoded, journal, verify
from sandbox.demand import WorldService, create, fork_world
from sandbox.demand_bridge import Worker, publish
from sandbox.demand_integrity import integrity_issues
from sandbox.sites import load
from sandbox.demand_model import Rejected
from sandbox.demand_rewrite import rewrite
from sandbox.demand_world import normalize
from sandbox.test_demand import Source, SCENARIO, DOCUMENT, writer
from sandbox.test_world_model import SCENARIO as WORLD_SCENARIO


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def world(self, scenario=SCENARIO, rewrite_fn=writer):
        create(self.root/'world',scenario,'test')
        world=WorldService(self.root/'world',Source,rewrite_fn);self.addCleanup(world.close)
        return world

    def test_cached_derived_and_missing_requests_bypass_blocked_generation(self):
        world=self.world({**SCENARIO,'absent_titles':['Excluded event']})
        world.ensure('Seed')
        started=threading.Event();release=threading.Event()
        def slow(*args):
            started.set();release.wait(3);return writer(*args)
        world.writer=slow
        with ThreadPoolExecutor() as pool:
            future=pool.submit(world.handle,'/wiki/Cold')
            try:
                self.assertTrue(started.wait(1))
                before=time.monotonic()
                for path,status in [('/wiki/Seed',200),('/api/rest_v1/page/summary/Seed',200),('/wiki/Excluded_event',404)]:
                    result=world.handle(path);self.assertEqual(result['status'],status)
                self.assertLess(time.monotonic()-before,.5)
                # The independent connection must not see the uncommitted cold page.
                self.assertIsNone(world.handle_cached('/wiki/Cold'))
            finally:release.set()
            self.assertEqual(future.result()['status'],200)

    def test_bridge_serves_warm_requests_and_records_every_expired_request(self):
        world=self.world({**SCENARIO,'absent_titles':['Excluded event'],'on_demand':{'request_seconds':.15}})
        world.ensure('Seed');started=threading.Event();release=threading.Event()
        def slow(*args):started.set();release.wait(3);return writer(*args)
        world.writer=slow;worker=Worker([world],self.root/'queue')
        def submit(name,path):
            p=worker.queue/(name+'.request.json');publish(p,{'host':'en.wikipedia.org','path':path,'method':'GET'});return p.with_name(name+'.response.json')
        def response(path):
            until=time.monotonic()+1
            while not path.exists() and time.monotonic()<until:time.sleep(.01)
            self.assertTrue(path.exists(),str(path));return json.loads(path.read_bytes())
        try:
            cold=submit('first','/wiki/Cold');self.assertTrue(started.wait(1))
            warm=submit('second','/api/rest_v1/page/summary/Seed')
            missing=submit('third','/wiki/Excluded_event')
            queued=submit('fourth','/wiki/Another_cold_page')
            self.assertEqual(response(warm)['status'],200)
            self.assertEqual(response(missing)['status'],404)
            self.assertEqual(response(cold)['status'],503)
            self.assertEqual(response(queued)['status'],503)
        finally:release.set();worker.close()
        self.assertEqual(len(list(worker.queue.glob('*.request.json'))),len(list(worker.queue.glob('*.response.json'))))

    def test_generation_deadline_rolls_back_and_preserves_failure(self):
        world=self.world({**SCENARIO,'on_demand':{'generation_seconds':.001}})
        result=world.handle('/wiki/New')
        self.assertEqual(result['coverage'],'generation_failed')
        self.assertIsNone(world.read('pages','New'))
        attempt=next((world.root/'attempts').iterdir())
        verify(attempt);self.assertTrue((attempt/'failure.json').exists());self.assertFalse((attempt/'accepted.json').exists())

    def test_absent_new_topic_never_reaches_writer_and_is_cached(self):
        world=self.world(WORLD_SCENARIO,rewrite_fn=__import__('sandbox.demand_model',fromlist=['rewrite']).rewrite)
        decision={'status':'absent','reason':'The specified launch never occurred','basis':['Operator rule: launch cancelled']}
        with patch('sandbox.demand_availability.ask',return_value=decision) as assessment, patch('sandbox.demand_rewrite.ask',side_effect=AssertionError('Writer must not run')):
            self.assertEqual(world.handle('/wiki/Unlisted_launch_ceremony')['status'],404)
            self.assertEqual(world.handle('/wiki/Unlisted_launch_ceremony')['status'],404)
            self.assertEqual(assessment.call_count,1)
        self.assertEqual(world.read('pages','Unlisted launch ceremony')['reason'],'scenario-absent')
        data=assessment.call_args.args[5]
        self.assertNotIn('prompt',data);self.assertNotIn('task',data)

    def test_uncertain_availability_never_becomes_a_missing_page(self):
        world=self.world(WORLD_SCENARIO,rewrite_fn=__import__('sandbox.demand_model',fromlist=['rewrite']).rewrite)
        with patch('sandbox.demand_availability.ask',return_value={'status':'uncertain','reason':'Ambiguous topic','basis':[]}):
            self.assertEqual(world.handle('/wiki/Ambiguous')['status'],503)
        self.assertIsNone(world.read('pages','Ambiguous'))

    def test_integrity_checks_detect_blank_leads_and_mass_deletion(self):
        source=('<div class="mw-parser-output"><section data-mw-section-id="0"><p>Introduction.</p></section>'+''.join('<p>Independent historical details, preserved. </p>' for _ in range(30))+'</div>').encode()
        broken=b'<div class="mw-parser-output"><section data-mw-section-id="0"></section><p>Remnant.</p></div>'
        self.assertEqual(len(integrity_issues(load('wikipedia'),source,broken)),2)
        self.assertEqual(integrity_issues(load('wikipedia'),source,source.replace(b'Introduction.',b'Updated introduction.')),[])

    def test_deleted_lead_can_be_restored_on_repair_even_if_review_misses_it(self):
        source=b'<div class="mw-parser-output"><section data-mw-section-id="0"><p>Original introduction.</p></section><p>Unrelated facts.</p></div>'
        store=Store(self.root/'repair');seen=[]
        def model(store,scenario,role,stage,system,data,schema):
            if stage=='page-plan':return {'summary':'update','changes':[{'blocks':[n['block'] for n in data['document']],'reason':'update','facts':[]}]}
            if stage.startswith('patch-0'):
                lead=next(n for n in data['nodes'] if n['value']=='Original introduction.')
                return {'edits':[],'remove_blocks':[lead['block']]}
            if stage.startswith('patch-1'):
                seen.extend(n['value'] for n in data['nodes'])
                return {'edits':[{'id':n['id'],'text':'Corrected introduction.'} for n in data['nodes'] if n['value']=='Original introduction.']}
            if stage.startswith('removal-review'):return {'decisions':[{'block':b['block'],'decision':'allow','reason':'Injected reviewer miss'} for b in data['requested_removals']]}
            return {'issues':[],'claims':[]}
        with patch('sandbox.demand_availability.ask',return_value={'status':'present','reason':'Existing topic','basis':[]}),patch('sandbox.demand_rewrite.ask',side_effect=model):
            result,_,_=rewrite(source,WORLD_SCENARIO,normalize(WORLD_SCENARIO)['world_facts'],'Topic',store,'2026-01-01')
        self.assertIn('Original introduction.',seen)
        self.assertIn(b'Corrected introduction.',result);self.assertIn(b'Unrelated facts.',result)

    def test_deletion_reviewer_can_prevent_loss_before_mutation(self):
        source=b'<div class="mw-parser-output"><p>Independent history.</p></div>'
        def model(store,scenario,role,stage,system,data,schema):
            if stage=='page-plan':return {'summary':'update','changes':[{'blocks':[n['block'] for n in data['document']],'reason':'update','facts':[]}]}
            if stage.startswith('patch-0'):return {'edits':[],'remove_blocks':[data['nodes'][0]['block']]}
            if stage.startswith('removal-review'):return {'decisions':[{'block':data['requested_removals'][0]['block'],'decision':'rewrite','reason':'Keep independent history.'}]}
            return {'edits':[],'issues':[],'claims':[]}
        with patch('sandbox.demand_availability.ask',return_value={'status':'present','reason':'Existing topic','basis':[]}),patch('sandbox.demand_rewrite.ask',side_effect=model):
            result,_,_=rewrite(source,WORLD_SCENARIO,normalize(WORLD_SCENARIO)['world_facts'],'Topic',Store(self.root/'removal'),'2026-01-01')
        self.assertIn(b'Independent history.',result)

    def test_diagnostic_seeds_cannot_be_reused_as_validated_seeds(self):
        world=self.world();article=world.ensure('Seed');article['validation_status']='unvalidated_diagnostic'
        with world.db:world.db.execute('UPDATE pages SET value=?',(json.dumps(article),))
        world.freeze(self.root/'frozen')
        with self.assertRaisesRegex(ValueError,'Unvalidated diagnostic'):
            fork_world(self.root/'frozen',self.root/'fork')
        self.assertFalse((self.root/'fork').exists())

    def test_protected_source_facts_survive_even_when_review_misses_deletion(self):
        source=b'<div class="mw-parser-output"><p>A city.</p><p>The bid was submitted in 2020.</p></div>'
        store=Store(self.root/'protected')
        def model(store,scenario,role,stage,system,data,schema):
            if stage=='page-plan':return {'summary':'update','changes':[],'preserve':['The bid was submitted in 2020.']}
            if stage.startswith('patch-0'):
                return {'edits':[{'id':n['id'],'text':'A bid was submitted.'} for n in data['nodes'] if '2020' in n['value']]}
            if stage.startswith('patch-1'):
                self.assertTrue(any('2020' in b['text'] for b in data['original_blocks']))
                return {'edits':[{'id':n['id'],'text':'The bid was submitted in 2020.'} for n in data['nodes'] if n['value']=='A bid was submitted.']}
            if stage.startswith('page-review'):
                self.assertNotIn('unknowns',data['world_model'])
                self.assertNotIn('unspecified_by_operator',data)
                preserved=next(b for b in data['final_document'] if '2020' in b['text'])
                self.assertTrue(preserved['source_text_unchanged'])
            return {'issues':[],'claims':[]}
        with patch('sandbox.demand_availability.ask',return_value={'status':'present','reason':'Existing topic','basis':[]}),patch('sandbox.demand_rewrite.ask',side_effect=model):
            output,_,_=rewrite(source,WORLD_SCENARIO,normalize(WORLD_SCENARIO)['world_facts'],'Topic',store,'2026-01-01')
        self.assertIn(b'The bid was submitted in 2020.',output)

    def test_declared_entity_names_and_ids_are_equivalent_claim_values(self):
        spec=copy.deepcopy(WORLD_SCENARIO)
        spec['world_model']['facts'][0].update(predicate='related_entity',value='institute')
        def model(store,scenario,role,stage,system,data,schema):
            if stage=='page-plan':return {'summary':'unchanged','changes':[],'preserve':[]}
            if stage.startswith('patch'):return {'edits':[]}
            return {'issues':[],'claims':[{'key':'institute.related_entity','value':'New Institute','blocks':[]}]}
        with patch('sandbox.demand_availability.ask',return_value={'status':'present','reason':'Existing topic','basis':[]}),patch('sandbox.demand_rewrite.ask',side_effect=model):
            output,_,_=rewrite(b'<div class="mw-parser-output"><p>New Institute.</p></div>',spec,normalize(spec)['world_facts'],'Topic',Store(self.root/'claims'),'2026-01-01')
        self.assertIn(b'New Institute.',output)

    def test_protected_historical_text_still_allows_canonical_link_updates(self):
        source=b'<div class="mw-parser-output"><p>In 1980, <a href="/wiki/Old_Institute" title="Old Institute">Old Institute</a> opened.</p></div>'
        def model(store,scenario,role,stage,system,data,schema):
            if stage=='page-plan':return {'summary':'rename links','changes':[],'preserve':['In 1980, Old Institute opened.']}
            if stage.startswith('patch'):
                self.assertTrue(all(n['field'] not in ('text','tail') for n in data['nodes']))
                return {'edits':[{'id':n['id'],'text':n['value'].replace('Old_Institute','New_Institute').replace('Old Institute','New Institute')} for n in data['nodes']]}
            return {'issues':[],'claims':[]}
        with patch('sandbox.demand_availability.ask',return_value={'status':'present','reason':'Existing topic','basis':[]}),patch('sandbox.demand_rewrite.ask',side_effect=model):
            output,_,_=rewrite(source,WORLD_SCENARIO,normalize(WORLD_SCENARIO)['world_facts'],'Topic',Store(self.root/'history'),'2026-01-01')
        self.assertIn(b'href="/wiki/New_Institute"',output)
        self.assertIn(b'>Old Institute</a> opened.',output)

    def test_partial_preservation_quote_cannot_freeze_a_required_rewrite(self):
        source=b'<div class="mw-parser-output"><p>Old Institute studies water.</p></div>'
        def model(store,scenario,role,stage,system,data,schema):
            if stage=='page-plan':return {'summary':'rename','changes':[],'preserve':['Old Institute']}
            if stage.startswith('patch'):return {'edits':[{'id':n['id'],'text':n['value'].replace('Old Institute','New Institute')} for n in data['nodes']]}
            return {'issues':[],'claims':[]}
        with patch('sandbox.demand_availability.ask',return_value={'status':'present','reason':'Existing topic','basis':[]}),patch('sandbox.demand_rewrite.ask',side_effect=model):
            output,_,_=rewrite(source,WORLD_SCENARIO,normalize(WORLD_SCENARIO)['world_facts'],'Topic',Store(self.root/'partial'),'2026-01-01')
        self.assertIn(b'New Institute studies water.',output)

    def test_transient_provider_failure_retries_once_and_preserves_both_responses(self):
        from sandbox.rewrite_model import call_claude
        store=Store(self.root/'provider');store.deadline=time.monotonic()+5
        response=MagicMock();response.status=200;response.headers={}
        response.read.return_value=encoded({'model':'claude-sonnet-5','stop_reason':'end_turn','content':[{'type':'text','text':'{"ok":true}'}]})
        context=MagicMock();context.__enter__.return_value=response
        opener=MagicMock();opener.open.side_effect=[HTTPError('https://api.anthropic.com/v1/messages',500,'Internal error',{},io.BytesIO(b'{"error":{}}')),context]
        with patch('sandbox.rewrite_model.api_key',return_value='test'),patch('sandbox.rewrite_model.build_opener',return_value=opener),patch('sandbox.rewrite_model.time.sleep'):
            self.assertEqual(call_claude({'model':'claude-sonnet-5'},store,'Topic','stage'),{'ok':True})
        self.assertEqual([e['status'] for e in journal(store.root/'events.jsonl') if e['kind']=='generation_response'],[500,200])
        self.assertLessEqual(opener.open.call_args.kwargs['timeout'],5)
        store.deadline=time.monotonic()-1
        with patch('sandbox.rewrite_model.api_key',return_value='test'),patch('sandbox.rewrite_model.build_opener',return_value=opener):
            with self.assertRaises(TimeoutError):call_claude({'model':'claude-sonnet-5'},store,'Topic','expired')
        self.assertEqual(opener.open.call_count,2)

    def test_transport_timeout_retries_once_within_the_deadline(self):
        from sandbox.rewrite_model import call_claude
        store=Store(self.root/'transport');store.deadline=time.monotonic()+5
        response=MagicMock();response.status=200;response.headers={}
        response.read.return_value=encoded({'model':'claude-sonnet-5','stop_reason':'end_turn','content':[{'type':'text','text':'{"ok":true}'}]})
        context=MagicMock();context.__enter__.return_value=response
        opener=MagicMock();opener.open.side_effect=[TimeoutError('The read operation timed out'),context]
        with patch('sandbox.rewrite_model.api_key',return_value='test'),patch('sandbox.rewrite_model.build_opener',return_value=opener):
            self.assertEqual(call_claude({'model':'claude-sonnet-5'},store,'Topic','stage'),{'ok':True})
        kinds=[e['kind'] for e in journal(store.root/'events.jsonl')]
        self.assertEqual(kinds.count('generation_transport_error'),1);self.assertIn('generation_retry',kinds)
        opener.open.side_effect=[TimeoutError('first'),TimeoutError('second')]
        with patch('sandbox.rewrite_model.api_key',return_value='test'),patch('sandbox.rewrite_model.build_opener',return_value=opener):
            with self.assertRaises(TimeoutError):call_claude({'model':'claude-sonnet-5'},store,'Topic','twice')


if __name__=='__main__':unittest.main()
