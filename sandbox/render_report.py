"""Render a trace report for sealed runs, with the edits each world made to the pages they read.

Run folders are sealed and never modified; the report is written to a new file.

    python -m sandbox.render_report runs/<id>-q1-reference runs/<id>-q1-synthetic --output reports/<id>-review.html
"""
import argparse
import json
from pathlib import Path

from sandbox.archive import verify
from sandbox.report_changes import world_changes
from truman.report import report_html


def load(folder):
    folder = Path(folder)
    verify(folder)
    run = json.loads((folder / 'run.json').read_bytes())
    if run.get('worlds') and 'world_changes' not in run:
        run['world_changes'] = world_changes(run)
    return run


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('runs', nargs='+', type=Path, help='Sealed run folders containing run.json')
    p.add_argument('--output', type=Path, required=True, help='New HTML file; an existing file is never overwritten')
    p.add_argument('--batch', help='Batch name shown in the report; default: the first run\'s batch')
    a = p.parse_args()
    results = [load(folder) for folder in a.runs]
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open('x', encoding='utf-8') as stream:
        stream.write(report_html(results, a.batch or results[0].get('batch_id') or a.output.stem))
    print(a.output)


if __name__ == '__main__':
    main()
