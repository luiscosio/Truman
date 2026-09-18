"""Filesystem RPC across the sandbox boundary; no credential-bearing network listener."""
import base64
import json
import os
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from sandbox.archive import durable,encoded


def publish(path,value):
    temp=path.with_suffix('.partial');durable(temp,encoded(value));temp.rename(path)


class Worker:
    def __init__(self,world,queue):
        self.world=world;self.queue=Path(queue);self.queue.mkdir(parents=True,exist_ok=False)
        self.stop_event=threading.Event();self.thread=threading.Thread(target=self.loop,daemon=True)
        self.thread.start()

    def loop(self):
        while not self.stop_event.is_set():
            for path in sorted(self.queue.glob('*.request.json')):
                if self.stop_event.is_set():break
                output=path.with_name(path.name.replace('.request.json','.response.json'))
                if output.exists():continue
                try:
                    request=json.loads(path.read_bytes())
                    value=self.world.handle(request['path'])
                    if 'body_base64' not in value:
                        value={**value,'body_base64':base64.b64encode(self.world.bytes(value['body'])).decode()}
                except Exception as exc:
                    durable(path.with_suffix('.failure.json'),encoded({'error':str(exc)}))
                    value={'status':503,'mime':'text/plain','body_base64':base64.b64encode(b'Service temporarily unavailable').decode(),
                           'headers':{},'coverage':'generation_failed','evidence':None}
                publish(output,value)
            self.stop_event.wait(.05)

    def close(self):
        self.stop_event.set();self.thread.join(timeout=630)
        if self.thread.is_alive():raise RuntimeError('World generation still running; cannot seal the run')


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
