"""Record or compare route responses of frozen worlds, bypassing response caches.

Refactors of the site adapters must reproduce these responses exactly unless a
change is intended. Targets come from recorded agent traffic plus --target.
"""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit
from sandbox.archive import encoded, sha


def targets(runs, extra):
    found = dict.fromkeys(extra)
    for log in sorted(p for root in runs for p in Path(root).glob('*/network.jsonl')):
        for line in log.read_bytes().splitlines():
            event = json.loads(line)
            target = event.get('path') or urlsplit(event.get('url', '')).path
            if target and target.startswith('/') and event.get('host', 'en.wikipedia.org').endswith('wikipedia.org'):
                found.setdefault(target)
    return list(found)


def record(world_root, paths):
    from sandbox.demand import WorldService
    from sandbox.demand_routes import respond
    world = WorldService(world_root)
    if not world.readonly:
        raise ValueError('Golden responses require a sealed, read-only world: ' + str(world_root))
    try:
        result = {}
        for target in paths:
            status, mime, body, headers, coverage, evidence = respond(world, target)
            result[target] = {'status': status, 'mime': mime, 'headers': headers, 'coverage': coverage,
                              'evidence': evidence, 'body_sha256': sha(body)}
        return result
    finally:
        world.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--world', type=Path, action='append', required=True)
    p.add_argument('--runs', type=Path, action='append', default=[], help='Folders whose */network.jsonl supply targets')
    p.add_argument('--target', action='append', default=[])
    p.add_argument('--targets-file', type=Path, help='Additional targets, one per line')
    p.add_argument('--output', type=Path, help='Write a new golden file')
    p.add_argument('--compare', type=Path, help='Compare against a golden file')
    a = p.parse_args()
    if bool(a.output) == bool(a.compare):
        p.error('Use exactly one of --output or --compare')
    if a.compare:
        golden = json.loads(a.compare.read_bytes())
        paths = golden['targets']
    else:
        extra = a.target + (a.targets_file.read_text().split() if a.targets_file else [])
        paths = targets(a.runs, extra)
    worlds = {str(root): record(root, paths) for root in a.world}
    if a.output:
        a.output.write_bytes(encoded({'targets': paths, 'worlds': worlds}))
        print(len(paths), 'targets x', len(worlds), 'worlds recorded')
        return 0
    differences = [(world, target, field, before[field], worlds[world][target][field])
                   for world, responses in golden['worlds'].items() for target, before in responses.items()
                   for field in before if before[field] != worlds[world][target][field]]
    for world, target, field, before, after in differences:
        print(Path(world).parent.name + '/' + Path(world).name, target[:110], field, json.dumps(before)[:90], '->', json.dumps(after)[:90])
    print(len(differences), 'differences across', sum(map(len, golden['worlds'].values())), 'responses')
    return 1 if differences else 0


if __name__ == '__main__':
    raise SystemExit(main())
