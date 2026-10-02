import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from sandbox.archive import encoded, sha
from sandbox.report_changes import world_changes


def world(root, edits):
    """A minimal world: one page whose accepted attempt holds an edit log."""
    blob = encoded(edits)
    attempt = root / 'attempts' / 'a1'
    (attempt / 'blobs').mkdir(parents=True)
    (attempt / 'blobs' / sha(blob)).write_bytes(blob)
    connection = sqlite3.connect(root / 'world.sqlite')
    connection.execute('CREATE TABLE pages (key TEXT PRIMARY KEY, value TEXT)')
    record = {'title': 'ISA', 'html_blob': 'x', 'attempt': 'a1', 'edits_blob': sha(blob), 'page': {'display_title': 'International Seabed Authority'}}
    connection.execute('INSERT INTO pages VALUES (?, ?)', ('ISA', json.dumps(record)))
    connection.commit()
    connection.close()


class WorldChangeTests(unittest.TestCase):
    def test_pages_the_run_received_list_their_net_edits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            world(root, [
                {'id': 4, 'block': 1, 'field': 'text', 'original': 'not adopted', 'replacement': 'adopted in 2025'},
                # A later repair pass rewrote the same field; the report shows source to final.
                {'id': 4, 'block': 1, 'field': 'text', 'original': 'adopted in 2025', 'replacement': 'adopted in 2026'},
                {'id': 9, 'block': 2, 'field': 'href', 'original': './A', 'replacement': './A'},
                {'block': 3, 'field': 'block', 'original': '<li><a href="./Pluto">Pluto</a></li>', 'replacement': ''},
            ])
            run = {'worlds': [{'site': 'wikipedia', 'root': str(root)}], 'events': [
                {'kind': 'network_request', 'host': 'en.wikipedia.org', 'path': '/wiki/ISA', 'evidence': {'title': 'ISA'}},
                {'kind': 'network_request', 'host': 'en.wikipedia.org', 'path': '/w/index.php?title=ISA&action=raw', 'evidence': {'title': 'ISA'}},
                {'kind': 'network_request', 'host': 'globalvoices.org', 'path': '/x/', 'evidence': {'title': 'x'}},
                {'kind': 'network_request', 'host': 'en.wikipedia.org', 'path': '/wiki/Missing', 'evidence': {'title': 'Missing'}}]}
            pages = world_changes(run)
        self.assertEqual(len(pages), 1)
        self.assertEqual((pages[0]['display_title'], pages[0]['path']), ('International Seabed Authority', '/wiki/ISA'))
        self.assertEqual([(e['label'], e['before'], e['after']) for e in pages[0]['edits']],
                         [('Text', 'not adopted', 'adopted in 2026'), ('Removed block', 'Pluto', '')])


if __name__ == '__main__':
    unittest.main()
