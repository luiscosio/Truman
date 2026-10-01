import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from sandbox import demand_pair
from sandbox.archive import seal,verify


class PairTests(unittest.TestCase):
 def test_multiple_questions_preserve_all_cases_and_matched_controls(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'runs').mkdir();(root/'reports').mkdir()
   for condition in ('reference','synthetic'):
    for site in ('wiki','news'):
     p=root/(condition+'-'+site);p.mkdir();(p/'world.json').write_text(json.dumps({'scenario':{'condition':condition}}));seal(p)
   profile=root/'profile';profile.mkdir();seal(profile);profile_seal=verify(profile)
   tasks=[]
   for number in (1,2):
    task=root/f'task{number}.json';task.write_text(json.dumps({'id':f'task{number}','prompt':f'Question {number}','required_urls':[]}));tasks.append(task)
   calls=[];worlds=[]
   def run(command,**kwargs):
    identifier=command[command.index('--run-id')+1];condition=Path(command[command.index('--world')+1]).name.split('-')[0]
    worlds.append([Path(command[i+1]).name for i,arg in enumerate(command) if arg=='--world'])
    question=Path(command[command.index('--task-file')+1]).stem
    calls.append((question,condition));folder=root/'runs'/identifier;folder.mkdir()
    result={'id':identifier,'condition':condition,'status':'completed','experiment_sha256':question,'requested_model':'test-model','effort':'high','limits':{'seconds':300},'observed_tools':['WebFetch'],'agent_adapter':'test','network_mode':'managed','observed_message_models':['test-model']}
    (folder/'run.json').write_text(json.dumps(result));(folder/'network-profile.json').write_text(json.dumps({'profile_seal':profile_seal,'gateway_image':'fixed'}));(folder/'images.json').write_text('["same-agent","same-renderer"]');seal(folder)
    return SimpleNamespace(returncode=0)
   def report(results,identifier,destination):
    self.assertEqual(len(results),4);path=destination/(identifier+'.html');path.write_text('report');return path
   args=['demand_pair','--reference',str(root/'reference-wiki'),'--reference',str(root/'reference-news'),
         '--synthetic',str(root/'synthetic-wiki'),'--synthetic',str(root/'synthetic-news'),'--profile',str(profile),'--task-file',str(tasks[0]),'--task-file',str(tasks[1]),'--run-id','pair-test','--model','test-model']
   with patch.object(demand_pair,'ROOT',root),patch('sys.argv',args),patch.object(demand_pair.subprocess,'run',side_effect=run),patch.object(demand_pair,'write_report',side_effect=report),contextlib.redirect_stdout(io.StringIO()):demand_pair.main()
   self.assertEqual(calls,[('task1','reference'),('task1','synthetic'),('task2','synthetic'),('task2','reference')])
   self.assertEqual(worlds[0],['reference-wiki','reference-news']);self.assertEqual(worlds[1],['synthetic-wiki','synthetic-news'])
   cases=json.loads((root/'runs/pair-test/cases.json').read_text());self.assertEqual(len(cases),4);verify(root/'runs/pair-test')


if __name__=='__main__':unittest.main()
