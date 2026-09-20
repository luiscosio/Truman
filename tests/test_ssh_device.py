import json,subprocess,unittest
from unittest.mock import patch
from sandbox.ssh_device.lab import ssh,stop

class SSHTests(unittest.TestCase):
 def test_remote_shell_text_is_never_executed_on_host_and_host_key_is_pinned(self):
  command='ip route; $(touch /host-test); echo hello'
  with patch('sandbox.ssh_device.lab.subprocess.run',return_value=subprocess.CompletedProcess([],0,'remote output','')) as run:
   result=ssh({'root':'/unused','client':'client','ssh_host':'172.20.0.2'},command)
  args=run.call_args.args[0]
  self.assertEqual(args[-1],command);self.assertEqual(args[:3],['docker','exec','client'])
  self.assertIn('StrictHostKeyChecking=yes',args);self.assertIn('BatchMode=yes',args)
  self.assertFalse(run.call_args.kwargs.get('shell',False));self.assertEqual(result['stdout'],'remote output')
 def test_timeout_is_an_observation_not_a_fabricated_device_reply(self):
  with patch('sandbox.ssh_device.lab.subprocess.run',side_effect=subprocess.TimeoutExpired('ssh',1)):
   result=ssh({'root':'/unused','client':'client','ssh_host':'172.20.0.2'},'sleep 50',timeout=1)
  self.assertEqual(result['exit_code'],124);self.assertIn('may still be running',result['stderr'])
 def test_cleanup_does_not_remove_resources_with_another_owner(self):
  state={'id':'mine','router':'router','backend':'backend','client':'client','networks':['network']}
  def run(args,**kwargs):
   self.assertNotIn('rm',args)
   labels={'truman.lab':'another'}
   body=[{'Labels':labels}] if args[1]=='network' else [{'Config':{'Labels':labels}}]
   return subprocess.CompletedProcess(args,0,json.dumps(body),'')
  with patch('sandbox.ssh_device.lab.subprocess.run',side_effect=run):stop(state)

if __name__=='__main__':unittest.main()
