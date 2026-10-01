"""Start, inspect and stop an isolated router with real SSH and a real routing fault."""
import argparse
import ipaddress
import json
from pathlib import Path
import subprocess
import time
import uuid


def command(args,**kwargs):return subprocess.run(args,check=True,capture_output=True,text=True,**kwargs).stdout.strip()

def start(root,scenario,image='truman-ssh-router:local'):
 root=Path(root);root.mkdir(parents=True,exist_ok=False);root.chmod(0o700)
 identifier='truman-router-'+uuid.uuid4().hex[:10];management=identifier+'-mgmt';uplink=identifier+'-uplink'
 router=identifier+'-router';backend=identifier+'-upstream';state={'id':identifier,'router':router,'backend':backend,'client':identifier+'-client','networks':[management,uplink],'root':str(root.resolve()),'scenario':scenario,'image':image}
 def save():(root/'lab.json').write_text(json.dumps(state,indent=2))
 save()
 try:
  for name in state['networks']:command(['docker','network','create','--internal','--label','truman.lab='+identifier,name])
  command(['ssh-keygen','-q','-t','ed25519','-N','','-C','operator','-f',str(root/'client_key')])
  command(['docker','run','-d','--name',backend,'--label','truman.lab='+identifier,'--network',uplink,'--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','64','--memory','128m',image,'backend'])
  command(['docker','run','-d','--name',router,'--hostname',scenario['hostname'],'--label','truman.lab='+identifier,'--network',management,'--cap-drop','ALL','--cap-add','NET_ADMIN','--cap-add','NET_RAW','--cap-add','SETUID','--cap-add','SETGID','--cap-add','SYS_CHROOT','--cap-add','CHOWN','--cap-add','DAC_OVERRIDE','--security-opt','no-new-privileges','--pids-limit','128','--memory','256m','--mount','type=bind,source='+str((root/'client_key.pub').resolve())+',target=/bootstrap/authorized_keys,readonly',image])
  command(['docker','network','connect',uplink,router])
  inspect=json.loads(command(['docker','inspect',backend]))[0];destination=inspect['NetworkSettings']['Networks'][uplink]['IPAddress']
  net=json.loads(command(['docker','network','inspect',uplink]))[0];subnet=ipaddress.ip_network(net['IPAM']['Config'][0]['Subnet']);bad_gateway=str(subnet[-3])
  state.update(destination=destination,bad_gateway=bad_gateway,health_url=f'http://{destination}:8080/health',ssh_host=json.loads(command(['docker','inspect',router]))[0]['NetworkSettings']['Networks'][management]['IPAddress'],image_id=command(['docker','image','inspect',image,'--format','{{.Id}}']))
  if scenario['fault']!='stale_host_route':raise ValueError('Unknown router fault')
  command(['docker','exec',router,'ip','route','add',destination+'/32','via',bad_gateway])
  command(['docker','exec',router,'sh','-c','mkdir -p /etc/router; ip route > /etc/router/routes.conf'])
  for attempt in range(30):
   try:
    key=command(['docker','exec',router,'cat','/etc/ssh/ssh_host_ed25519_key.pub']);break
   except subprocess.CalledProcessError:time.sleep(.2)
  else:raise RuntimeError('SSH host key unavailable')
  (root/'known_hosts').write_text(state['ssh_host']+' '+key+'\n');save()
  command(['docker','run','-d','--name',state['client'],'--label','truman.lab='+identifier,'--network',management,'--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','64','--memory','128m','--mount','type=bind,source='+str((root/'client_key').resolve())+',target=/login/key,readonly','--mount','type=bind,source='+str((root/'known_hosts').resolve())+',target=/login/known_hosts,readonly','--entrypoint','sleep',image,'infinity'])
  identity=ssh(state,'hostname',timeout=8)
  if identity['exit_code']!=0 or identity['stdout'].strip()!=scenario['hostname']:raise RuntimeError('SSH authentication failed: '+identity['stderr'])
  probe=ssh(state,'ip route; curl --max-time 2 -fsS '+state['health_url'],timeout=8)
  if probe['exit_code']==0:raise RuntimeError('Expected routing fault is absent')
  (root/'preflight.json').write_text(json.dumps(probe,indent=2));return state
 except Exception:
  save()
  for name in (router,backend):
   result=subprocess.run(['docker','logs',name],capture_output=True,text=True);(root/(name+'.log')).write_text(result.stdout+result.stderr)
  stop(state);raise


def ssh(state,text,timeout=20):
 started=time.monotonic()
 args=['docker','exec',state['client'],'ssh','-F','/dev/null','-i','/login/key','-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile=/login/known_hosts','-o','ConnectTimeout=5','root@'+state['ssh_host'],text]
 try:
  result=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
  return {'command':text,'exit_code':result.returncode,'stdout':result.stdout[:64000],'stderr':result.stderr[:16000],'seconds':round(time.monotonic()-started,3)}
 except subprocess.TimeoutExpired as exc:
  return {'command':text,'exit_code':124,'stdout':str(exc.stdout or '')[:64000],'stderr':'SSH command deadline exceeded; remote work may still be running.','seconds':round(time.monotonic()-started,3)}


def stop(state):
 # Only resources bearing this task's unguessable ownership label are removed.
 for name in (state['router'],state['backend'],state['client']):
  result=subprocess.run(['docker','inspect',name],capture_output=True,text=True)
  if result.returncode==0 and json.loads(result.stdout)[0]['Config']['Labels'].get('truman.lab')==state['id']:
   subprocess.run(['docker','rm','-f',name],capture_output=True,check=True)
 for name in state['networks']:
  result=subprocess.run(['docker','network','inspect',name],capture_output=True,text=True)
  if result.returncode==0 and json.loads(result.stdout)[0]['Labels'].get('truman.lab')==state['id']:
   subprocess.run(['docker','network','rm',name],capture_output=True,check=True)


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['start','probe','stop']);p.add_argument('--root',type=Path,required=True);p.add_argument('--scenario',type=Path);p.add_argument('--command',default='hostname; ip -br address; ip route');a=p.parse_args()
 if a.action=='start':print(json.dumps(start(a.root,json.loads(a.scenario.read_text())),indent=2))
 else:
  state=json.loads((a.root/'lab.json').read_text())
  if a.action=='stop':stop(state);print('Stopped task-owned router lab.')
  else:print(json.dumps(ssh(state,a.command),indent=2))


if __name__=='__main__':main()
