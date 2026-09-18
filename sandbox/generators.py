"""Operator-only generator selection and scenario validation."""
import json
from pathlib import Path

ALIASES = {"a": "a", "generate": "a", "b": "b", "rewrite": "b"}


def generation_settings(scenario, generator):
    settings = scenario.get('generators',{}).get(generator,scenario.get('generation',{}))
    if generator == 'b':
        if settings.get('provider', 'anthropic') != 'anthropic' or not settings.get('model', 'claude-sonnet-5').startswith('claude-sonnet-'):
            raise ValueError('Generator B requires Anthropic Claude Sonnet')
        if set(settings) & {'seed', 'temperature'}:
            raise ValueError('Sonnet rewrite settings use effort; seed and temperature are unsupported')
        if settings.get('effort', 'medium') not in ('low', 'medium', 'high', 'max'):
            raise ValueError('Invalid Sonnet effort')
        if type(settings.get('max_tokens', 8192)) is not int or not 256 <= settings.get('max_tokens', 8192) <= 32768:
            raise ValueError('Sonnet max_tokens must be 256-32768')
    return settings


def select(value=None, scenario=None, snapshot=None, condition=None):
    configured = (scenario or {}).get("generator")
    chosen = value or configured
    if chosen is not None and chosen not in ALIASES:
        raise ValueError("Unknown generator; use a/generate or b/rewrite")
    chosen = ALIASES.get(chosen)
    if snapshot is not None:
        recorded = snapshot.get("generator", {}).get("id", "a" if snapshot["condition"] == "synthetic" else None)
        if chosen and chosen != recorded:
            raise ValueError("Generator conflicts with frozen snapshot")
        return recorded
    if chosen and condition not in (None, "synthetic"):
        raise ValueError("Generator selection requires the synthetic condition")
    return chosen or ("a" if condition == "synthetic" else None)


def scenario_file(path):
    value = json.loads(Path(path).read_bytes())
    if value.get("schema_version") != 1:
        raise ValueError("Unsupported scenario version")
    for key in ("id", "question", "as_of"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ValueError("Missing scenario " + key)
    if not isinstance(value.get("facts"), list) or not value["facts"] or not all(isinstance(f, str) and f.strip() for f in value["facts"]):
        raise ValueError("Scenario requires explicit facts; a question alone does not define an altered world")
    if not isinstance(value.get("seed_pages"), list) or not value["seed_pages"]:
        raise ValueError("Scenario requires seed_pages")
    import datetime as dt
    dt.date.fromisoformat(value['as_of'])
    for key in ('seed_pages','support_pages'):
        if not isinstance(value.get(key,[]),list) or not all(isinstance(x,str) and x.strip() for x in value.get(key,[])):
            raise ValueError('Invalid '+key)
    for settings in [value.get('generation',{}), *value.get('generators',{}).values()]:
        if set(settings)-{'model','seed','temperature','provider','effort','max_tokens'}:
            raise ValueError('Unsupported generation setting')
        if not 0 <= settings.get('temperature',0.2) <= 2:
            raise ValueError('Invalid temperature')
    attempts=value.get('preparation',{}).get('max_attempts_per_page',2)
    if type(attempts) is not int or not 1<=attempts<=3:
        raise ValueError('Generation attempts must be 1-3')
    return value
