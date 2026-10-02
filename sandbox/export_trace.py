"""Export one sealed run as an expanded, shareable HTML trajectory without grading."""
import argparse
import json
import re
from pathlib import Path

from sandbox.archive import verify
from sandbox.report_changes import world_changes
from truman.report import COPY_SCRIPT, STYLE, changes_section, esc, trajectory


def export(source, destination):
    source, destination = Path(source), Path(destination)
    digest = verify(source)
    run = json.loads((source / 'run.json').read_bytes())
    if run.get('worlds') and 'world_changes' not in run:
        run['world_changes'] = world_changes(run)
    body = re.sub(r'<details\b([^>]*)>', lambda m: '<details' + m[1] + ('>' if re.search(r'\bopen\b', m[1]) else ' open>'), trajectory(run))
    document = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(run['id'])} trace</title><style>{STYLE}
pre{{max-height:none;overflow:visible}}</style></head><body><main>
<header><div class="masthead"><span><strong>Truman</strong> recorded trace</span><span>{esc(run.get('label') or run['id'])}</span></div>
<p class="question">{esc(run.get('prompt', ''))}</p>
<dl class="facts"><div><dt>Model</dt><dd>{esc(run.get('requested_model'))}</dd></div><div><dt>Effort</dt><dd>{esc(run.get('effort'))}</dd></div>
<div><dt>Status</dt><dd>{esc(run['status'])}</dd></div></dl>
<p class="lede">All steps are expanded. Network records show what the server sent; tool results show what the tool returned to the agent.
Long previews can be truncated; complete bytes remain in the sealed recording. Private reasoning is not inferred.</p></header>
{changes_section([run])}<h2>Trace</h2>{body}<footer>Recording: {esc(run['id'])}<br>Integrity seal: {esc(digest)}</footer>
</main><script>{COPY_SCRIPT}</script></body></html>'''
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
