import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from sandbox.archive import Store
from sandbox.demand_model import Rejected
from sandbox.wikipedia_native import apply_patches,rewrite_source,lead,compact_patches,undefined_references


class NativeTests(unittest.TestCase):
 def test_native_edits_preserve_unrelated_templates_and_references(self):
  source='{{Infobox institution|name=Old Institute}}\n\nOld Institute opened in 1980.<ref>{{cite web|title=History}}</ref>\n\n== History ==\nA prior name.\n'
  result=apply_patches(source,[{'before':'name=Old Institute','after':'name=New Institute'},{'before':'Old Institute opened','after':'New Institute opened'}])
  self.assertIn('<ref>{{cite web|title=History}}</ref>',result);self.assertTrue(result.startswith('{{Infobox'))
  self.assertNotIn('History ==',lead(result));self.assertIn('1980',lead(result))
 def test_ambiguous_overlapping_and_rendered_patches_fail_closed(self):
  for source,edits in [('a a',[{'before':'a','after':'b'}]),('abcdef',[{'before':'abc','after':'x'},{'before':'bc','after':'y'}]),('wiki',[{'before':'wiki','after':'<html><body>oops</body></html>'}])]:
   with self.assertRaises(Rejected):apply_patches(source,edits)
 def test_source_like_html_examples_are_not_rejected_as_documents(self):
  self.assertIn('<html>',apply_patches('== HTML ==\n<syntaxhighlight><html></syntaxhighlight>',[]))
 def test_unchanged_source_preserves_editor_and_comment_without_model(self):
  with tempfile.TemporaryDirectory() as tmp,patch('sandbox.wikipedia_native.ask',side_effect=AssertionError('No model needed')):
   record={'revid':5,'timestamp':'2026-01-01T00:00:00Z','user':'Editor','comment':'Fixed a typo'}
   text,r,edits=rewrite_source('{{x}}',b'x',b'x',record,{},'Topic',Store(Path(tmp)))
   self.assertEqual((text,r,edits),('{{x}}',record,[]))
 def test_block_ids_and_review_control_publication(self):
  original=b'<div class="mw-parser-output"><p>Old Institute</p></div>';accepted=original.replace(b'Old',b'New')
  with tempfile.TemporaryDirectory() as tmp:
   scenario={'as_of':'2026-01-01','facts':['Rename the institute.'],'world_model':{}}
   responses=[{'edits':[{'id':0,'text':'{{name|New Institute}}','reason':'renamed'}],'comment':'Fixed a typo'},{'accepted':True,'issues':[]}]
   with patch('sandbox.wikipedia_native.ask',side_effect=responses):
    text,record,edits=rewrite_source('{{name|Old Institute}}\n\nUnchanged.',original,accepted,{'timestamp':'2026-01-01','user':'Editor','comment':'Fixed a typo'},scenario,'Institute',Store(Path(tmp)))
   self.assertEqual(text,'{{name|New Institute}}\n\nUnchanged.');self.assertEqual(record['user'],'Editor')

 def test_repairs_accumulate_instead_of_reverting_previous_edits(self):
  original=b'<div class="mw-parser-output"><p>Old</p></div>';accepted=original.replace(b'Old',b'New')
  responses=[{'edits':[{'id':0,'text':'New name.','reason':'rename'}],'comment':'Copyedit'},
             {'accepted':False,'issues':['Update role too.']},
             {'edits':[{'id':1,'text':'New role.','reason':'role'}],'comment':'Copyedit'},
             {'accepted':True,'issues':[]}]
  with tempfile.TemporaryDirectory() as tmp,patch('sandbox.wikipedia_native.ask',side_effect=responses) as ask:
   result=rewrite_source('Old name.\n\nOld role.',original,accepted,{'timestamp':'2026-01-01'},
                         {'as_of':'2026-01-01','facts':['Rename and change role.']},'Topic',Store(Path(tmp)))
   self.assertEqual(result[0],'New name.\n\nNew role.')
   self.assertEqual(ask.call_args_list[2].args[5]['source_blocks'][0]['source'],'New name.')

 def test_compact_patches_retain_unrelated_historical_changes(self):
  original='{{Info|age=45}}\n\n'+'This unchanged material. '*30+'The director is Old Name.\n\nEnd.'
  edited=original.replace('Old Name','New Name')
  patches=compact_patches(original,[{'before':original,'after':edited}])
  older=original.replace('age=45','age=44')
  self.assertEqual(apply_patches(older,patches),edited.replace('age=45','age=44'))

 def test_new_dangling_reference_is_repaired_before_semantic_review(self):
  original=b'<div class="mw-parser-output"><p>Old</p></div>';accepted=original.replace(b'Old',b'New')
  source='Keep.<ref name="a"/>\n\nExcluded.<ref name="a">Source</ref>'
  responses=[{'edits':[{'id':1,'text':'','reason':'excluded'}],'comment':''},
             {'edits':[{'id':0,'text':'Keep.<ref name="a">Source</ref>','reason':'preserve definition'}],'comment':''},
             {'accepted':True,'issues':[]}]
  with tempfile.TemporaryDirectory() as tmp,patch('sandbox.wikipedia_native.ask',side_effect=responses) as ask:
   text,_,_=rewrite_source(source,original,accepted,{'timestamp':'2026-01-01'},
                          {'as_of':'2026-01-01','facts':['Remove the excluded event.']},'Topic',Store(Path(tmp)))
   self.assertFalse(undefined_references(text));self.assertNotIn('Excluded',text)
   self.assertEqual([c.args[2] for c in ask.call_args_list],['native_writer','native_writer','native_reviewer'])

 def test_native_routes_preserve_source_and_metadata(self):
  import base64
  from lxml import etree
  from sandbox.demand import WorldService,create
  from sandbox.test_demand import Source,SCENARIO
  class NativeSource(Source):
   def acquire(self,*args):
    value=super().acquire(*args);value['source']='{{Info|name=Example}}\n\nLead.\n\n== Details ==\nBody.';return value
  scenario={**SCENARIO,'condition':'reference','wikipedia':{'raw':'native','revision_metadata':'preserve'}}
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'world';create(root,scenario,'test');w=WorldService(root,NativeSource)
   try:
    article=w.ensure('Topic');expected=w.bytes(article['text_blob']).decode()
    def body(path):
     result=w.handle(path);self.assertEqual(result['status'],200)
     return base64.b64decode(result['body_base64']) if 'body_base64' in result else w.bytes(result['body'])
    self.assertEqual(body('/w/index.php?title=Topic&action=raw').decode(),expected)
    revision=json.loads(body('/w/api.php?action=query&titles=Topic&prop=revisions&rvprop=user|comment|content'))['query']['pages']['42']['revisions'][0]
    self.assertEqual(revision['user'],'Editor');self.assertEqual(revision['comment'],'edit');self.assertEqual(revision['*'],expected)
    exported=etree.fromstring(body('/wiki/Special:Export/Topic'))
    self.assertEqual(exported.xpath('string(//*[local-name()="username"])'),'Editor')
    self.assertEqual(exported.xpath('string(//*[local-name()="text"])'),expected)
    parsed=json.loads(body('/w/api.php?action=parse&page=Topic&prop=wikitext&section=0'))
    self.assertIn('{{Info',parsed['parse']['wikitext']['*']);self.assertNotIn('Body.',parsed['parse']['wikitext']['*'])
   finally:w.close()


if __name__=='__main__':unittest.main()
