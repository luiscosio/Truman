"""Filesystem RPC across the sandbox boundary; no credential-bearing network listener."""
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


def publish(path,value):
    temp=path.with_suffix('.partial');durable(temp,encoded(value));temp.rename(path)


class Worker:
    def __init__(self,world,queue):
        self.world=world;self.queue=Path(queue);self.queue.mkdir(parents=True,exist_ok=False)
        self.stop_event=threading.Event();self.thread=threading.Thread(target=self.loop,daemon=True)
        self.pool=ThreadPoolExecutor(max_workers=1)
        self.pending={};self.active=None
        self.request_seconds=float(world.scenario.get('on_demand',{}).get('request_seconds',90))
        self.thread.start()

    def failure(self,path,reason):
        durable(path.with_suffix('.failure.json'),encoded({'error':reason}))
        return {'status':503,'mime':'application/json; charset=utf-8',
                'body_base64':base64.b64encode(b'{"error":{"code":"temporarily_unavailable","info":"Please retry later."}}').decode(),
                'headers':{'Retry-After':'1'},'coverage':'generation_failed','evidence':None}

    def complete(self,path,value):
        output=path.with_name(path.name.replace('.request.json','.response.json'))
        if 'body_base64' not in value:
            value={**value,'body_base64':base64.b64encode(self.world.bytes(value['body'])).decode()}
        publish(output,value);self.pending.pop(path,None)

    def loop(self):
        while not self.stop_event.is_set():
            for path in sorted(self.queue.glob('*.request.json')):
                output=path.with_name(path.name.replace('.request.json','.response.json'))
                if output.exists():continue
                self.pending.setdefault(path,time.monotonic()+self.request_seconds)
                if self.active and self.active[0]==path:continue
                try:
                    request=json.loads(path.read_bytes())
                    value=self.world.handle_cached(request['path'])
                    if value is not None:self.complete(path,value)
                    elif self.active is None:
                        self.active=(path,self.pool.submit(self.world.handle,request['path']))
                except Exception as exc:
                    self.complete(path,self.failure(path,str(exc)))
            if self.active and self.active[1].done():
                path,future=self.active
                if path in self.pending:
                    try:value=future.result()
                    except Exception as exc:value=self.failure(path,str(exc))
                    self.complete(path,value)
                self.active=None
            for path,deadline in list(self.pending.items()):
                if time.monotonic()>=deadline:self.complete(path,self.failure(path,'World request deadline exceeded'))
            self.stop_event.wait(.05)
        # Every received request gets an explicit terminal outcome, even when
        # the target finishes while generation is still running.
        for path in self.queue.glob('*.request.json'):
            if not path.with_name(path.name.replace('.request.json','.response.json')).exists():
                self.complete(path,self.failure(path,'World service stopped before response completion'))

    def close(self):
        self.stop_event.set();self.thread.join(timeout=5)
        if self.thread.is_alive():raise RuntimeError('World dispatcher still running; cannot seal the run')
        self.pool.shutdown(wait=True,cancel_futures=True)


class Handler(BaseHTTPRequestHandler):
    def version_string(self):return 'MediaWiki'
    def log_message(self,*args):pass
    def do_HEAD(self):self.do_GET()
    def do_POST(self):self.send_error(405)
    def do_GET(self):
        if self.path=='/health':
            self.send_response(200);self.end_headers();self.wfile.write(b'ok');return
        if self.headers.get('Host','').split(':')[0] not in ('en.wikipedia.org','en.m.wikipedia.org','wikipedia.org','www.wikipedia.org'):
            self.send_error(403);return
        queue=Path(os.environ['WORLD_QUEUE']);identifier=uuid.uuid4().hex
        publish(queue/(identifier+'.request.json'),{'path':self.path,'method':self.command})
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
