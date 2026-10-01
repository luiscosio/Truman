"""Site-neutral request dispatch for growing and frozen worlds; no network access here.

The site profile decides which handler serves a request, how parameters parse and
how errors look. Handlers here are the ones every site can share; site-specific
handlers live in sandbox/sites/<id>/handlers.py.
"""
import datetime as dt
import json
import re
from urllib.parse import parse_qs, unquote, urlsplit
from lxml import html


class InvalidRequest(ValueError):
    """A request the real site itself rejects, answered with its own error code."""
    def __init__(self, code, info):
        super().__init__(info)
        self.code = code


class Context:
    """One request: the world, its site profile, the matched route and parameters."""

    def __init__(self, world, target, route, variables, query):
        self.world = world
        self.site = world.site
        self.target = target
        self.route = route
        self.options = route['options']
        self.vars = variables
        self.query = query

    def param(self, name, default=''):
        return self.query.get(name, [default])[0]

    def has(self, name):
        return name in self.query

    def invalid(self, message, **fields):
        spec = self.site.messages[message]
        return InvalidRequest(spec['code'], spec['info'].format(**fields))

    def value(self, name):
        """A parameter parsed by its profile type; absent values use the profile default."""
        spec = self.site.params[name]
        default = spec.get('default')
        if name not in self.query:
            return default
        raw = self.query[name][0]
        if raw == '' and default is None:
            return None
        return self.parse(name, raw)

    def parse(self, name, raw):
        spec = self.site.params[name]
        kind = spec['type']
        if kind == 'int':
            if raw == 'max' and 'max' in spec:
                return spec['max']
            if self.options.get('lenient') and not re.fullmatch(r'[0-9]+', raw):
                # Page views ignore unparsable numbers instead of rejecting them.
                return spec['default']
            if not re.fullmatch(r'[+-]?[0-9]+', raw):
                raise self.invalid('int', name=name, value=raw)
            number = int(raw)
            return min(max(number, spec.get('min', number)), spec.get('max', number))
        if kind == 'version':
            if not re.fullmatch(r'[+-]?[0-9]+', raw):
                raise self.invalid('int', name=name, value=raw)
            if int(raw) < 1:
                raise self.invalid('version', name=name, value=int(raw))
            return int(raw)
        if kind == 'enum':
            if raw not in spec['values']:
                raise self.invalid('enum', name=name, value=raw)
            return raw
        try:
            moment = (dt.datetime.strptime(raw, '%Y%m%d%H%M%S') if re.fullmatch(r'[0-9]{14}', raw)
                      else dt.datetime.fromisoformat(raw.replace('Z', '+00:00')))
            if moment.tzinfo:
                moment = moment.astimezone(dt.timezone.utc)
            return moment.strftime('%Y-%m-%dT%H:%M:%SZ')
        except ValueError:
            raise self.invalid('timestamp', name=name, value=raw)

    def out(self, value, status=200, mime='application/json; charset=utf-8', coverage='derived', proof=None, headers=None):
        body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
        return status, mime, body, headers or {}, coverage, proof

    def error(self, name, coverage, proof=None, **fields):
        status, mime, body, headers = self.site.error(name, **fields)
        return status, mime, body, headers, coverage, proof

    def body(self, article):
        document = html.fromstring(self.world.bytes(article['html_blob']), parser=html.HTMLParser(encoding='utf-8'))
        return document.xpath(self.site.content['body'])[0]

    def extract(self, article, intro=False):
        """Plain prose of an accepted page, optionally only its lead."""
        root = self.body(article)
        for node in list(root.xpath(self.site.content.get('extract_drop', './/style|.//script'))):
            if node.getparent() is not None:
                node.drop_tree()
        if intro:
            lead = root.xpath(self.site.content['lead'])
            paragraphs = lead[0].xpath('.//p') if lead else root.xpath('.//p')[:3]
        else:
            paragraphs = root.xpath('.//p')
        return '\n\n'.join(p.text_content().strip() for p in paragraphs if p.text_content().strip())

    def resource(self):
        """The page a page route names: a valid version parameter, else its key or the home page."""
        version = self.param(self.options['version']) if self.options.get('version') else ''
        if re.fullmatch(r'[0-9]+', version) and int(version):
            return self.world.revision(int(version))
        names = [self.vars.get(name) if kind == 'path' else self.param(name)
                 for kind, _, name in (source.partition('.') for source in self.options.get('key', ['path.key']))]
        return self.world.ensure(next(filter(None, names), self.site.resource['home']))

    def html(self, article):
        if article.get('missing'):
            return self.error('not_found', 'world_missing')
        return self.out(self.world.bytes(article['html_blob']), mime='text/html; charset=utf-8', proof=article['page'])


def unsupported(ctx):
    from sandbox.demand import CoverageMiss
    raise CoverageMiss(ctx.options.get('reason', 'Unsupported route'))


def home(ctx):
    return ctx.out(b'', 302, 'text/plain', headers={'Location': ctx.site.url(ctx.site.resource['home'])})


def asset(ctx):
    from sandbox.demand import CoverageMiss
    stored = ctx.world.read('cache', 'asset:' + ctx.vars['key'].rsplit('/', 1)[-1])
    if not stored:
        raise CoverageMiss('Resource outside captured world')
    return ctx.out(ctx.world.bytes(stored['blob']), mime=stored['mime'])


def page_html(ctx):
    return ctx.html(ctx.resource())


def page_raw(ctx):
    article = ctx.resource()
    if article.get('missing'):
        return ctx.html(article)
    return ctx.out(ctx.world.bytes(article['text_blob']), mime='text/plain; charset=utf-8', proof=article['page'])


def page_other(ctx):
    """A page action the site has but the simulation does not implement."""
    article = ctx.resource()
    if article.get('missing'):
        return ctx.html(article)
    return unsupported(ctx)


HANDLERS = {'unsupported': unsupported, 'home': home, 'asset': asset,
            'page_html': page_html, 'page_raw': page_raw, 'page_other': page_other}


def respond(world, target):
    status, mime, body, headers, coverage, proof = dispatch(world, target)
    return status, mime, body, {**world.site.headers, **headers}, coverage, proof


def dispatch(world, target):
    from sandbox.demand import CoverageMiss, NeedsGeneration
    site = world.site
    parts = urlsplit(target)
    query = parse_qs(parts.query, keep_blank_values=True)
    try:
        if len(target) > 12000 or parts.scheme or parts.netloc:
            raise CoverageMiss('Invalid request target')
        route, variables = site.match(unquote(parts.path), query)
        if route is None:
            raise CoverageMiss('Unsupported ' + site.name + ' route')
        return route['handler'](Context(world, target, route, variables, query))
    except NeedsGeneration:
        raise
    except InvalidRequest as exc:
        return (*site.error('invalid_request', code=exc.code, info=str(exc)), 'invalid_request', {'reason': str(exc)})
    except CoverageMiss as exc:
        return (*site.error('unavailable'), 'outside_snapshot', {'reason': str(exc)})
    except Exception as exc:
        # Never return an unmodified original on failed generation/validation.
        return (*site.error('unavailable'), 'generation_failed', {'reason': type(exc).__name__ + ': ' + str(exc)})
