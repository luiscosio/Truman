"""What each world changed on the pages an agent read, for trace reports.

A world keeps every accepted page's edit log in its attempt. Reports show
those edits next to the requests that served the page, so a reader sees
exactly which text the agent was given that differs from the captured source.
"""
import json
import sqlite3
from pathlib import Path

from lxml import html

from sandbox.archive import read_blob
from sandbox.sites import load

LABELS = {'text': 'Text', 'tail': 'Text', 'href': 'Link target', 'title': 'Tooltip', 'alt': 'Image description',
          'aria-label': 'Accessible label', 'content': 'Page metadata', 'datetime': 'Date attribute',
          'block': 'Removed block', 'move': 'Moved entry', 'footnote': 'Removed footnote',
          'footnote_marker': 'Removed citation marker'}


def page_record(root, title):
    """The world's committed record for a page key, or None."""
    database = Path(root) / 'world.sqlite'
    if not database.exists():
        return None
    connection = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        row = connection.execute('SELECT value FROM pages WHERE key=?', (title,)).fetchone()
    finally:
        connection.close()
    return json.loads(row[0]) if row else None


def text_of(markup):
    try:
        return ' '.join(html.fromstring(markup).text_content().split())
    except (ValueError, TypeError):
        return markup


def page_edits(root, record):
    """Net edits for one page: repeated passes on a field collapse to first before, last after."""
    if not record.get('edits_blob') or not record.get('attempt'):
        return []
    log = json.loads(read_blob(Path(root) / 'attempts' / record['attempt'], record['edits_blob']))
    merged = {}
    for index, entry in enumerate(log):
        field = entry.get('field', 'text')
        key = (entry.get('block'), field, entry.get('id')) if 'id' in entry else ('entry', index)
        before = text_of(entry.get('original', '')) if field == 'block' else entry.get('original', '')
        if key in merged:
            merged[key]['after'] = entry.get('replacement', '')
        else:
            merged[key] = {'label': LABELS.get(field, field.replace('_', ' ').capitalize()), 'field': field,
                           'before': before, 'after': entry.get('replacement', '')}
    return [e for e in merged.values() if e['before'] != e['after']]


def world_changes(run):
    """One entry per distinct world page the run's requests were served from."""
    hosts = {}
    for world in run.get('worlds') or []:
        for host in load(world['site']).hosts:
            hosts[host] = world
    pages, seen = [], set()
    for event in run.get('events', []):
        title = (event.get('evidence') or {}).get('title') if event.get('kind') == 'network_request' else None
        world = hosts.get(event.get('host'))
        if not title or not world or (event['host'], title) in seen:
            continue
        seen.add((event['host'], title))
        record = page_record(world['root'], title)
        if record is None or 'html_blob' not in record:
            continue
        pages.append({'host': event['host'], 'site': world['site'], 'title': title,
                      'display_title': (record.get('page') or {}).get('display_title') or title,
                      'path': event['path'], 'edits': page_edits(world['root'], record)})
    return pages
