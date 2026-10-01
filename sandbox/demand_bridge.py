"""Filesystem RPC across the sandbox boundary; no credential-bearing network listener.

The container Handler forwards each request with its Host. The host-side Worker
routes it to the world whose site profile serves that host.
"""
import base64
import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from sandbox.archive import durable,encoded


SERVER='truman-world'


def publish(path,value):
    temp=path.with_suffix('.partial');durable(temp,encoded(value));temp.rename(path)


class Worker:
    def __init__(self,worlds,queue):
        self.hosts={}
        for world in worlds:
            for host in world.site.hosts:
                if host in self.hosts:raise ValueError('Two worlds serve host '+host)
                self.hosts[host]=world
        self.queue=Path(queue);self.queue.mkdir(parents=True,exist_ok=False)
        self.stop_event=threading.Event();self.thread=threading.Thread(target=self.loop,daemon=True)
        self.pool=ThreadPoolExecutor(max_workers=1)
        self.pending={};self.active=None
        self.request_seconds=min(float(w.scenario.get('on_demand',{}).get('request_seconds',90)) for w in worlds)
        self.thread.start()

    def failure(self,path,world,reason):
        durable(path.with_suffix('.failure.json'),encoded({'error':reason}))
        if world is None:
            return {'status':403,'mime':'text/plain; charset=utf-8','body_base64':base64.b64encode(b'Forbidden').decode(),
                    'headers':{},'coverage':'blocked','evidence':{'reason':reason}}
        status,mime,body,headers=world.site.error('unavailable')
        return {'status':status,'mime':mime,'body_base64':base64.b64encode(body).decode(),
                'headers':headers,'coverage':'generation_failed','evidence':{'reason':reason}}

    def world_for(self,path):
        return self.hosts.get(json.loads(path.read_bytes()).get('host',''))

    def complete(self,path,value,world):
        output=path.with_name(path.name.replace('.request.json','.response.json'))
        if 'body_base64' not in value:
            value={**value,'body_base64':base64.b64encode(world.bytes(value['body'])).decode()}
        publish(output,value);self.pending.pop(path,None)

    def loop(self):
        while not self.stop_event.is_set():
            for path in sorted(self.queue.glob('*.request.json')):
                output=path.with_name(path.name.replace('.request.json','.response.json'))
                if output.exists():continue
                self.pending.setdefault(path,time.monotonic()+self.request_seconds)
                if self.active and self.active[0]==path:continue
                world=None
                try:
                    request=json.loads(path.read_bytes());world=self.hosts.get(request.get('host',''))
                    if world is None:
                        self.complete(path,self.failure(path,None,'No world serves host '+request.get('host','')),None);continue
                    value=world.handle_cached(request['path'])
                    if value is not None:self.complete(path,value,world)
                    elif self.active is None:
                        self.active=(path,world,self.pool.submit(world.handle,request['path']))
                except Exception as exc:
                    self.complete(path,self.failure(path,world,str(exc)),world)
            if self.active and self.active[2].done():
                path,world,future=self.active
                if path in self.pending:
                    try:value=future.result()
                    except Exception as exc:value=self.failure(path,world,str(exc))
                    self.complete(path,value,world)
                self.active=None
            for path,deadline in list(self.pending.items()):
                if time.monotonic()>=deadline:
                    world=self.world_for(path);self.complete(path,self.failure(path,world,'World request deadline exceeded'),world)
            self.stop_event.wait(.05)
        # Every received request gets an explicit terminal outcome, even when
        # the target finishes while generation is still running.
        for path in self.queue.glob('*.request.json'):
            if not path.with_name(path.name.replace('.request.json','.response.json')).exists():
                world=self.world_for(path);self.complete(path,self.failure(path,world,'World service stopped before response completion'),world)

    def close(self):
        self.stop_event.set();self.thread.join(timeout=5)
        if self.thread.is_alive():raise RuntimeError('World dispatcher still running; cannot seal the run')
        self.pool.shutdown(wait=True,cancel_futures=True)


class Handler(BaseHTTPRequestHandler):
    # The gateway removes this origin token; the agent never sees a Python server banner.
    def version_string(self):return SERVER
    def log_message(self,*args):pass
    def do_HEAD(self):self.do_GET()
    def do_POST(self):self.send_error(405)
    def do_GET(self):
        if self.path=='/health':
            self.send_response(200);self.end_headers();self.wfile.write(b'ok');return
        host=self.headers.get('Host','').split(':')[0].lower()
        queue=Path(os.environ['WORLD_QUEUE']);identifier=uuid.uuid4().hex
        publish(queue/(identifier+'.request.json'),{'host':host,'path':self.path,'method':self.command})
        output=queue/(identifier+'.response.json');deadline=time.monotonic()+600
        while not output.exists() and time.monotonic()<deadline:time.sleep(.05)
        if not output.exists():self.send_error(504);return
        value=json.loads(output.read_bytes());body=base64.b64decode(value['body_base64'])
        self.send_response(value['status']);self.send_header('Content-Type',value['mime']);self.send_header('Content-Length',str(len(body)))
        self.send_header('X-World-Coverage',value['coverage'])
        if value.get('evidence'):self.send_header('X-World-Evidence',base64.b64encode(encoded(value['evidence'])).decode())
        for key,val in value['headers'].items():self.send_header(key,val)
        self.end_headers()
        if self.command!='HEAD':
            try:self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError):pass


if __name__=='__main__':ThreadingHTTPServer(('0.0.0.0',80),Handler).serve_forever()
