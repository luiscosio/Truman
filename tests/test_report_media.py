import functools
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import unittest

from truman.cli import ReportHandler


class QuietHandler(ReportHandler):
    def log_message(self, *_args):pass


class ReportMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.root=Path(cls.temp.name)/'reports';cls.root.mkdir()
        (cls.root/'clip.mp4').write_bytes(b'0123456789abcdef')
        (cls.root/'poster.png').write_bytes(b'png-test')
        (cls.root/'.env').write_text('private')
        outside=Path(cls.temp.name)/'outside.json';outside.write_text('private')
        (cls.root/'escape.json').symlink_to(outside)
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(QuietHandler,directory=str(cls.root)))
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.thread.join();cls.temp.cleanup()

    def request(self,path,headers=None,method='GET'):
        c=HTTPConnection('127.0.0.1',self.server.server_port)
        c.request(method,path,headers=headers or {});r=c.getresponse()
        result=r.status,dict(r.getheaders()),r.read();c.close();return result

    def test_video_get_and_seek_range(self):
        status,headers,body=self.request('/clip.mp4')
        self.assertEqual((status,body),(200,b'0123456789abcdef'))
        status,headers,body=self.request('/clip.mp4',{'Range':'bytes=3-6'})
        self.assertEqual((status,body),(206,b'3456'))
        self.assertEqual(headers['Content-Range'],'bytes 3-6/16')
        self.assertEqual(headers['Content-Length'],'4')
        self.assertEqual(headers['Accept-Ranges'],'bytes')

    def test_suffix_open_ended_and_invalid_ranges(self):
        self.assertEqual(self.request('/clip.mp4',{'Range':'bytes=-3'})[2],b'def')
        self.assertEqual(self.request('/clip.mp4',{'Range':'bytes=13-'})[2],b'def')
        for value in ['bytes=99-','bytes=6-3','bytes=-0','bytes=','bytes=0-1,3-4']:
            with self.subTest(value=value):
                status,headers,body=self.request('/clip.mp4',{'Range':value})
                self.assertEqual(status,416);self.assertEqual(body,b'')
                self.assertEqual(headers['Content-Range'],'bytes */16')

    def test_head_obeys_ranges_and_confinement(self):
        status,headers,body=self.request('/clip.mp4',{'Range':'bytes=0-1'},'HEAD')
        self.assertEqual(status,206);self.assertEqual(body,b'')
        self.assertEqual(headers['Content-Length'],'2')
        for method in ['GET','HEAD']:
            for path in ['/.env','/escape.json','/../outside.json']:
                self.assertEqual(self.request(path,method=method)[0],404)
        self.assertEqual(self.request('/poster.png')[2],b'png-test')


if __name__=='__main__':unittest.main()
