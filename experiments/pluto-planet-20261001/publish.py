"""Build a frozen synthetic world from a captured reference world and the hand edits in edits.yaml.

No model writes or reviews these pages. Each edited page records its edits, so
trace reports show exactly what changed against the captured source. A page with
`from:` does not exist on the real site; it is created from that captured page.

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
        if found != expected and not (rule.get('optional') and found == 0):
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


def misses(text, rules):
    """Rules that would not match `text` the stated number of times."""
    out = []
    for rule in rules:
        found = len(re.findall(rule['pattern'], text)) if 'pattern' in rule else text.count(rule['find'])
        if found != rule.get('count', 1) and not (rule.get('optional') and found == 0):
            out.append((found, rule.get('find', rule.get('pattern'))[:80]))
        else:
            text = apply(text, [rule], '')
    return out


def anchors(world, title, since):
    """Captured older revisions dated on or after `since`: (kept, dropped).

    The world keeps the earliest and the latest; revisions between them are
    served from the earliest (WorldService.nearest_capture), so fewer texts
    need the world's edits.
    """
    current = world.read('pages', title)['record']['revid']
    rows = [json.loads(v) for (v,) in world.db.execute('SELECT value FROM versions WHERE key=?', (title,))]
    found = sorted((r for r in rows if not r.get('missing') and r['record']['revid'] != current and r['record']['timestamp'] >= since),
                   key=lambda r: r['record']['timestamp'])
    kept = found[:1] + found[-1:] if len(found) > 1 else found
    return kept, [r for r in found if r not in kept]


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
    spec = yaml.safe_load(EDITS.read_text())
    pages, since = spec[source.site.id], spec.get('history', {}).get('edited_from')
    try:
        for title, rules in pages.items():
            edited(source, source.read('pages', rules.get('from', title)), rules)
            print(f'{title}: {len(rules["html"])} html rules match' + (f', {len(rules["wikitext"])} wikitext rules match' if 'wikitext' in rules else ''))
            for old in anchors(source, title, since)[0] if since and 'history' in rules else []:
                html_misses = misses(source.bytes(old['html_blob']).decode(), rules['history']['html'])
                text_misses = misses(source.bytes(old['text_blob']).decode(), rules['history'].get('wikitext', []))
                print(f'  revision {old["record"]["revid"]} ({old["record"]["timestamp"][:10]}): '
                      + ('all rules match' if not html_misses + text_misses else f'{len(html_misses)} html, {len(text_misses)} wikitext misses'))
                for found, rule in html_misses + text_misses:
                    print(f'    found {found}: {rule!r}')
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
            record = world.read('pages', rules.get('from', title))
            original, document, text = edited(world, record, rules)
            if 'from' in rules:
                # A page the real site never had: same template, its own identity.
                revid = int(sha(document.encode())[:12], 16)
                record = {**record, 'title': title, 'record': {**record['record'], 'revid': revid},
                          'page': {**record['page'], 'title': title, 'display_title': title, 'page_id': int(sha(title.encode())[:12], 16),
                                   'revision_id': revid, 'source_url': world.site.url(title)}}
                original = ''
            attempt, store = world.attempt()
            store.event('original', html_blob=store.blob(original.encode()), template=rules.get('from'))
            # A rule may describe itself with before/after text, e.g. a navbox entry moved between rows.
            log = [{'id': index, 'block': index, 'field': 'text', 'original': r.get('before', plain(r.get('find', ''))),
                    'replacement': r.get('after', plain(r['replace']))} for index, r in enumerate(rules['html'])]
            if 'from' in rules:
                log = [{'id': 0, 'block': 0, 'field': 'text', 'original': '',
                        'replacement': 'New page, not on the real site: ' + plain(document[document.find('<h1'):document.find('</h1>') + 5])}]
            value = {**record, 'html_blob': world.blob(document.encode()), 'text_blob': world.blob(text.encode()),
                     'page': {**record['page'], 'sha256': sha(text.encode())}, 'attempt': attempt.name,
                     'edits_blob': store.blob(encoded(log)), 'generation_method': 'manual', 'validation_status': 'manual_reviewed'}
            store.event('manual_edit', html_blob=store.blob(document.encode()), edits_blob=value['edits_blob'], rules_sha256=sha(EDITS.read_bytes()))
            if since and 'history' in rules:
                kept, dropped = anchors(world, title, since)
                for old in kept:
                    old_html = apply(world.bytes(old['html_blob']).decode(), rules['history']['html'], f'{title} {old["record"]["timestamp"]} html')
                    old_text = apply(world.bytes(old['text_blob']).decode(), rules['history']['wikitext'], f'{title} {old["record"]["timestamp"]} wikitext')
                    revised = {**old, 'html_blob': world.blob(old_html.encode()), 'text_blob': world.blob(old_text.encode()),
                               'page': {**old['page'], 'sha256': sha(old_text.encode())}, 'generation_method': 'manual'}
                    world.db.execute('UPDATE versions SET value=? WHERE key=? AND revision=?', (json.dumps(revised), title, old['record']['revid']))
                    store.event('manual_history_edit', revision=old['record']['revid'], html_blob=revised['html_blob'], text_blob=revised['text_blob'])
                for old in dropped:
                    world.db.execute('DELETE FROM versions WHERE key=? AND revision=?', (title, old['record']['revid']))
                store.event('history_anchors', kept=[o['record']['revid'] for o in kept], dropped=[o['record']['revid'] for o in dropped])
            durable(attempt / 'accepted.json', encoded(value))
            seal(attempt)
            world.db.execute('INSERT OR REPLACE INTO pages VALUES (?,?)', (title, json.dumps(value)))
            world.db.execute('INSERT OR REPLACE INTO versions VALUES (?,?,?)', (title, record['record']['revid'], json.dumps(value)))
        world.db.commit()
        shutil.copy2(EDITS, a.output / 'edits.yaml')
        print(json.dumps({'world': str(a.output), 'frozen': str(a.frozen), 'seal': world.freeze(a.frozen)}))
    finally:
        world.close()


if __name__ == '__main__':
    main()
