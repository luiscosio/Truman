"""Evidence-preserving grouping for the optional video exporter."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1] / 'tools/trace-video/trace_video.py'
spec = importlib.util.spec_from_file_location('trace_video', MODULE)
video = importlib.util.module_from_spec(spec)
spec.loader.exec_module(video)


def call(event_id, call_id, url):
    return {'id': event_id, 'kind': 'assistant', 'calls': [
        {'id': call_id, 'name': 'WebFetch', 'arguments': {'url': url}}]}


def network(event_id, path, status=200):
    return {'id': event_id, 'kind': 'network_request', 'host': 'example.test',
            'path': path, 'status': status}


def result(event_id, call_id, text):
    return {'id': event_id, 'kind': 'builtin_result', 'call': {'id': call_id},
            'result': {'content': text}}


class TraceVideoTests(unittest.TestCase):
    def test_interleaved_calls_are_joined_by_identity_not_nearest_event(self):
        run = {'status': 'completed', 'final_answer': 'Final.', 'events': [
            call(1, 'a', 'https://example.test/alpha'),
            call(2, 'b', 'https://example.test/beta'),
            network(3, '/alpha'), network(4, '/beta'),
            result(5, 'b', 'Beta'), result(6, 'a', 'Alpha'),
            {'id': 7, 'kind': 'assistant', 'text': 'Final.'}]}
        scenes = {s['key']: s for s in video.build_plan(run)}
        self.assertEqual(scenes['call-1']['event_ids'], [1, 3, 6])
        self.assertEqual(scenes['call-2']['event_ids'], [2, 4, 5])
        self.assertEqual(scenes['call-1']['body'], 'Alpha')
        self.assertEqual(scenes['final']['body'], 'Final.')
        self.assertEqual(scenes['final']['event_ids'], [7])

    def test_ambiguous_request_is_kept_as_an_independent_step(self):
        run = {'status': 'completed', 'events': [call(1,'a','https://example.test/a'),
            call(2,'b','https://example.test/b'),network(3,'/other'),
            result(4,'a','A'),result(5,'b','B')]}
        scenes = {s['key']: s for s in video.build_plan(run)}
        self.assertEqual(scenes['network-3']['event_ids'], [3])
        self.assertIsNone(scenes['call-1']['network'])
        self.assertIsNone(scenes['call-2']['network'])

    def test_error_status_and_missing_final_are_not_hidden(self):
        run = {'status': 'coverage_incomplete', 'events': [
            call(1,'a','https://example.test/missing'),network(2,'/missing',409),
            result(3,'a','Requested resource unavailable')]}
        scenes = {s['key']: s for s in video.build_plan(run)}
        self.assertEqual(scenes['call-1']['status'],409)
        self.assertIn('0 of 1', scenes['outcome']['body'])
        self.assertIn('coverage incomplete', scenes['outcome']['body'])
        self.assertEqual(scenes['final']['body'],'No final response was recorded.')

    def test_blob_tampering_and_traversal_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'capture/blobs';p.mkdir(parents=True)
            (p/('a'*64)).write_bytes(b'changed')
            with self.assertRaises(ValueError):video.find_blob(Path(tmp),'a'*64)
            with self.assertRaises(ValueError):video.find_blob(Path(tmp),'../../.env')

    def test_answer_pagination_keeps_every_word_and_heading_with_paragraph(self):
        class Font:
            def getlength(self, text):return len(text)
        text='First paragraph has several words to read.\n\n## Caveat\n\nSecond paragraph must follow its heading.'
        pages=video.text_pages(text,Font(),25,5)
        rendered=' '.join(' '.join(p) for p in pages)
        self.assertEqual(rendered.split(),video.plain(text).split())
        for page in pages:
            if 'Caveat' in page:self.assertIn('Second paragraph must',page)


if __name__ == '__main__':
    unittest.main()
