"""Revisions a world adds to an article's history: the edits a real event would leave.

A real change to a watched article arrives as an edit with a matching summary, often a
revert and a re-revert, and a talk-page thread. A world that only rewrites captured
revisions shows the change riding silently on some unrelated real edit. These helpers
weave added revisions into the article's cached revision lists, in time order, each with
an id between its neighbours; the next revision takes it as its parent, and its content
is stored like a captured revision's.
"""
import json
from datetime import datetime


def _time(stamp):
    return datetime.fromisoformat(stamp.replace('Z', '+00:00')).timestamp()


def windows(world, key):
    """Every cached newest-first revision list of `key`, as (cache key, size, records)."""
    prefix = 'history:' + key + ':'
    return [(k, int(k[len(prefix):]), json.loads(v)) for k, v in world.db.execute('SELECT key,value FROM cache WHERE key LIKE ?', ('history:%',))
            if k.startswith(prefix) and k[len(prefix):].isdigit()]


def _known_ids(world):
    """Every (timestamp, revision id) in the world's cached histories. Revision ids are
    numbered across the whole wiki, so an added one is placed among these by time."""
    known = set()
    for k, v in world.db.execute('SELECT key,value FROM cache WHERE key LIKE ?', ('history:%',)):
        if k.rpartition(':')[2].isdigit():
            known.update((r['timestamp'], r['revid']) for r in json.loads(v))
    return sorted(known)


def add_revision(world, key, timestamp, user, comment, value):
    """Insert one revision of `key` at `timestamp` that serves the text and HTML of `value`.

    `value` is a stored page version (a row of the versions table). A revision newer than
    every captured one becomes the article's current revision; its `value` should then be
    the current page. Returns the new id.
    """
    found = windows(world, key)
    widest = max(found, key=lambda w: len(w[2]), default=(None, 0, []))[2]
    older = [r for r in widest if r['timestamp'] <= timestamp]
    newer = [r for r in widest if r['timestamp'] > timestamp]
    if not older:
        raise ValueError(f'{key}: {timestamp} is before the captured revision history')
    before, after = older[0], (newer[-1] if newer else None)
    known = _known_ids(world)
    lower = max((k for k in known if k[0] <= timestamp), default=(before['timestamp'], before['revid']))
    upper = min((k for k in known if k[0] > timestamp), default=None)
    if upper is None:
        raise ValueError(f'{key}: {timestamp} is newer than every captured revision of the wiki')
    low = max(before['revid'], lower[1])
    high = min(after['revid'], upper[1]) if after else upper[1]
    if high - low < 2:
        raise ValueError(f'{key}: no free revision id between {low} and {high}')
    share = (_time(timestamp) - _time(lower[0])) / max(1, _time(upper[0]) - _time(lower[0]))
    revid = min(high - 1, max(low + 1, lower[1] + round((upper[1] - lower[1]) * share)))
    if world.db.execute('SELECT 1 FROM versions WHERE revision=?', (revid,)).fetchone():
        raise ValueError(f'{key}: revision id {revid} is taken')
    record = {'revid': revid, 'parentid': before['revid'], 'user': user, 'timestamp': timestamp, 'comment': comment}
    for cache_key, size, records in found:
        # A window holds the newest `size` revisions; a shorter one reaches the first revision.
        if len(records) < size or records[-1]['timestamp'] <= timestamp:
            records = sorted([*records, record], key=lambda r: r['timestamp'], reverse=True)[:size]
        if after:
            records = [{**r, 'parentid': revid} if r['revid'] == after['revid'] else r for r in records]
        world.db.execute('UPDATE cache SET value=? WHERE key=?', (json.dumps(records), cache_key))
    page = {**value['page'], 'revision_id': revid, 'revision_at': timestamp,
            'source_url': f'https://en.wikipedia.org/w/index.php?oldid={revid}'}
    added = {**value, 'record': record, 'page': page}
    if after:
        for table, where, args in (('versions', 'key=? AND revision=?', (key, after['revid'])), ('pages', 'key=?', (key,))):
            row = world.db.execute(f'SELECT value FROM {table} WHERE {where}', args).fetchone()
            stored = json.loads(row[0]) if row else None
            if stored and stored.get('record', {}).get('revid') == after['revid']:
                stored['record'] = {**stored['record'], 'parentid': revid}
                world.db.execute(f'UPDATE {table} SET value=? WHERE {where}', (json.dumps(stored), *args))
    else:
        world.db.execute('UPDATE pages SET value=? WHERE key=?', (json.dumps(added), key))
    world.db.execute('INSERT INTO versions VALUES (?,?,?)', (key, revid, json.dumps(added)))
    return revid
