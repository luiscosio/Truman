"""Declarative website profiles.

Each simulated website is a package under sandbox/sites/<id>/ with a site.yaml
profile and an optional handlers module. The profile holds every site convention
(hosts, routes, parameters, error responses, content selectors, link rules,
resource keys and version metadata). Shared world code asks the Site object and
never hardcodes a particular website. See SITES.md for the profile reference.
"""
import functools
import hashlib
import importlib
import json
import re
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

import yaml

ROOT = Path(__file__).parent
# Worlds and scenarios created before site profiles existed are Wikipedia worlds.
DEFAULT = 'wikipedia'
PARAM_TYPES = ('int', 'timestamp', 'enum', 'version')
# Engine features a profile configures; scenarios pick modes with site_options.
OPTIONS = ('raw', 'revision_metadata', 'search')
QUERY_TESTS = ('equals', 'present', 'absent', 'prefix')


class ProfileError(ValueError):
    pass


def path(site_id):
    if not re.fullmatch(r'[a-z0-9_]+', site_id):
        raise ProfileError('Invalid site id: ' + repr(site_id))
    found = ROOT / site_id / 'site.yaml'
    if not found.exists():
        raise ProfileError('Unknown site: ' + site_id)
    return found


@functools.cache
def load(site_id=DEFAULT):
    """The repository profile for a site id; profiles are versioned like code."""
    return Site(path(site_id).read_bytes(), site_id)


@functools.cache
def profile(site_id=DEFAULT):
    """Profile data only, for modules that must not import site handlers."""
    return yaml.safe_load(path(site_id).read_bytes())


def for_scenario(scenario):
    return load(scenario.get('site', DEFAULT))


def require(condition, message):
    if not condition:
        raise ProfileError(message)


class Site:
    def __init__(self, raw, site_id):
        self.yaml = raw
        self.sha256 = hashlib.sha256(raw).hexdigest()
        data = yaml.safe_load(raw)
        require(isinstance(data, dict) and data.get('schema_version') == 1, 'Profiles must use schema_version 1')
        require(data.get('id') == site_id, 'Profile id must match its folder: ' + site_id)
        self.data = data
        self.id = site_id
        self.name = data['name']
        self.hosts = data['hosts']
        self.origin = 'https://' + self.hosts[0]
        self.resource = data['resource']
        self.content = data['content']
        self.links = data['links']
        self.versions = data['versions']
        self.options = data.get('options', {})
        self.params = data.get('params', {})
        self.messages = data.get('messages', {})
        self.errors = data['errors']
        self.constants = data.get('constants', {})
        self.headers = data.get('headers', {})
        self.rewrite = data['rewrite']
        self.capture = data.get('capture', {})
        self.prepare = data.get('prepare', {'paths': ['{path}']})
        self.limitations = data.get('limitations', {})
        self.module = importlib.import_module(data['handlers'])
        self.routes = [self._route(route) for route in data['routes']]
        self._validate()

    # Validation keeps profile mistakes out of live requests.
    def _validate(self):
        require(self.hosts and all(re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', h) for h in self.hosts),
                'hosts must be exact lowercase DNS names')
        for key in ('path', 'home'):
            require(isinstance(self.resource.get(key), str), 'resource.' + key + ' is required')
        require('{key}' in self.resource['path'], 'resource.path needs a {key} placeholder')
        require(isinstance(self.content.get('body'), str), 'content.body is required')
        require(isinstance(self.content.get('lead', ''), str), 'content.lead must be an XPath when present')
        require(re.search(r'\{(id|key)\}', self.versions.get('url', '')), 'versions.url needs an {id} or {key} placeholder')
        require(isinstance(self.rewrite.get('scripts', []), list), 'rewrite.scripts must be a list')
        for name, spec in self.params.items():
            require(spec.get('type') in PARAM_TYPES, 'Unknown type for parameter ' + name)
            require(spec['type'] != 'enum' or spec.get('values'), 'Enum parameter needs values: ' + name)
            needed = ['int', 'version'] if spec['type'] == 'version' else [spec['type']]
            require(all(m in self.messages for m in needed), 'No invalid-value message for type ' + spec['type'])
        for code, spec in self.messages.items():
            require(isinstance(spec.get('code'), str) and isinstance(spec.get('info'), str), 'messages.' + code + ' needs code and info')
        for name in ('invalid_request', 'unavailable', 'not_found'):
            require(name in self.errors, 'errors.' + name + ' is required')
        for name, error in self.errors.items():
            require(isinstance(error.get('status'), int) and error.get('mime'), 'errors.' + name + ' needs status and mime')
            require(('json' in error) != ('body' in error), 'errors.' + name + ' needs exactly one of json or body')
        for block in ('blocks', 'attributes', 'skip'):
            require(isinstance(self.rewrite.get(block), list), 'rewrite.' + block + ' must be a list')
        require(set(self.options) == set(OPTIONS), 'options must declare exactly: ' + ', '.join(OPTIONS))
        for name, option in self.options.items():
            require(option.get('default') in option.get('modes', {}), 'options.' + name + '.default must be one of its modes')
        require(self.options['raw']['default'] != 'native', 'The default raw mode must derive text from the accepted DOM')
        for mode, spec in self.options['raw']['modes'].items():
            require(callable(getattr(self.module, spec.get('hook', ''), None)), 'Missing raw hook for mode ' + mode)
            require(isinstance(spec.get('format'), str), 'Missing raw format label for mode ' + mode)

    def _route(self, route):
        from sandbox import demand_routes
        paths = route['path'] if isinstance(route['path'], list) else [route['path']]
        name = route['handler']
        handler = getattr(self.module, name, None) or demand_routes.HANDLERS.get(name)
        require(callable(handler), 'Unknown route handler: ' + name)
        tests = {}
        for param, test in (route.get('query') or {}).items():
            if test is True:
                tests[param] = ('present', None)
            elif test is False:
                tests[param] = ('absent', None)
            elif isinstance(test, dict):
                require(len(test) == 1 and next(iter(test)) in QUERY_TESTS, 'Invalid query test for ' + param)
                tests[param] = next(iter(test.items()))
            else:
                tests[param] = ('equals', test if isinstance(test, list) else [test])
        return {'patterns': [self._pattern(p) for p in paths], 'tests': tests, 'handler': handler, 'name': name,
                'defaults': route.get('defaults', {}), 'options': route.get('options', {})}

    @staticmethod
    def _pattern(path):
        # A {name} placeholder captures the rest of a segment run, including slashes.
        parts = re.split(r'\{(\w+)\}', path)
        regex = ''.join(re.escape(p) if i % 2 == 0 else '(?P<' + p + '>.+)' for i, p in enumerate(parts))
        return re.compile(regex + r'\Z')

    def match(self, path, query):
        """First route whose path and query tests match, with its path variables."""
        for route in self.routes:
            for pattern in route['patterns']:
                found = pattern.match(path)
                if not found:
                    continue
                values = {k: v[0] for k, v in query.items()}
                values = {**route['defaults'], **values}
                if all(self._test(values, name, test) for name, test in route['tests'].items()):
                    return route, found.groupdict()
        return None, {}

    @staticmethod
    def _test(values, name, test):
        kind, expected = test
        if kind == 'present':
            return name in values
        if kind == 'absent':
            return name not in values
        if kind == 'prefix':
            return values.get(name, '').startswith(expected)
        return values.get(name) in expected

    # Resource identity
    def key(self, title):
        """Canonical resource key for a title or path segment."""
        rules = self.resource.get('key', {})
        for old, new in rules.get('replace', {}).items():
            title = title.replace(old, new)
        if rules.get('strip'):
            title = title.strip()
        if rules.get('trim'):
            title = title.strip(rules['trim'])
        if rules.get('capitalize_first'):
            title = title[:1].upper() + title[1:]
        return title

    def encoded(self, key):
        """A resource key as it appears in URLs."""
        encode = self.resource.get('encode', {})
        segment = self.key(key)
        for old, new in encode.get('replace', {}).items():
            segment = segment.replace(old, new)
        return quote(segment, safe=encode.get('safe', ''))

    def path(self, key):
        if self.key(key) == self.resource['home'] and 'home_path' in self.resource:
            return self.resource['home_path']
        return self.resource['path'].replace('{key}', self.encoded(key))

    def url(self, key):
        return self.origin + self.path(key)

    def version_url(self, version, key):
        """Canonical source URL of a page version ({id}: version id, {key}: page path)."""
        return (self.versions['url'].replace('{origin}', self.origin).replace('{id}', str(version))
                .replace('{key}', self.encoded(key)))

    def internal(self, url):
        return url.hostname in (None, *self.hosts)

    def is_resource(self, key):
        """Whether a key can name a page (resource.pattern, when the profile sets one)."""
        return 'pattern' not in self.resource or re.fullmatch(self.resource['pattern'], key) is not None

    def key_from_href(self, href):
        """The resource key an internal link names, or None for any other link."""
        url = urlsplit(href)
        if not self.internal(url):
            return None
        for prefix in self.links['resource_prefixes']:
            if url.path.startswith(prefix):
                key = self.key(unquote(url.path[len(prefix):]))
                return key if self.is_resource(key) else None
        return None

    def link_allowed(self, value):
        """Whether a rewritten link stays inside this site's own navigation."""
        url = urlsplit(value)
        if value.startswith('#'):
            return True
        return url.scheme in ('', 'https') and self.internal(url) and (
            url.path.startswith(tuple(self.links['rewrite_prefixes'])) or self.key_from_href(value) is not None)

    def asset_path(self, key):
        return self.resource['assets'].replace('{key}', key)

    # Representations and options
    def settings(self, scenario):
        """Profile option defaults overlaid by a scenario's site_options."""
        # Scenarios written before site profiles carried these options under 'wikipedia'.
        chosen = scenario.get('site_options', scenario.get('wikipedia', {}) if self.id == 'wikipedia' else {})
        unknown = set(chosen) - set(self.options)
        require(not unknown, 'Unknown site options: ' + ', '.join(sorted(unknown)))
        result = {name: chosen.get(name, spec['default']) for name, spec in self.options.items()}
        for name, mode in result.items():
            require(mode in self.options[name]['modes'], 'Unsupported ' + name + ' mode for ' + self.id + ': ' + str(mode))
        return result

    def raw(self, mode):
        """The hook and stored format label of a raw-text mode."""
        spec = self.options['raw']['modes'][mode]
        return getattr(self.module, spec['hook']), spec['format']

    def render_text(self, tree):
        """Raw text derived from an accepted DOM with the profile's default mode."""
        return self.raw(self.options['raw']['default'])[0](tree, self)

    def world_limitations(self, settings):
        return [*self.limitations.get('always', []), *self.limitations.get('raw_' + settings['raw'], [])]

    def source(self):
        """Factory for the site's source adapter, bound to this profile."""
        return functools.partial(getattr(self.module, self.data['source']), site=self)

    def lead(self, body):
        """The lead elements of a page body; [] when the profile defines no lead."""
        return body.xpath(self.content['lead']) if self.content.get('lead') else []

    def error(self, name, **fields):
        """Render a profile error template; placeholders use {field} and constants."""
        spec = self.errors[name]
        values = {**self.constants, **fields}

        def fill(value):
            if isinstance(value, str):
                return re.sub(r'\{(\w+)\}', lambda m: str(values.get(m[1], m[0])), value)
            if isinstance(value, dict):
                return {fill(k): fill(v) for k, v in value.items()}
            if isinstance(value, list):
                return [fill(v) for v in value]
            return value
        body = (json.dumps(fill(spec['json']), ensure_ascii=False).encode() if 'json' in spec
                else fill(spec['body']).encode())
        return spec['status'], spec['mime'], body, fill(spec.get('headers', {}))
