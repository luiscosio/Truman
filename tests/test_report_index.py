import json
import tempfile
import unittest
from pathlib import Path

from truman.report_index import index, series_of


class ReportIndexTests(unittest.TestCase):
    def test_runs_are_grouped_by_series_dated_and_linked_to_reports_and_write_ups(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs, reports, experiments = root / 'runs', root / 'reports', root / 'experiments'
            for name, condition in (('pair-20261001-v1-q1-reference', 'reference'), ('pair-20261001-v1-q1-synthetic', 'synthetic')):
                (runs / name).mkdir(parents=True)
                (runs / name / 'run.json').write_text(json.dumps({'status': 'completed', 'condition': condition, 'task': 'isa', 'requested_model': 'm'}))
            (runs / 'pair-20261001-v1').mkdir()
            (runs / 'pair-20261001-v1' / 'cases.json').write_text(json.dumps([{'status': 'completed'}, {'status': 'completed'}]))
            (runs / 'world-20260918-v2-frozen').mkdir()
            (runs / 'world-20260918-v2-frozen' / 'world.json').write_text('{}')
            (runs / 'world-20260918-v2-frozen' / 'seal.json').write_text('{}')
            reports.mkdir()
            (reports / 'pair-20261001-v1-q1-synthetic.html').write_text('report')
            (experiments / 'isa').mkdir(parents=True)
            (experiments / 'isa' / 'README.md').write_text('Run pair-20261001-v1-q1-synthetic and its pair.')
            (root / 'results').mkdir()
            (root / 'results' / 'WORLDS.md').write_text('Frozen as world-20260918-v2-frozen.')
            output, entries, series = index(runs, reports, experiments, root / 'results', reports / 'index.html')
            page = output.read_text()
            self.assertEqual((entries, series), (4, 2))
            self.assertLess(page.index('pair-20261001'), page.index('world-20260918'))
            self.assertIn('href="pair-20261001-v1-q1-synthetic.html"', page)
            self.assertIn('href="../experiments/isa/README.md"', page)
            self.assertIn('2 runs', page)
            self.assertIn('href="../results/WORLDS.md">results: WORLDS</a>', page)
            self.assertIn('>frozen<', page)

    def test_series_strip_member_suffixes(self):
        self.assertEqual(series_of('mac-musk-native-paired-20260920-v1-q2-synthetic'), 'mac-musk-native-paired-20260920')
        self.assertEqual(series_of('manual-monarchy-seeds-20260919-v6-frozen'), 'manual-monarchy-seeds-20260919')
        self.assertEqual(series_of('20260917T164827Z-suite-9c50e238-r1-c2'), '20260917T164827Z-suite-9c50e238')


if __name__ == '__main__':
    unittest.main()
