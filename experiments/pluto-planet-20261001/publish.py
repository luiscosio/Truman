"""Build a frozen synthetic world from a captured reference world and the hand edits in edits.yaml.

No model writes or reviews these pages. Each edited page records its edits, so
trace reports show exactly what changed against the captured source.

    PYTHONPATH=. python experiments/pluto-planet-20261001/publish.py --reference data/live-worlds/pluto-wiki-reference-20261001 --check
    PYTHONPATH=. python experiments/pluto-planet-20261001/publish.py --reference data/live-worlds/pluto-wiki-reference-20261001 \
        --output data/live-worlds/pluto-wiki-manual-20261001 --frozen runs/pluto-worlds-20261001/wiki-manual-frozen
"""
import argparse
import json
import re
import shutil
import sqlite3
from pathlib import Path

import yaml
from lxml import html

from sandbox.archive import durable, encoded, seal, sha
from sandbox.demand import WorldService, create

EDITS = Path(__file__).with_name('edits.yaml')


def apply(text, rules, label):
    """Apply exact `find` rules, or `pattern` rules (regular expressions) where markup whitespace varies."""
    for rule in rules:
        expected = rule.get('count', 1)
        if 'pattern' in rule:
            changed, found = re.subn(rule['pattern'], lambda m: m.expand(rule['replace']), text)
        else:
            found = text.count(rule['find'])
            changed = text.replace(rule['find'], rule['replace'])
        if found != expected:
            raise ValueError(f'{label}: expected {expected} match(es), found {found}: {rule.get("find", rule.get("pattern"))[:90]!r}')
        text = changed
    return text


def plain(fragment):
    """Visible text of an HTML snippet, for the edit log reports display."""
    if not fragment.strip():
        return ''
    try:
        return ' '.join(html.fragment_fromstring(fragment, create_parent='div').text_content().split())
    except Exception:
        return fragment


def edited(world, record, rules):
    """The page record's HTML and text with this page's rules applied."""
    page = world.bytes(record['html_blob']).decode()
    document = apply(page, rules['html'], record['title'] + ' html')
    if 'wikitext' in rules:
        text = apply(world.bytes(record['text_blob']).decode(), rules['wikitext'], record['title'] + ' wikitext')
    else:
        text = world.site.render_text(html.fromstring(document.encode()))
    return page, document, text


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--reference', type=Path, required=True, help='Captured reference world (unchanged pages)')
    p.add_argument('--output', type=Path, help='New synthetic world to create')
    p.add_argument('--frozen', type=Path, help='Where to freeze the synthetic world')
    p.add_argument('--check', action='store_true', help='Only check that every rule matches')
    a = p.parse_args()
    source = WorldService(a.reference)
    pages = yaml.safe_load(EDITS.read_text())[source.site.id]
    try:
        for title, rules in pages.items():
            edited(source, source.read('pages', title), rules)
            print(f'{title}: {len(rules["html"])} html rules match' + (f', {len(rules["wikitext"])} wikitext rules match' if 'wikitext' in rules else ''))
    finally:
        source.close()
    if a.check:
        return
    config = json.loads((a.reference / 'world.json').read_bytes())
    scenario = {**config['scenario'], 'id': config['scenario']['id'].replace('-reference', '') + '-manual', 'condition': 'synthetic'}
    create(a.output, scenario, config['renderer_image'])
    reader = sqlite3.connect((a.reference / 'world.sqlite').resolve().as_uri() + '?mode=ro', uri=True)
    writer = sqlite3.connect(a.output / 'world.sqlite')
    try:
        reader.backup(writer)
    finally:
        reader.close()
        writer.close()
    for directory in ('attempts', 'blobs'):
        shutil.copytree(a.reference / directory, a.output / directory, dirs_exist_ok=True)
    world = WorldService(a.output)
    try:
        for title, rules in pages.items():
            record = world.read('pages', title)
            original, document, text = edited(world, record, rules)
            attempt, store = world.attempt()
            store.event('original', html_blob=store.blob(original.encode()))
            # A rule may describe itself with before/after text, e.g. a navbox entry moved between rows.
            log = [{'id': index, 'block': index, 'field': 'text', 'original': r.get('before', plain(r.get('find', ''))),
                    'replacement': r.get('after', plain(r['replace']))} for index, r in enumerate(rules['html'])]
            value = {**record, 'html_blob': world.blob(document.encode()), 'text_blob': world.blob(text.encode()),
                     'page': {**record['page'], 'sha256': sha(text.encode())}, 'attempt': attempt.name,
                     'edits_blob': store.blob(encoded(log)), 'generation_method': 'manual', 'validation_status': 'manual_reviewed'}
            store.event('manual_edit', html_blob=store.blob(document.encode()), edits_blob=value['edits_blob'], rules_sha256=sha(EDITS.read_bytes()))
            durable(attempt / 'accepted.json', encoded(value))
            seal(attempt)
            world.db.execute('UPDATE pages SET value=? WHERE key=?', (json.dumps(value), title))
            world.db.execute('UPDATE versions SET value=? WHERE key=? AND revision=?', (json.dumps(value), title, record['record']['revid']))
        world.db.commit()
        shutil.copy2(EDITS, a.output / 'edits.yaml')
        print(json.dumps({'world': str(a.output), 'frozen': str(a.frozen), 'seal': world.freeze(a.frozen)}))
    finally:
        world.close()


if __name__ == '__main__':
    main()
