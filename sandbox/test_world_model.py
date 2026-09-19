import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from lxml import html
from sandbox.archive import Store, verify, journal
from sandbox.demand import create, WorldService
from sandbox.demand_model import Rejected
from sandbox.demand_rewrite import rewrite, surfaces, identity_issues
from sandbox.demand_world import validate, normalize, active_facts, settings
from sandbox.test_demand import Source

SPEC={'version':1,'entities':[{'id':'institute','kind':'organization','source_title':'Old Institute',
      'title':'New Institute','aliases':['Research Institute'],'exists':True}],
      'facts':[{'subject':'institute','predicate':'name','value':'New Institute','valid_from':'2025-01-01',
                'valid_until':'','origin':'given','basis':'Operator rule 1'}],
      'invariants':['Use the new name after 2025.'],'preserve':['Unrelated history.'],'unknowns':[]}
SCENARIO={'id':'rename','as_of':'2026-09-18','facts':['The institute was renamed in 2025.'],
          'world_model':SPEC,'generators':{'b':{'model':'claude-sonnet-5','effort':'high'}}}
DOC=b'<html><head><title>Old Institute</title></head><body><div class="mw-parser-output"><p>The <a href="/wiki/Old_Institute" title="Old Institute">Old Institute</a> studies water.</p><p>Founded in 1980.</p></div></body></html>'


class WorldModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)

    def test_temporal_conflicts_and_unknown_subjects_reject(self):
        spec=copy.deepcopy(SPEC);spec['facts'].append({**spec['facts'][0],'value':'Other'})
        with self.assertRaisesRegex(ValueError,'Conflicting'):validate(spec)
        spec['facts'][0]['valid_until']='2025-01-01';spec['facts'][0]['valid_from']='2020-01-01'
        validate(spec)
        self.assertEqual(active_facts(spec,'2024-01-01')['institute.name'],'New Institute')
        self.assertEqual(active_facts(spec,'2025-01-01')['institute.name'],'Other')
        spec['facts'][0]['subject']='unknown'
        with self.assertRaises(ValueError):validate(spec)

    def test_alias_collisions_reject(self):
        spec=copy.deepcopy(SPEC);spec['entities'].append({**spec['entities'][0],'id':'other'})
        with self.assertRaisesRegex(ValueError,'alias'):validate(spec)

    def test_rewriter_cannot_invent_link_targets(self):
        from sandbox.demand_rewrite import apply
        nodes=surfaces(html.fromstring('<p><a href="/wiki/Original">Label</a></p>'))
        node=next(n for n in nodes if n['field']=='href')
        with self.assertRaisesRegex(Rejected,'no captured or declared'):
            apply(nodes,[{'id':node['id'],'text':'/wiki/Invented_page'}],{node['id']},{'Original','Known page'})
        apply(nodes,[{'id':node['id'],'text':'/wiki/Known_page'}],{node['id']},{'Original','Known page'})
        self.assertEqual(node['node'].get('href'),'/wiki/Known_page')

    def test_proposed_image_replacement_is_removed_and_reviewed(self):
        document=b'<div class="mw-parser-output"><p>A portrait.</p><figure><img alt="Portrait" src="/old.png"></figure></div>'
        store=Store(self.root/'images');reviewed=[]
        def model(store,scenario,role,stage,system,data,schema):
            if stage=='page-plan':
                return {'summary':'Remove invalid portrait','changes':[{'blocks':list({n['block'] for n in data['document']}),'reason':'Invalid evidence','facts':[]}]}
            if stage.startswith('patch'):
                return {'edits':[{'id':n['id'],'text':'New portrait /invented.png'} for n in data['nodes'] if n['field']=='image']}
            if stage.startswith('page-review'):reviewed.extend(data['final_document'])
            return {'accepted':True,'issues':[],'claims':[]}
        with patch('sandbox.demand_rewrite.ask',side_effect=model):
            result,_,_=rewrite(document,SCENARIO,normalize(SCENARIO)['world_facts'],'Topic',store,'2026-01-01')
        self.assertFalse(html.fromstring(result).xpath('.//img'))
        self.assertNotIn(b'invented.png',result)
        self.assertFalse(any(a[1]=='image' for block in reviewed for a in block['attributes']))
        self.assertTrue(any(e['kind']=='unsupported_image_removed' for e in journal(store.root/'events.jsonl')))

    def test_large_article_plan_uses_concepts_then_checks_all_blocks(self):
        document=('<div class="mw-parser-output">'+''.join('<p>Unrelated fact '+str(i)+'.</p>' for i in range(2001))+'</div>').encode()
        patched=[]
        def model(store,scenario,role,stage,system,data,schema):
            if stage=='page-plan':
                self.assertNotIn('blocks',schema['properties']['changes']['items']['properties'])
                return {'summary':'No changes identified','changes':[]}
            if stage.startswith('patch'):
                patched.extend(n['id'] for n in data['nodes']);return {'edits':[]}
            return {'accepted':True,'issues':[],'claims':[]}
        with patch('sandbox.demand_rewrite.ask',side_effect=model):
            rewrite(document,SCENARIO,normalize(SCENARIO)['world_facts'],'Topic',Store(self.root/'large'),'2026-01-01')
        self.assertEqual(len(patched),2001)
        self.assertEqual(len(set(patched)),2001)

    def test_truncated_patch_splits_only_between_blocks(self):
        from sandbox.rewrite_model import OutputTruncated
        document=b'<div class="mw-parser-output"><p>Old name <b>one</b>.</p><p>Old name <b>two</b>.</p></div>'
        store=Store(self.root/'split');groups=[]
        def model(store,scenario,role,stage,system,data,schema):
            if stage=='page-plan':
                return {'summary':'rename','changes':[{'blocks':sorted({n['block'] for n in data['document']}),'reason':'rename','facts':[]}]}
            if stage.startswith('patch'):
                blocks={n['block'] for n in data['nodes']}
                if len(blocks)>1:raise OutputTruncated('max_tokens')
                groups.append(data['nodes'])
                return {'edits':[{'id':n['id'],'text':n['value'].replace('Old name','New name')} for n in data['nodes'] if 'Old name' in n['value']]}
            return {'accepted':True,'issues':[],'claims':[]}
        with patch('sandbox.demand_rewrite.ask',side_effect=model):
            result,_,_=rewrite(document,SCENARIO,normalize(SCENARIO)['world_facts'],'Topic',store,'2026-01-01')
        self.assertEqual(result.count(b'New name'),2)
        self.assertEqual([len(g) for g in groups],[3,3])
        self.assertEqual(len([e for e in journal(store.root/'events.jsonl') if e['kind']=='semantic_chunk_split']),1)

    def test_unsplittable_truncation_never_publishes(self):
        from sandbox.rewrite_model import OutputTruncated
        create(self.root/'world',SCENARIO,'test')
        world=WorldService(self.root/'world',Source);self.addCleanup(world.close)
        def model(store,scenario,role,stage,system,data,schema):
            if stage=='page-plan':
                return {'summary':'change','changes':[{'blocks':sorted({n['block'] for n in data['document']}),'reason':'change','facts':[]}]}
            raise OutputTruncated('max_tokens')
        with patch('sandbox.demand_rewrite.ask',side_effect=model):
            self.assertEqual(world.handle('/wiki/First')['status'],503)
        self.assertIsNone(world.read('pages','First'))

    def test_removed_link_is_plain_text_and_nonpage_entities_have_no_title_rule(self):
        from sandbox.demand_rewrite import apply,visible
        spec=copy.deepcopy(SPEC);spec['entities'].append({'id':'plan','kind':'event','source_title':'','title':'A plan','aliases':[],'exists':True})
        tree=html.fromstring('<p><a href="/wiki/Old_Institute" title="Old Institute">Historical plan</a></p>')
        nodes=surfaces(tree)
        edits=[{'id':n['id'],'text':''} for n in nodes if n['field'] in ('href','title')]
        apply(nodes,edits,{n['id'] for n in nodes})
        self.assertEqual(tree.xpath('count(.//a)'),0)
        self.assertEqual(tree.xpath('string(.//span)'),'Historical plan')
        self.assertFalse(any(n['field'] in ('href','title') for n in visible(nodes)))
        self.assertEqual(identity_issues(nodes,spec),[])

    def test_benchmark_records_generation_errors_and_provider_blocks(self):
        from sandbox.demand_benchmark import run_case,cases
        from sandbox.rewrite_model import ProviderBlocked
        for repeat,error in [(1,ValueError('rejected')),(2,ProviderBlocked('account blocked'))]:
            with patch('sandbox.demand.WorldService.ensure',side_effect=error):
                result=run_case(self.root,cases()[0],normalize(SCENARIO),'world-sonnet-high',repeat)
            expected=['failed','failed'] if repeat==1 else ['blocked','not_run']
            self.assertEqual([p['status'] for p in result['pages']],expected)
            self.assertTrue((self.root/f'leadership--world-sonnet-high--{repeat}'/'benchmark.json').exists())

    def test_structured_world_is_not_limited_by_legacy_fact_slot_cap(self):
        s=copy.deepcopy(SCENARIO)
        s['world_model']['facts']=[{**SPEC['facts'][0],'predicate':'property_'+str(i),'value':str(i)} for i in range(140)]
        create(self.root/'world',s,'test')
        world=WorldService(self.root/'world',Source,lambda d,s,f,*a:(d,f,[]));self.addCleanup(world.close)
        with patch('sandbox.demand_rewrite.review_peers'):
            world.ensure('First')
        self.assertEqual(len(world.facts()),140)

    def test_display_titles_use_the_same_normalization_as_routes(self):
        s=copy.deepcopy(SCENARIO)
        s['world_model']['entities'][0]['source_title']='Old_Institute'
        s['world_model']['entities'][0]['title']='New_Institute'
        self.assertEqual(normalize(s)['display_titles'],{'Old Institute':'New Institute'})

    def test_entities_without_articles_do_not_create_routes(self):
        spec=copy.deepcopy(SPEC);spec['entities'].append({'id':'handover','kind':'event','source_title':'','title':'Planned handover','aliases':[],'exists':True})
        validate(spec)
        create(self.root/'world',{**SCENARIO,'world_model':spec},'test')
        world=WorldService(self.root/'world');self.addCleanup(world.close)
        self.assertEqual(world.resolve('Planned handover'),'Planned handover')
        self.assertNotIn('',world.scenario['display_titles'])

    def test_utf8_survives_publication_projection_and_extract(self):
        create(self.root/'world',SCENARIO,'test')
        sentence='Mira Shah — director; café and naïve research.'
        document=('<div class="mw-parser-output"><p>'+sentence+'</p></div>').encode()
        world=WorldService(self.root/'world',Source,lambda d,s,f,*a:(document,f,[]));self.addCleanup(world.close)
        with patch('sandbox.demand_rewrite.review_peers'):
            page=world.ensure('First')
        self.assertIn(sentence,world.bytes(page['text_blob']).decode())
        response=world.handle('/w/api.php?action=query&prop=extracts&explaintext=1&titles=First')
        result=json.loads(world.bytes(response['body']))
        self.assertEqual(next(iter(result['query']['pages'].values()))['extract'],sentence)

    def test_latest_page_uses_world_date_and_explicit_revision_uses_revision_date(self):
        create(self.root/'world',SCENARIO,'test');seen=[]
        def writer(d,s,f,*args):seen.append(s['_document_date']);return d,f,[]
        world=WorldService(self.root/'world',Source,writer);self.addCleanup(world.close)
        with patch('sandbox.demand_rewrite.review_peers') as review:
            world.ensure('Latest')
            world.ensure('Historical',4)
        self.assertEqual(seen,['2026-09-18','2026-09-17'])
        self.assertEqual([c.args[2] for c in review.call_args_list],seen)
        self.assertEqual(review.call_args_list[1].args[4][0]['revision_at'],'2026-09-18')

    def test_large_document_encoding_retains_all_fields(self):
        from sandbox.demand_rewrite import document_packet
        document=('<div class="mw-parser-output">'+''.join('<p title="metadata">Text '+str(i)+'</p>' for i in range(6000))+'</div>').encode()
        nodes=surfaces(html.fromstring(document));packet=document_packet(nodes)
        self.assertIsInstance(packet,dict)
        self.assertEqual([dict(zip(packet['fields'],row)) for row in packet['nodes']],__import__('sandbox.demand_rewrite',fromlist=['visible']).visible(nodes))

    def test_review_diff_retains_every_changed_or_removed_original_field(self):
        from sandbox.demand_rewrite import review_original_changes
        before=[{'id':0,'block':0,'field':'text','tag':'p','value':'Original'},
                {'id':1,'block':1,'field':'text','tag':'p','value':'Unchanged'},
                {'id':2,'block':2,'field':'href','tag':'a','value':'/wiki/Removed'}]
        after=[{**before[0],'value':'Changed'},before[1]]
        fields=list(before[0])
        diff=review_original_changes({'fields':fields,'nodes':[[n[k] for k in fields] for n in before]},after)
        self.assertEqual(diff,[before[0],before[2]])
        reconstructed={n['id']:n for n in after};reconstructed.update({n['id']:n for n in diff})
        self.assertEqual(list(reconstructed.values()),before)

    def test_cross_page_contradiction_blocks_publication(self):
        create(self.root/'world',SCENARIO,'test')
        world=WorldService(self.root/'world',Source,lambda d,s,f,*a:(d,f,[]));self.addCleanup(world.close)
        with patch('sandbox.demand_rewrite.review_peers'):
            world.ensure('First')
        with patch('sandbox.demand_rewrite.ask',return_value={'accepted':False,'issues':['Incompatible claim']}):
            self.assertEqual(world.handle('/wiki/Second')['status'],503)
        self.assertIsNone(world.read('pages','Second'))
        self.assertIsNotNone(world.read('pages','First'))

    def test_opus_roles_and_invalid_models(self):
        s={**SCENARIO,'models':{'reviewer':{'model':'claude-opus-5','effort':'high'}}}
        self.assertEqual(settings(s,'reviewer')['model'],'claude-opus-5')
        with self.assertRaises(ValueError):settings({**s,'models':{'reviewer':{'model':'unknown'}}},'reviewer')

    def test_haiku_writer_uses_structured_output_without_adaptive_thinking(self):
        from sandbox.demand_world import ask,obj,S
        scenario={**SCENARIO,'models':{'writer':{'model':'claude-haiku-4-5-20251001'}}}
        with patch('sandbox.demand_world.call_claude',return_value={'answer':'ok'}) as provider:
            ask(Store(self.root/'haiku'),scenario,'writer','test','system',{},obj({'answer':S}))
        payload=provider.call_args.args[0]
        self.assertNotIn('thinking',payload)
        self.assertNotIn('effort',payload['output_config'])
        self.assertEqual(payload['output_config']['format']['type'],'json_schema')

    def test_invalid_haiku_patch_escalates_without_publishing_it(self):
        scenario={**SCENARIO,'models':{'writer':{'model':'claude-haiku-4-5-20251001'},'reviewer':{'model':'claude-sonnet-5'}}}
        models=[]
        def model(store,s,role,stage,system,data,schema):
            if stage=='page-plan':return {'summary':'check','changes':[{'blocks':sorted({n['block'] for n in data['document']}),'reason':'check','facts':[]}]}
            if stage.startswith('patch'):
                models.append(settings(s,'writer')['model'])
                if models[-1].startswith('claude-haiku-'):return {'edits':[{'id':999999,'text':'invalid'}]}
                return {'edits':[]}
            return {'accepted':True,'issues':[],'claims':[]}
        with patch('sandbox.demand_rewrite.ask',side_effect=model):
            output,_,_=rewrite(b'<div class="mw-parser-output"><p>Unrelated history.</p></div>',scenario,normalize(scenario)['world_facts'],'Topic',Store(self.root/'escalate'),'2026-01-01')
        self.assertEqual(models,['claude-haiku-4-5-20251001','claude-sonnet-5'])
        self.assertIn(b'Unrelated history.',output)

    def test_peer_packet_preserves_all_fields_without_patch_ids(self):
        from sandbox.demand_rewrite import peer_document,visible,shared_peer_fields,readable_document
        packet=peer_document(DOC)
        expected=[[n['field'],n['value']] for n in visible(surfaces(html.fromstring(DOC))) ]
        self.assertEqual([entry for block in packet['blocks'] for entry in block],expected)
        long={'blocks':[[['href','https://en.wikipedia.org/wiki/A_very_long_repeated_article_identity_for_testing']]],'format':'test'}
        first,second,shared=shared_peer_fields(long,long)
        for compact in (first,second):
            self.assertEqual([[shared[e] if isinstance(e,int) else e for e in b] for b in compact['blocks']],long['blocks'])
        readable=readable_document(surfaces(html.fromstring(DOC)))
        self.assertTrue(any('The Old Institute studies water.' in block['text'] for block in readable))

    def test_large_peer_comparisons_cover_every_cross_page_block_pair(self):
        from sandbox.demand_rewrite import peer_pairs
        left={'blocks':[[['text','Left '+str(i)+' x'*30]] for i in range(6)]}
        right={'blocks':[[['text','Right '+str(i)+' y'*30]] for i in range(4)]}
        pairs=list(peer_pairs(left,right,limit=450))
        observed={(a[0][1],b[0][1]) for l,r in pairs for a in l['blocks'] for b in r['blocks']}
        expected={(a[0][1],b[0][1]) for a in left['blocks'] for b in right['blocks']}
        self.assertEqual(observed,expected)
        self.assertGreater(len(pairs),1)

    def test_seed_fork_preserves_bytes_and_allows_new_requests(self):
        from sandbox.demand import fork_world
        create(self.root/'source',SCENARIO,'sha256:test')
        source=WorldService(self.root/'source',Source,lambda d,s,f,*a:(d,f,[]))
        with patch('sandbox.demand_rewrite.review_peers'):
            original=source.ensure('First')
        digest=source.freeze(self.root/'frozen');source.close()
        scenario={**SCENARIO,'models':{'writer':{'model':'claude-haiku-4-5-20251001'}}}
        fork_world(self.root/'frozen',self.root/'growing',scenario)
        world=WorldService(self.root/'growing',Source,lambda d,s,f,*a:(d,f,[]));self.addCleanup(world.close)
        self.assertFalse(world.readonly)
        self.assertEqual(world.ensure('First'),original)
        with patch('sandbox.demand_rewrite.review_peers'):
            self.assertEqual(world.ensure('Second')['title'],'Second')
        self.assertEqual(verify(self.root/'frozen'),digest)
        with self.assertRaisesRegex(ValueError,'scope differ'):
            fork_world(self.root/'frozen',self.root/'invalid',{**scenario,'as_of':'2027-01-01'})

    def test_history_metadata_does_not_generate_historical_pages(self):
        create(self.root/'world',SCENARIO,'test')
        world=WorldService(self.root/'world',Source,lambda d,s,f,*a:(d,f,[]));self.addCleanup(world.close)
        with patch('sandbox.demand_rewrite.review_peers'):world.ensure('First')
        with patch.object(world,'history',side_effect=AssertionError('Unexpected historical generation')):
            result=world.handle('/w/api.php?action=query&titles=First&prop=revisions&rvprop=ids|user|comment&rvlimit=3')
        self.assertEqual(result['status'],200)
        records=next(iter(json.loads(world.bytes(result['body']))['query']['pages'].values()))['revisions']
        self.assertEqual([r['revid'] for r in records],[5,4,3])
        self.assertTrue(all(r['user']==r['comment']=='' for r in records))
        self.assertEqual(world.db.execute('SELECT count(*) FROM versions').fetchone()[0],1)

    def test_all_metadata_and_links_reach_reviewer_and_repairs_localize(self):
        store=Store(self.root/'audit');calls=[]
        def model(store,scenario,role,stage,system,data,schema):
            calls.append((stage,data))
            if stage=='page-plan':return {'summary':'rename','changes':[{'blocks':list({n['block'] for n in data['document']}),'reason':'rename','facts':['institute.name']}]}
            if stage.startswith('patch'):
                # First pass intentionally misses tooltip to exercise deterministic repair.
                return {'edits':[{'id':n['id'],'text':n['value'].replace('Old_Institute','New_Institute').replace('Old Institute','New Institute')}
                                 for n in data['nodes'] if 'Old' in n['value'] and (not stage.startswith('patch-0') or n['field']!='title')]}
            return {'accepted':True,'issues':[],'claims':[{'key':'institute.name','value':'New Institute','blocks':[]}]}
        with patch('sandbox.demand_rewrite.ask',side_effect=model):
            result,facts,edits=rewrite(DOC,SCENARIO,normalize(SCENARIO)['world_facts'],'Old Institute',store,'2026-01-01')
        self.assertNotIn(b'Old',result);self.assertIn(b'Founded in 1980.',result)
        reviews=[d for stage,d in calls if stage.startswith('page-review')]
        self.assertEqual(len(reviews),2)
        self.assertTrue(any(a[1]=='href' for n in reviews[0]['final_document'] for a in n['attributes']))
        self.assertEqual(facts,normalize(SCENARIO)['world_facts'])
        first=[d for stage,d in calls if stage.startswith('patch-0')][0]
        second=[d for stage,d in calls if stage.startswith('patch-1')][0]
        self.assertLess(len(second['nodes']),len(first['nodes']))

    def test_unknown_or_conflicting_claims_cannot_publish(self):
        def model(*args):
            stage=args[3]
            if stage=='page-plan':return {'summary':'unchanged','changes':[]}
            if stage.startswith('patch'):return {'edits':[]}
            return {'accepted':True,'issues':[],'claims':[{'key':'institute.name','value':'Other','blocks':[]}]}
        with patch('sandbox.demand_rewrite.ask',side_effect=model),self.assertRaises(Rejected):
            rewrite(DOC,SCENARIO,normalize(SCENARIO)['world_facts'],'Old Institute',Store(self.root/'reject'),'2026-01-01')

    def test_alias_before_first_request_and_explicit_absence_when_frozen(self):
        s=copy.deepcopy(SCENARIO);s['world_model']['entities'].append({'id':'launch','kind':'event','source_title':'Launch',
                    'title':'Launch','aliases':['The Launch'],'exists':False})
        create(self.root/'world',s,'test');world=WorldService(self.root/'world',Source,lambda d,s,f,*a:(d,f,[]));self.addCleanup(world.close)
        self.assertEqual(world.resolve('New Institute'),'Old Institute')
        self.assertEqual(world.resolve('Research Institute'),'Old Institute')
        self.assertTrue(world.ensure('The Launch')['missing'])
        self.assertEqual(len(list((world.root/'attempts').iterdir())),0)
        digest=world.freeze(self.root/'frozen');frozen=WorldService(self.root/'frozen');self.addCleanup(frozen.close)
        self.assertEqual(frozen.handle('/wiki/The_Launch')['coverage'],'world_missing');self.assertEqual(verify(frozen.root),digest)

    def test_page_cannot_extend_facts_and_editing_spec_requires_new_world(self):
        create(self.root/'world',SCENARIO,'test')
        world=WorldService(self.root/'world',Source,lambda d,s,f,*a:(d,{**f,'invented.slot':'new'},[]))
        try:
            self.assertEqual(world.handle('/wiki/Old_Institute')['status'],503)
            self.assertIsNone(world.read('pages','Old Institute'))
        finally:world.close()
        config=json.loads((self.root/'world/world.json').read_bytes());config['scenario']['facts'].append('Changed rule')
        (self.root/'world/world.json').write_text(json.dumps(config))
        with self.assertRaisesRegex(ValueError,'changed'):WorldService(self.root/'world')

    @patch('sandbox.demand_rewrite.review_peers')
    def test_preparation_reports_budget_gaps_and_checks_representations(self,review_peers):
        from sandbox.demand_prepare import prepare
        create(self.root/'world',SCENARIO,'test')
        document=b'<div class="mw-parser-output"><p>New Institute <a href="/wiki/Neighbor">Neighbor</a></p></div>'
        world=WorldService(self.root/'world',Source,lambda d,s,f,*a:(document,f,[]));self.addCleanup(world.close)
        report=prepare(world,['New Institute'],max_pages=1,depth=1)
        self.assertEqual(report['status'],'incomplete');self.assertEqual(report['unvisited'],['Neighbor'])
        self.assertEqual(len(report['pages'][0]['routes']),5)
        report=prepare(world,['New Institute'],max_pages=2,depth=1)
        self.assertEqual(report['status'],'ready')


if __name__=='__main__':unittest.main()
