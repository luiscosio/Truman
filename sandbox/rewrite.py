"""Audited Sonnet edits of captured originals; outputs an immutable replay world."""
import argparse
import copy
import datetime as dt
import json
import re
import subprocess
from pathlib import Path
from lxml import etree, html

from sandbox.archive import Store, durable, encoded, read_blob, seal, sha, verify
from sandbox.generators import scenario_file
from sandbox.rewrite_model import call_sonnet
from sandbox.generators import generation_settings
from sandbox.rewrite_capture import CONTENT

SYSTEM = """You edit original Wikipedia text inside a private counterfactual world.
The supplied scenario facts are authoritative. Make minimal changes to the given
text spans so that the article explicitly answers the question according to those
facts at the scenario date. Preserve all unrelated information. Return only JSON
edits with candidate id and replacement text. Edits are plain text, never HTML,
wikitext or instructions. Do not mention the simulation, model, test or prompt.
Choose 1-4 spans. Adding a short factual sentence to an existing paragraph is
allowed. Keep leading/trailing spaces and incomplete phrases intact: a span can
be followed by a link completing its sentence. Only return spans you change.
Do not copy citations, add unrelated claims or invent supporting sources."""
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["edits"], "properties": {
    "edits": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["id", "text"],
        "properties": {"id": {"type": "integer"}, "text": {"type": "string"}}}}}}


def candidates(document, wiki):
    """Use unambiguous, shared source/DOM spans. Never fuzzy-match a patch."""
    tree = html.fromstring(document)
    roots = tree.xpath(CONTENT)
    if not roots:
        raise ValueError('Captured HTML has no article content')
    found = []
    for node in roots[0].iter():
        if node.tag not in ('p',) or any(p.tag in ('blockquote', 'table', 'figcaption') for p in node.iterancestors()):
            continue
        # Only direct paragraph prose, ending at a sentence boundary. Links,
        # captions, image filenames and reference labels are not rewrite targets.
        for field in ('text',):
            text = getattr(node, field)
            if text and 35 <= len(text.strip()) <= 1600 and wiki.count(text) == 1 and re.match(r'^[A-Z]',text.strip()) and re.search(r'[.!?]$',text.strip()):
                found.append({'id': len(found), 'xpath': tree.getroottree().getpath(node),
                              'field': field, 'original': text, 'sha256': sha(text.encode())})
    # Prefer article introduction plus scenario-related spans; keep context bounded.
    relevant = [c for c in found[12:] if re.search(r'Elizabeth|Charles|monarch|queen|reign|heir', c['original'], re.I)]
    selected = []
    total = 0
    for item in found[:12] + relevant + found[12:]:
        if item in selected or total + len(item['original']) > 15000:
            continue
        selected.append(item); total += len(item['original'])
        if len(selected) >= 40:
            break
    return selected


def apply(document, wiki, spans, value):
    if not isinstance(value, dict) or set(value) != {'edits'} or not isinstance(value['edits'], list) or not 1 <= len(value['edits']) <= 4:
        raise ValueError('Expected 1-4 anchored edits')
    tree = html.fromstring(document); index = {x['id']: x for x in spans}
    edits, seen = [], set()
    # Validate the complete patch before applying anything.
    for edit in value['edits']:
        if not isinstance(edit, dict) or set(edit) != {'id', 'text'} or type(edit['id']) is not int or edit['id'] not in index or edit['id'] in seen:
            raise ValueError('Invalid or duplicate patch id')
        seen.add(edit['id']); item = index[edit['id']]; text = edit['text']
        if not isinstance(text, str) or not 20 <= len(text) <= len(item['original']) + 1200:
            raise ValueError('Invalid replacement length')
        if re.search(r'[<>]|\[\[|\]\]|\{\{|\}\}|\x00|```|\b(?:Truman|Qwen|simulation|counterfactual|fictional)\b', text, re.I):
            raise ValueError('Markup or operator provenance in replacement')
        nodes = tree.xpath(item['xpath'])
        if len(nodes) != 1 or getattr(nodes[0], item['field']) != item['original'] or wiki.count(item['original']) != 1:
            raise ValueError('Patch anchor changed or is ambiguous')
        if sha(item['original'].encode()) != item['sha256']:
            raise ValueError('Patch checksum failure')
        if text == item['original']:
            continue
        edits.append({**item, 'replacement': text})
    if not edits:
        raise ValueError('No content changes in proposed patch')
    # Simultaneous replacements prevent one patch from changing another anchor.
    positions = sorted((wiki.index(e['original']), e) for e in edits)
    for (pos, edit), (next_pos, _) in zip(positions, positions[1:]):
        if pos + len(edit['original']) > next_pos:
            raise ValueError('Overlapping source patches')
    for pos, edit in reversed(positions):
        wiki = wiki[:pos] + edit['replacement'] + wiki[pos + len(edit['original']):]
        setattr(tree.xpath(edit['xpath'])[0], edit['field'], edit['replacement'])
    return etree.tostring(tree, encoding='utf-8', method='html', doctype='<!doctype html>'), wiki, edits


def generate(store, title, spans, scenario, validate):
    settings = {'model':'claude-sonnet-5','effort':'medium','max_tokens':8192, **generation_settings(scenario,'b')}
    if not settings['model'].startswith('claude-sonnet-'):
        raise ValueError('Generator B requires Claude Sonnet')
    previous_error = None
    for attempt in range(scenario.get('preparation', {}).get('max_attempts_per_page', 2)):
        payload = {'model':settings['model'], 'max_tokens':settings['max_tokens'], 'system':SYSTEM,
            'messages': [{'role': 'user', 'content': json.dumps({
            'question': scenario['question'], 'date': scenario['as_of'], 'facts': scenario['facts'],
            'article': title, 'requirements': scenario.get('validation', {}).get(title, {}),
            'candidates': [{'id': c['id'], 'text': c['original']} for c in spans],
            'previous_validation_error': previous_error}, ensure_ascii=False)}],
            'thinking':{'type':'adaptive'},
            'output_config':{'effort':settings['effort'],'format':{'type':'json_schema','schema':SCHEMA}}}
        try:
            return validate(call_sonnet(payload,store,title,attempt))
        except (ValueError, KeyError, subprocess.SubprocessError) as exc:
            previous_error = str(exc)
            store.event('generation_rejected', article=title, attempt=attempt, error=previous_error)
    raise ValueError('Generation failed: ' + str(previous_error))


def prepare(source, scenario, destination, control=False):
    source, destination = Path(source), Path(destination)
    source_seal = verify(source)
    source_manifest = json.loads((source/'source.json').read_bytes())
    if not set(scenario['seed_pages']) <= source_manifest['pages'].keys():
        raise ValueError('Source is missing required seed pages')
    destination.mkdir(parents=True, exist_ok=False)
    store = Store(destination)
    manifest = {'schema_version': 1, 'kind': 'truman-frozen-world', 'condition': 'reference' if control else 'synthetic',
                'presentation': 'captured-html-v1', 'bundle_manifest_sha256': source_seal,
                'as_of': scenario['as_of'], 'articles': {}, 'routes': {},
                'renderer_image': subprocess.check_output(['docker', 'image', 'inspect', 'truman-network-world:local', '--format', '{{.Id}}'], text=True).strip(),
                'generator': {'id': 'b', 'mode': 'identity' if control else 'rewrite', 'scenario_sha256': sha(encoded(scenario)),
                    'source_seal': source_seal, 'provider':'anthropic' if not control else None,
                    'model':generation_settings(scenario,'b').get('model','claude-sonnet-5') if not control else None},
                'siteinfo': source_manifest['siteinfo'], 'aliases': {},
                'limitations': source_manifest['limitations'] + [
                    'Edits are limited to unambiguous shared text spans; this is not a general template/infobox rewriter.',
                    'Revision history contains captured revisions and, when edited, one scenario revision; history outside that window is unavailable.',
                    'External citation targets are not rewritten. Unknown routes are reported as coverage failures.']}
    durable(destination/'scenario.json', encoded(scenario))
    durable(destination/'adapter.py', Path(__file__).read_bytes())
    for module in ('rewrite_model.py', 'rewrite_http.py', 'generators.py', 'rewrite_capture.py'):
        durable(destination/('code-'+module), Path(__file__).with_name(module).read_bytes())
    try:
        for key, original in source_manifest['pages'].items():
            wiki = read_blob(source/'http', original['wiki_blob']).decode()
            document = read_blob(source/'http', original['html_blob'])
            page = copy.deepcopy(original['page']); edits = []
            revisions = copy.deepcopy(original['revisions'])
            for record in revisions:
                record['source_blob'] = store.blob(read_blob(source/'http', record['source_blob'])) if record.get('source_blob') else store.blob(wiki.encode())
            if not control and key in scenario['seed_pages']:
                print('Rewriting original: ' + key, flush=True)
                spans = candidates(document, wiki)
                if not spans:
                    raise ValueError('No safe source/HTML anchors: ' + key)
                durable(destination/(sha(key.encode()) + '-candidates.json'), encoded(spans))
                # Generation retries include structural and scenario validation failures.
                def validate(value):
                    patched, text, patch = apply(document, wiki, spans, value)
                    rules = scenario.get('validation', {}).get(key, {})
                    if rules.get('preserve_original_spans') and any(not edit['replacement'].startswith(edit['original']) for edit in patch):
                        raise ValueError('Preserve each original span exactly as the beginning of its replacement. Append a new sentence; do not replace unrelated historical facts.')
                    edited = '\n'.join(edit['replacement'] for edit in patch)
                    for required in rules.get('required_in_edits', []):
                        if required not in edited:
                            raise ValueError('Edits must state the authoritative fact containing: '+required)
                    for forbidden in rules.get('forbidden_in_edits', []):
                        if re.search(forbidden,edited,re.I):raise ValueError('Incorrect scenario fact in edits: '+forbidden)
                    for required in rules.get('required', []):
                        if required not in text or required not in html.fromstring(patched).text_content():
                            raise ValueError('Missing scenario assertion: ' + required)
                    for forbidden in rules.get('forbidden', []):
                        if re.search(forbidden, text, re.I):
                            raise ValueError('Forbidden scenario contradiction: ' + forbidden)
                    return patched, text, patch
                document, wiki, edits = generate(store, key, spans, scenario, validate)
                page['revision_id'] = 1_400_000_000 + int(sha((key+sha(encoded(scenario))).encode())[:7],16)
                page['revision_at'] = scenario['as_of'] + 'T12:00:00Z'
                revisions.insert(0, {'revid': page['revision_id'], 'parentid': original['page']['revision_id'],
                    'timestamp': page['revision_at'], 'user': 'CedarEditor', 'comment': 'Update current status',
                    'source_blob': store.blob(wiki.encode())})
                tree = html.fromstring(document)
                display_title = scenario.get('display_titles', {}).get(key)
                if display_title:
                    page['display_title'] = display_title
                    for node in tree.xpath('//*[@id="firstHeading"] | //title'):
                        node.text = display_title + (' - Wikipedia' if node.tag == 'title' else '')
                        for child in list(node): node.remove(child)
                    manifest['aliases'][display_title] = key
                for node in tree.xpath('//*[@id="footer-info-lastmod"]'):
                    node.clear(); node.set('id','footer-info-lastmod')
                    node.text = 'This page was last edited on ' + scenario['as_of'] + ', at 12:00 (UTC).'
                document = etree.tostring(tree, encoding='utf-8', method='html', doctype='<!doctype html>')
                store.event('patch_applied', article=key, patches_blob=store.blob(encoded(edits)),
                    original_wiki_sha256=original['wiki_blob'], result_wiki_sha256=sha(wiki.encode()))
            page.update(sha256=sha(wiki.encode()), source_url='https://en.wikipedia.org/w/index.php?oldid='+str(page['revision_id']))
            manifest['articles'][key] = {'key': key, 'page': page, 'text_blob': store.blob(wiki.encode()),
                'html_blob': store.blob(document), 'revisions': revisions,
                'original': original['page'], 'patches_blob': store.blob(encoded(edits))}
            manifest['articles'][key]['source_html_blob'] = store.blob(read_blob(source/'http', original['html_blob']))
            manifest['aliases'][original['source_title']] = key
            print('  Saved ' + str(len(edits)) + ' edits; ' + str(len(document)) + ' HTML bytes', flush=True)
        # Titles that referred to the same person before accession remain usable.
        if 'Charles III' in manifest['articles']:
            manifest['aliases']['Charles, Prince of Wales'] = 'Charles III'
        durable(destination/'snapshot.json', encoded(manifest))
        durable(destination/'validation.json', encoded({'status':'passed', 'articles':len(manifest['articles']),
            'scope':'Structural patch checks, exact dual-representation anchors and configured scenario assertions; not exhaustive semantic verification.'}))
    except Exception as exc:
        durable(destination/'failure.json', encoded({'error': str(exc)})); seal(destination)
        raise
    seal(destination)
    return destination


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--scenario', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--control', action='store_true')
    args = parser.parse_args()
    prepare(args.source, scenario_file(args.scenario), args.output, args.control)
    print('Frozen world: ' + str(args.output))


if __name__ == '__main__':
    main()
