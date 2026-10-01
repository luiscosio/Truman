"""Versioned, scenario-independent world specifications and audited compilation.

Facts are single-valued subject/predicate slots over half-open date intervals.
Unknowns remain unknown; published pages cannot extend the specification.
"""
import argparse
import copy
import datetime as dt
import json
import re
from pathlib import Path

from sandbox.archive import Store, durable, encoded, seal, sha
from sandbox.generators import generation_settings
from sandbox.rewrite_model import call_claude
from sandbox import sites


def obj(fields):
    return {'type':'object','properties':fields,'required':list(fields),'additionalProperties':False}


S={'type':'string'}
def arr(item):return {'type':'array','items':item}
ENTITY=obj({'id':S,'kind':S,'source_title':S,'title':S,'aliases':arr(S),'exists':{'type':'boolean'}})
FACT=obj({'subject':S,'predicate':S,'value':S,'valid_from':S,'valid_until':S,
          'origin':{'type':'string','enum':['given','derived']},'basis':S})
SPEC=obj({'version':{'type':'integer','enum':[1]},'entities':arr(ENTITY),'facts':arr(FACT),
          'invariants':arr(S),'preserve':arr(S),'unknowns':arr(S)})
REVIEW=obj({'accepted':{'type':'boolean'},'issues':arr(S)})


def settings(scenario,role):
    base=settings(scenario,'reviewer') if role in ('peer_reviewer','preservation_reviewer') else generation_settings(scenario,'b')
    configured={**base,**scenario.get('models',{}).get(role,{})}
    generation_settings({'generators':{'b':configured}},'b')
    return {'model':'claude-sonnet-5','effort':'high','max_tokens':16384,**configured}


def ask(store,scenario,role,stage,system,data,schema):
    config=settings(scenario,role)
    store.event('world_model_stage',role=role,stage=stage,model=config['model'],effort=config['effort'])
    payload={'model':config['model'],'max_tokens':config['max_tokens'],
        'system':system,'output_config':{'format':{'type':'json_schema','schema':schema}},
        'messages':[{'role':'user','content':json.dumps(data,ensure_ascii=False)}]}
    # Haiku 4.5 has neither adaptive thinking nor effort. Use its fast,
    # non-thinking structured-output mode; stronger roles can review its work.
    if not config['model'].startswith('claude-haiku-'):
        payload['thinking']={'type':'adaptive'}
        payload['output_config']['effort']=config['effort']
    return call_claude(payload,store,role,stage)


def validate(spec):
    if not isinstance(spec,dict) or set(spec)!=set(SPEC['properties']) or type(spec['version']) is not int or spec['version']!=1:
        raise ValueError('Invalid world specification')
    if len(encoded(spec))>200000:raise ValueError('World specification exceeds budget')
    if not isinstance(spec['entities'],list) or not isinstance(spec['facts'],list):raise ValueError('Invalid entity/fact lists')
    ids=set()
    for e in spec['entities']:
        if set(e)!=set(ENTITY['properties']) or type(e['exists']) is not bool:raise ValueError('Invalid entity')
        if not re.fullmatch('[a-z][a-z0-9_]{0,79}',e['id']) or e['id'] in ids:raise ValueError('Invalid or duplicate entity ID')
        ids.add(e['id'])
        for k in ('kind','title'):
            if not isinstance(e[k],str) or not e[k].strip():raise ValueError('Empty entity '+k)
        if not isinstance(e['source_title'],str):raise ValueError('Invalid source title')
        if not isinstance(e['aliases'],list):raise ValueError('Invalid aliases')
        for name in ([e['source_title'],e['title'],*e['aliases']] if e['source_title'] else []):
            if not isinstance(name,str) or not name.strip():raise ValueError('Empty alias')
    slots={}
    for f in spec['facts']:
        if set(f)!=set(FACT['properties']) or f['subject'] not in ids:raise ValueError('Invalid fact subject')
        if not re.fullmatch('[a-z][a-z0-9_]{0,79}',f['predicate']):raise ValueError('Invalid predicate')
        if f['origin'] not in ('given','derived') or not isinstance(f['basis'],str) or not f['basis'].strip():raise ValueError('Fact requires its basis')
        if not isinstance(f['value'],str) or not f['value'].strip():raise ValueError('Empty fact value')
        start=dt.date.fromisoformat(f['valid_from']) if f['valid_from'] else dt.date.min
        end=dt.date.fromisoformat(f['valid_until']) if f['valid_until'] else dt.date.max
        if start>=end:raise ValueError('Invalid fact interval')
        key=(f['subject'],f['predicate'])
        for a,b,value in slots.get(key,[]):
            if max(a,start)<min(b,end) and value!=f['value']:raise ValueError('Conflicting world fact: '+'.'.join(key))
        slots.setdefault(key,[]).append((start,end,f['value']))
    for field in ('invariants','preserve','unknowns'):
        if not isinstance(spec[field],list) or not all(isinstance(v,str) and v.strip() for v in spec[field]):raise ValueError('Invalid '+field)
    return spec


def title_index(spec,site):
    """Entity ID for every page title and alias, under the site's title normalization."""
    names={}
    for e in spec['entities']:
        for name in ([e['source_title'],e['title'],*e['aliases']] if e['source_title'] else []):
            key=site.key(name)
            if key in names and names[key]!=e['id']:raise ValueError('Ambiguous entity alias: '+name)
            names[key]=e['id']
    return names


def active_facts(spec,date):
    validate(spec);dt.date.fromisoformat(date)
    return {f["subject"]+'.'+f['predicate']:f['value'] for f in spec['facts']
            if (not f['valid_from'] or f['valid_from']<=date) and (not f['valid_until'] or date<f['valid_until'])}


def normalize(scenario):
    result=copy.deepcopy(scenario)
    if 'world_model' not in result:
        if result.get('rewrite_pipeline')=='world-v2':raise ValueError('Compile a world_model before using world-v2')
        return result
    spec=validate(result['world_model']);site=sites.for_scenario(result);title_index(spec,site)
    result['rewrite_pipeline']='world-v2'
    result['world_facts']=active_facts(spec,result['as_of'])
    result['display_titles']={site.key(e['source_title']):site.key(e['title']) for e in spec['entities'] if e['exists'] and e['source_title']}
    result['absent_titles']=sorted({site.key(n) for e in spec['entities'] if not e['exists'] and e['source_title']
                                   for n in [e['source_title'],e['title'],*e['aliases']]})
    for role in ('planner','writer','reviewer','peer_reviewer','preservation_reviewer'):settings(result,role)
    return result


def compile_world(scenario,store):
    """Compile once; semantic acceptance is audited, not a proof of consistency."""
    feedback=[];site=sites.for_scenario(scenario)
    for attempt in range(3):
        spec=ask(store,scenario,'planner','compile-'+str(attempt),
            'Compile a reusable alternate-world specification from operator rules. Rules are authoritative. '
            'Identify entities (people, organizations, places, events, technologies), stable IDs, source '+site.name+' titles, '
            'Use lowercase snake_case entity IDs and predicate names, matching [a-z][a-z0-9_]{0,79}; no dots, spaces or punctuation. '
            'world titles and aliases. source_title must be empty for an entity without its own article (e.g. a sub-event or facility); '
            'never reuse another entity article as its source_title or invent an article for every entity. '
            'Aliases are unambiguous article titles, not descriptions or generic words like the institute. '
            'Model relationships and events as facts with single-valued predicates. '
            'Use valid_from inclusive and valid_until exclusive ISO dates; empty means unbounded, never use the literal unknown. '
            'For current mutable properties whose start is unknown, use the world_date as the known-at lower bound, '
            'explain in basis that this is not an asserted change date, and list the actual start as unknown. '
            'For immutable event metadata (e.g. opening_year=1980), unbounded validity means the year remains a fact, '
            'not that the event happens continuously. Use one canonical direction for relationships, avoiding duplicate inverse facts. '
            'Year-only bounds may use January 1 as interval boundaries, not invented exact event dates; explain that in basis. '
            'Separate given facts from necessary derived consequences and cite their rule basis. '
            'Do not invent downstream history, arbitrary dates or facts merely to fill gaps: list unknowns. '
            'State what remains unchanged, temporal exceptions, and semantic invariants. '
            'exists=false only for article topics that cannot exist under explicit rules; ordinary topics with wrong claims still exist. '
            'Existing world_facts and display_titles are additional constraints. Do not include the target answer or task as a rewrite goal.',
            {'rules':scenario['facts'],'world_date':scenario['as_of'],
             'world_facts':scenario.get('world_facts',{}),'display_titles':scenario.get('display_titles',{}),
             'absent_titles':scenario.get('absent_titles',[]),'known_source_titles':scenario.get('source_titles',[]),'feedback':feedback},SPEC)
        try:validate(spec);title_index(spec,site)
        except ValueError as exc:
            feedback=[str(exc)];store.event('world_compilation_rejected',attempt=attempt,issues=feedback);continue
        review=ask(store,scenario,'reviewer','compile-review-'+str(attempt),
            'Check a proposed world specification against operator rules using this exact schema contract. '
            'Facts are immutable within a world; entities can exist without their own article (empty source_title). '
            'An entity may denote a cancelled plan, not a completed event. Fact intervals express when a proposition is known to hold. '
            'A world-date lower bound may mark known-at rather than the actual change date if basis says so. '
            'Unbounded immutable metadata like opening_year=1980 describes a permanent fact about a past event, not a continuous event. '
            'January 1 may be a year-granularity bound if explained in basis; do not demand unsupported day precision. '
            'Reject material contradictions, incompatible synonymous slots, missed required consequences, unjustified inventions, '
            'or changes to unrelated history. Do not reject harmless redundancy with invariants, inverse relations that agree, '
            'stylistic choices, or absence of details already represented by an interval. Unknowns are allowed. '
            'Do not demand fields the schema lacks. Return only actionable material issues; accept an adequate consistent specification.',
            {'scenario':{k:scenario.get(k) for k in ('facts','as_of','world_facts','display_titles','absent_titles')},'specification':spec},REVIEW)
        store.event('world_compilation_review',attempt=attempt,review=review,specification_blob=store.blob(encoded(spec)))
        if review['accepted'] and not review['issues']:
            return normalize({**scenario,'world_model':spec})
        feedback=review['issues'] or ['Reviewer rejected specification']
    raise ValueError('World compilation rejected: '+str(feedback))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--scenario',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--audit',type=Path,required=True)
    a=p.parse_args();store=Store(a.audit)
    try:
        scenario=compile_world(json.loads(a.scenario.read_bytes()),store)
        durable(a.output,encoded(scenario));store.event('compiled',scenario_sha256=sha(encoded(scenario)))
    finally:seal(store.root)
    print(a.output)


if __name__=='__main__':main()
