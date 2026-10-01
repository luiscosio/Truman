"""Index every recorded run, suite and world by date, series and experiment.

Run folders are sealed records, so they are never moved. This page sorts them
instead: newest first, grouped into series, with each run's report and the
experiment write-up that documents it.

    python -m truman.report_index --runs runs --reports reports --experiments experiments --results docs/results
"""
import argparse
import datetime as dt
import html
import json
import os
import re
from pathlib import Path

DATE = re.compile(r'(20\d{6})(?:T\d{6}Z)?')
# Suffixes that distinguish members of one series: versions, questions, conditions, frozen copies.
MEMBER = re.compile(r'(?:-(?:v\d+|q\d+|r\d+|c\d+|reference|synthetic|frozen|followup|verified|review|work))+$')

STYLE = """
:root{--ink:#192d2a;--muted:#65736d;--paper:#f5f3ec;--card:#fff;--line:#d9ded4;--green:#276658;--warn:#985411;--bad:#ad3039}
@media(prefers-color-scheme:dark){:root{--ink:#e5ebe6;--muted:#9aa8a1;--paper:#141a18;--card:#1c2421;--line:#2f3b36;--green:#7cc4ad;--warn:#e0a35c;--bad:#ef8a8f}}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,sans-serif}
main{max-width:1200px;margin:auto;padding:40px 24px}h1{font-size:36px;letter-spacing:-.03em;margin:6px 0}
.eyebrow{font:700 12px/1.3 ui-monospace,monospace;letter-spacing:.15em;color:var(--green)}.subtle{color:var(--muted)}
input{width:100%;font:inherit;padding:10px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink);margin:18px 0}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px 20px;margin:14px 0}
section h2{font-size:17px;margin:0 0 4px;overflow-wrap:anywhere}section .meta{font-size:13px;color:var(--muted)}
table{width:100%;border-collapse:collapse;margin-top:10px;font-size:13px}td{border-top:1px solid var(--line);padding:7px 8px 7px 0;vertical-align:top;overflow-wrap:anywhere}
td:first-child{font-family:ui-monospace,monospace;width:42%}.kind{font:700 11px ui-monospace,monospace;color:var(--muted)}
.ok{color:var(--green)}.warn{color:var(--warn)}.bad{color:var(--bad)}a{color:var(--green)}
@media(max-width:700px){td:first-child{width:auto}main{padding:24px 16px}h1{font-size:28px}}
"""
SCRIPT = """
const box=document.querySelector('input');
box.addEventListener('input',()=>{const q=box.value.toLowerCase();
for(const s of document.querySelectorAll('section'))s.hidden=q&&!s.textContent.toLowerCase().includes(q);});
"""


def read(path):
    try:
        return json.loads(path.read_bytes())
    except (OSError, ValueError):
        return None


def describe(folder):
    """Kind, status and details of one run-folder entry."""
    run, cases = read(folder / 'run.json'), read(folder / 'cases.json')
    if cases is not None:
        statuses = sorted({c.get('status', 'incomplete') for c in cases})
        return {'kind': 'suite', 'status': ', '.join(statuses) or 'empty', 'detail': f'{len(cases)} runs'}
    if run is not None:
        detail = ' · '.join(str(v) for v in (run.get('condition'), run.get('task'), run.get('requested_model') or run.get('model')) if v)
        return {'kind': 'agent run', 'status': run.get('status', 'unknown'), 'detail': detail}
    if (folder / 'world.json').exists():
        return {'kind': 'world', 'status': 'frozen' if (folder / 'seal.json').exists() else 'growing', 'detail': ''}
    worlds = [p.parent.name for p in folder.glob('*/world.json')]
    if worlds:
        return {'kind': 'worlds', 'status': 'sealed' if (folder / 'seal.json').exists() else 'open', 'detail': ', '.join(sorted(worlds))}
    return {'kind': 'artifact', 'status': 'sealed' if (folder / 'seal.json').exists() else 'unsealed', 'detail': ''}


def date_of(folder):
    found = DATE.search(folder.name)
    if found:
        return found.group(1)
    return dt.datetime.fromtimestamp(folder.stat().st_mtime, dt.timezone.utc).strftime('%Y%m%d')


def series_of(name):
    return MEMBER.sub('', name)


def documented(experiments, results):
    """Write-ups (experiment READMEs and results documents) with the text that names runs."""
    found = []
    for folder in sorted(p for p in experiments.iterdir() if p.is_dir()) if experiments.exists() else []:
        text = ' '.join(p.read_text(errors='replace') for p in folder.rglob('*') if p.suffix in ('.md', '.json'))
        found.append((folder / 'README.md' if (folder / 'README.md').exists() else folder, 'experiment: ' + folder.name, text))
    for document in sorted(results.glob('*.md')) if results.exists() else []:
        found.append((document, 'results: ' + document.stem, document.read_text(errors='replace')))
    return found


def index(runs, reports, experiments, results, output):
    docs = documented(experiments, results)
    entries = []
    for folder in sorted(p for p in runs.iterdir() if p.is_dir()):
        info = describe(folder)
        report = next((p for p in (reports / (folder.name + '.html'), folder / 'report.html') if p.exists()), None)
        writeups = [(path, label) for path, label, text in docs if folder.name in text]
        entries.append({'name': folder.name, 'date': date_of(folder), 'series': series_of(folder.name), 'report': report,
                        'writeups': writeups, **info})
    groups = {}
    for entry in entries:
        groups.setdefault((entry['date'], entry['series']), []).append(entry)
    base = output.parent

    def link(path, label):
        return f'<a href="{html.escape(os.path.relpath(path, base))}">{html.escape(label)}</a>'

    def status(value):
        tone = 'ok' if value in ('completed', 'frozen', 'sealed', 'prepared') else 'bad' if 'fail' in value or value == 'error' else 'warn'
        return f'<span class="{tone}">{html.escape(value)}</span>'
    sections = []
    for (date, series), members in sorted(groups.items(), key=lambda item: (item[0][0], item[0][1]), reverse=True):
        writeups = sorted({w for m in members for w in m['writeups']})
        rows = ''.join(
            f'<tr><td>{html.escape(m["name"])}</td><td><span class="kind">{m["kind"]}</span></td><td>{status(m["status"])}</td>'
            f'<td>{html.escape(m["detail"])}</td><td>{link(m["report"], "report") if m["report"] else ""}</td></tr>'
            for m in sorted(members, key=lambda m: m['name']))
        notes = ' · '.join(link(path, label) for path, label in writeups)
        day = f'{date[:4]}-{date[4:6]}-{date[6:]}'
        sections.append(f'<section><h2>{html.escape(series)}</h2><div class="meta">{day} · {len(members)} '
                        f'{"entry" if len(members) == 1 else "entries"}{" · " + notes if notes else ""}</div><table>{rows}</table></section>')
    page = (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Truman run index</title><style>{STYLE}</style></head><body><main><div class="eyebrow">TRUMAN</div><h1>Run index</h1>'
            f'<p class="subtle">{len(entries)} recorded entries in {html.escape(str(runs))}, newest first. Run folders are sealed and stay where '
            f'they are; this page sorts them. Generated {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC.</p>'
            f'<input type="search" placeholder="Filter by name, kind, status, task or experiment" aria-label="Filter">'
            f'{"".join(sections)}</main><script>{SCRIPT}</script></body></html>')
    output.write_text(page)
    return output, len(entries), len(groups)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--runs', type=Path, default=Path('runs'))
    p.add_argument('--reports', type=Path, default=Path('reports'))
    p.add_argument('--experiments', type=Path, default=Path('experiments'))
    p.add_argument('--results', type=Path, default=Path('docs/results'), help='Results documents that name runs')
    p.add_argument('--output', type=Path, help='Default: <reports>/index.html')
    a = p.parse_args()
    output, entries, groups = index(a.runs, a.reports, a.experiments, a.results, a.output or a.reports / 'index.html')
    print(f'{output}: {entries} entries in {groups} series')


if __name__ == '__main__':
    main()
