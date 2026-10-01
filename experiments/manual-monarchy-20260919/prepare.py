"""Reproduce this dated fixture from exact saved captures, with no model calls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from lxml import html
from sandbox.archive import read_blob, verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', required=True, type=Path,
                        help='External directory containing the two original sealed captures')
    parser.add_argument('--work-name', default='manual-monarchy-reproduction')
    parser.add_argument('--publish', action='store_true',
                        help='Create the v6 world and frozen copy; refuses existing destinations')
    args = parser.parse_args()
    recipe = Path(__file__).resolve().parent
    runs = args.runs.resolve()
    sources = runs / 'seed-live-sources-20260918-v1'
    verify(sources)
    verify(runs / 'mac-seed-live-coverage-diagnostic-20260918-v1')
    work = runs / args.work_name
    if work.parent != runs:
        parser.error('--work-name must be a single directory name')
    work.mkdir(exist_ok=False)
    for item in json.loads((recipe / 'sources.json').read_text()):
        i = item['index']
        source = sources / str(i)
        meta = json.loads((source / 'original.json').read_text())
        if meta['document_blob'] != item['document_blob'] or meta['title'] != item['title']:
            raise ValueError(f'Source {i} differs from the reviewed capture')
        tree = html.fromstring(read_blob(source / 'audit', item['document_blob']),
                               parser=html.HTMLParser(encoding='utf-8'))
        for n, node in enumerate(tree.iter()):
            if isinstance(node.tag, str):
                node.set('data-manual-id', str(n))
        (work / f'{i}-original.html').write_bytes(html.tostring(tree, encoding='utf-8'))
    for name in ('edit.py', 'refine.py', 'scan.py', 'publish.py'):
        shutil.copy2(recipe / name, work / name)
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1',
           'PYTHONPATH': str(recipe.parents[1])}
    for name in ('edit.py', 'scan.py'):
        subprocess.run([sys.executable, str(work / name)], env=env, check=True)
    for item in json.loads((recipe / 'candidates.json').read_text()):
        actual = hashlib.sha256((work / f"{item['index']}-candidate.html").read_bytes()).hexdigest()
        if actual != item['sha256']:
            raise ValueError(f"Candidate {item['index']} differs from the reviewed edition")
    if args.publish:
        subprocess.run([sys.executable, str(work / 'publish.py')], env=env, check=True)
    print(f'Reproduced candidates: {work}')


if __name__ == '__main__':
    main()
