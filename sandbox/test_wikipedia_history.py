import json
import tempfile
import unittest
from pathlib import Path

from sandbox.demand import WorldService, create
from sandbox.demand_prepare import prepare_history
from sandbox.sites.wikipedia.history import add_revision
from sandbox.test_demand import DOCUMENT, SCENARIO, Source, writer


class SpacedSource(Source):
    """Revision ids spaced as on Wikipedia (1000 apart), one per minute; revision 1100 is current."""
    def history(self, title, limit):
        return [{'revid': 1100 - 100 * i, 'parentid': 1000 - 100 * i, 'timestamp': '2026-09-17T12:%02d:00Z' % (59 - i),
                 'user': 'Editor', 'comment': 'edit %d' % (1100 - 100 * i)} for i in range(limit)]

    def acquire(self, title, revision=None):
        revision = revision or 1100
        return {'title': title, 'page_id': 42,
                'record': {'revid': revision, 'parentid': revision - 100, 'timestamp': '2026-09-17T12:%02d:00Z' % (59 - (1100 - revision) // 100),
                           'user': 'Editor', 'comment': 'edit %d' % revision},
                'source': 'wiki text of revision %d' % revision, 'document': DOCUMENT.replace(b'Charles III', b'Charles III, revision %d' % revision)}


class AddedRevisionTests(unittest.TestCase):
    def test_added_revision_is_listed_served_and_parented(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'world'
            create(root, {**SCENARIO, 'condition': 'synthetic', 'revision_comments': 'source', 'wikipedia': {'revision_metadata': 'preserve'}}, 'sha256:test')
            world = WorldService(root, SpacedSource, writer)
            try:
                world.ensure('Monarchy')
                prepare_history(world, ['Monarchy'], 10, ['2026-09-17T12:55:10Z'])  # captures revision 700 (12:55)
                base = json.loads(world.db.execute('SELECT value FROM versions WHERE key=? AND revision=?', ('Monarchy', 700)).fetchone()[0])
                changed = {**base, 'html_blob': world.blob(b'<p>The event happened.</p>'), 'text_blob': world.blob(b'The event happened.')}
                with world.db:
                    revid = add_revision(world, 'Monarchy', '2026-09-17T12:55:30Z', 'Witness', 'Add the event (see talk)', changed)
                    with self.assertRaisesRegex(ValueError, 'newer than every captured revision'):
                        add_revision(world, 'Monarchy', '2026-09-18T00:00:00Z', 'Late', 'after the newest revision', changed)
                    # Another article edited later gives the wiki-wide id range for a newest revision.
                    world.db.execute('INSERT INTO cache VALUES (?,?)', ('history:Other:10', json.dumps([{'revid': 5100, 'parentid': 5000, 'user': 'X', 'timestamp': '2026-09-18T00:00:00Z', 'comment': ''}])))
                    current = json.loads(world.db.execute('SELECT value FROM pages WHERE key=?', ('Monarchy',)).fetchone()[0])
                    newest = add_revision(world, 'Monarchy', '2026-09-17T13:30:00Z', 'Witness', 'Follow-up', current)
                world.freeze(Path(temp) / 'frozen')
            finally:
                world.close()
            frozen = WorldService(Path(temp) / 'frozen')
            try:
                self.assertTrue(700 < revid < 800)
                listed = frozen.history_metadata('Monarchy', 10)
                self.assertEqual([r['revid'] for r in listed[4:7]], [800, revid, 700])
                self.assertEqual(listed[5]['comment'], 'Add the event (see talk)')
                self.assertEqual((listed[4]['parentid'], listed[5]['parentid']), (revid, 700))
                self.assertEqual(len(listed), 10)  # the window keeps its size
                self.assertEqual(frozen.bytes(frozen.revision(revid)['html_blob']), b'<p>The event happened.</p>')
                # Uncaptured revisions after it are now served from it, not from the older capture.
                self.assertEqual(frozen.bytes(frozen.ensure('Monarchy', 800)['html_blob']), b'<p>The event happened.</p>')
                # A revision after the newest becomes the current one.
                self.assertTrue(1100 < newest < 5100)
                self.assertEqual((listed[0]['revid'], listed[0]['parentid']), (newest, 1100))
                self.assertEqual(frozen.ensure('Monarchy')['record']['revid'], newest)
            finally:
                frozen.close()


if __name__ == '__main__':
    unittest.main()
