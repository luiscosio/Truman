"""Export one sealed run as an expanded, shareable HTML trajectory without grading."""
import argparse
import json
import re
from pathlib import Path

from sandbox.archive import verify
from truman.report import STYLE, esc, trajectory


def export(source, destination):
    source, destination = Path(source), Path(destination)
    digest = verify(source)
    run = json.loads((source / 'run.json').read_bytes())
    body = re.sub(r'<details\b([^>]*)>', lambda m: '<details' + m[1] + ('>' if re.search(r'\bopen\b', m[1]) else ' open>'), trajectory(run))
    document = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(run['id'])} · Trace</title><style>{STYLE}
pre,.answer{{max-height:none;overflow:visible}}</style></head><body><main>
<header><div class="eyebrow">RECORDED AGENT TRAJECTORY</div><h1>{esc(run.get('label') or run['id'])}</h1>
<p>{esc(run.get('requested_model'))} · Effort: {esc(run.get('effort'))} · Status: {esc(run['status'])}</p>
<p class="subtle">All steps expanded. Network records show served responses; tool results show what the tool returned to the agent.
Long network previews can be truncated; complete bytes remain in the sealed recording. Private reasoning is not inferred.</p></header>
{body}<footer>Recording: {esc(run['id'])}<br>Integrity seal: {esc(digest)}</footer>
</main></body></html>'''
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('x', encoding='utf-8') as stream:
        stream.write(document)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    print(export(args.source, args.destination))


if __name__ == '__main__':
    main()
