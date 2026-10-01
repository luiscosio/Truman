# Site profiles

A simulated website is a folder under `sandbox/sites/<id>/`:

| File | Holds |
| --- | --- |
| `site.yaml` | Every site convention: hosts, routes, parameters, error pages, content selectors, link rules, resource keys, version URLs and supported engine options. |
| `handlers.py` | Code for formats YAML cannot express (an API's JSON shape, an export format, a feed), the source adapter that acquires original pages, and representation hooks. |

Shared code (`sandbox/demand*.py`, `sandbox/rewrite_capture.py`) reads the profile through
`sandbox.sites.load(id)` and never names a website. A handlers module can serve several
profiles: sources and hooks receive the profile that uses them. Three profiles exist:

| Profile | Status |
| --- | --- |
| `wikipedia` | English Wikipedia. Used by every recorded experiment. A refactor into this profile reproduced 1,550 recorded responses from five frozen worlds byte for byte (`python -m sandbox.route_golden`). |
| `globalvoices` | Global Voices, a real news site (articles under CC BY 3.0), using the shared news handlers. Captured live and served to an agent alongside Wikipedia in [the ISA experiment](examples/isa-mining-code-20261001/README.md). |
| `news` | A template for news publications on reserved `.example` hosts, with JSON-LD metadata. Covered by offline fixture tests; copy it for a new publication. |

## Choosing a site

A scenario names its site; omitting it means `wikipedia`, which keeps older scenarios and
worlds valid.

```json
{"id": "budget-news", "site": "news", "as_of": "2026-09-18", "facts": ["..."],
 "site_options": {"search": "captured_corpus"}}
```

`site_options` picks modes of the engine features the profile declares under `options`.
Unknown options or modes are rejected. Wikipedia scenarios written earlier carry the same
options under `wikipedia`; they are still read.

Each world records `site: {id, profile_sha256}` in `world.json` and keeps the profile with
its code snapshot (`code-sites__<id>__site.yaml`). Like code, the repository profile is
what runs; the recorded hash shows whether it changed since the world was created.

## Profile reference

```yaml
schema_version: 1
id: news                       # must match the folder
name: Example News             # used in model prompts and generated page titles
handlers: sandbox.sites.news.handlers
source: NewsSource             # class in the handlers module
hosts: [www.news.example]      # first host is the origin
```

**resource**: page identity.
`path` (with `{key}`) is the page URL; `home` is the key served for an empty key and
`home_path` its URL when it differs from `path`; `assets` is where captured images are
served. `pattern` (a regular expression) limits which keys name pages, so paths such as
`/feed/` or `/category/x/` never trigger acquisition. `key` normalizes titles (`replace`,
`strip`, `trim` characters, `capitalize_first`) and `encode` turns a key into a URL segment
(`replace`, `safe`).

**content**: XPath selectors. `body` finds the page body, `lead` (relative to body) the
introduction, `drop` editor banners removed at capture and before rewriting, `extract_drop`
nodes left out of plain-text extracts, `heading` the visible title. `title_suffix` follows
the title in `<title>`.

**links**: `resource_prefixes` are paths that name a page key directly;
`rewrite_prefixes` are further paths a rewritten link may point to (a link to any page key
is always allowed). Links to other hosts are never invented.

**article** (news handlers): where publication and modification dates are found, in
order, as XPaths or `ld+json:<field>`. Publication decides whether an article exists at
the world date. A capture modified after the world date is kept and marked
`modified_after_cutoff`, since only the current version can be fetched.

**versions**: `url` is a version's canonical source URL, with `{origin}`, `{id}` (version
id) and `{key}` (encoded page key).

**options**: the three engine features, each with a `default` and its `modes`:

| Option | Meaning |
| --- | --- |
| `raw` | How raw text is made. A `native` mode rewrites captured source with its hook; other modes derive text from the accepted DOM with theirs. `format` labels the stored representation. The default must derive from the DOM. |
| `revision_metadata` | `blank` hides editor names and comments; `preserve` keeps reviewed ones. |
| `search` | `upstream` asks the source at request time; `captured_corpus` searches accepted pages only. |

**rewrite**: what the rewriter reviews. `blocks` group inline text into one reviewable
unit, `attributes` are reviewed with the text, `skip` is never shown, and `scripts` lists
metadata script types (such as `application/ld+json`) that are kept at capture, reviewed
like text, and must still parse as JSON afterwards.

**capture**: `hosts` the source may fetch from and the `user_agent`.

**prepare**: routes checked for each prepared page (`{path}`: page path, `{title}`:
percent-encoded display title) and `skip_keys`, a pattern for linked keys not to follow.

**params**: typed query parameters: `int` (`default`, `min`, `max`; `max` also accepts the
word `max`), `timestamp`, `enum` (`values`) and `version` (a positive id). A route with
`options: {lenient: true}` falls back to defaults instead of rejecting bad values, as page
views usually do.

**messages**: the error code and text for each invalid parameter type (`int`, `timestamp`,
`enum`, `version`) plus any codes handlers raise. `{name}` and `{value}` are filled in.

**errors**: three required responses, each with `status`, `mime`, optional `headers` and
exactly one of `body` (text) or `json`. `{field}` placeholders use the error's fields and
`constants`.

| Error | Used for |
| --- | --- |
| `invalid_request` | A request the real site rejects (`{code}`, `{info}`). |
| `not_found` | A page that does not exist in the world. |
| `unavailable` | Every coverage miss and failed generation. Keep one realistic outage page for all of them; the exact reason is recorded internally, never shown. |

**headers**: optional response headers added to every response.

**routes**: first match wins.

```yaml
- {path: '/articles/{key}', handler: page_html}
- {path: /w/api.php, defaults: {action: query}, query: {action: [query, parse]}, handler: api_pages}
- {path: /wiki/Special:{name}, handler: unsupported, options: {reason: Unsupported special page}}
```

`{name}` captures the rest of the path, slashes included; quote paths that contain one.
`query` tests a parameter against a value or list, `true`/`false` (present or absent) or
`{prefix: text}`; `defaults` apply first. `options` reach the handler: `key` (where a page
key comes from, in order: `path.<var>`, `query.<param>`, else `home`), `version` (a query
parameter naming a version), `lenient`, `reason` (for `unsupported`).

Shared handlers: `page_html`, `page_raw`, `page_other` (resolves the page, then reports the
action unsupported), `asset`, `home` (redirect to the home page), `canonical_redirect`
(301 to a page's canonical path) and `unsupported`. Any other name must exist in the
site's handlers module.

## Writing handlers and sources

A handler takes a `Context` (`sandbox/demand_routes.py`) and returns
`(status, mime, body, headers, coverage, evidence)`, normally through `ctx.out(...)`.
`ctx.param`, `ctx.value` (typed by the profile), `ctx.resource()`, `ctx.extract()`,
`ctx.html()` and `ctx.invalid(code)` cover most needs. Raise `CoverageMiss` for anything
the simulation does not serve. Read only accepted world pages: a handler must never
return an unmodified upstream original for a rewritten page.

A source is constructed as `Source(attempt_root, cutoff, site=profile)` and provides:

| Method | Returns |
| --- | --- |
| `acquire(key, version=None)` | `{title, page_id, record, source, document, ...}` or `{missing: True, title}`. `record` must carry `revid` (an integer version id) and `timestamp` (ISO UTC); these are the engine's record fields for every site. Never return content newer than the cutoff. |
| `history(key, limit)`, `history_range(key, params)` | Version metadata, newest first; `[]` when the site has no public history. |
| `version_title(id)` | The page key of a version, or `None`. |
| `search(query, limit)` | Upstream hits, only if the profile offers `upstream` search. |

Fetch through `sandbox.rewrite_capture.Capture(root, site)`, which records every
response, refuses hosts outside `capture.hosts` and raises `FetchError` with the HTTP
status.

Representation hooks take `(tree, site)` for DOM-derived text.

## Several sites in one world

Compile one world specification, then create a world per site from it (same
`world_model`, date and condition, a different `site`). Linked worlds review each new
page against the committed pages of every linked world, each shown through its own
profile, so a news article cannot contradict an encyclopedia page that is already
accepted. Linking is recorded in every attempt's `context.json`.

```bash
python -m sandbox.demand_prepare --world <news world> --link <wikipedia world> --pages front <article key> --depth 0 --report <report.json>
```

## Running sites in the managed network

1. Write a site policy listing every simulated host with `"transport": "world"` (see
   `examples/isa-mining-code-20261001/sites.json`). Prepare a network profile from it:
   DNS answers are pinned for every listed host and the server certificate names every
   world host.

   ```bash
   python -m sandbox.transparent --managed --profile <new profile> --site-policy <sites.json>
   ```

2. Pass one `--world` per site. The runner links them, serves them through one bridge
   (requests are routed by `Host`; a host no world serves gets 403), freezes each into
   `world-snapshots/<site>`, and refuses to start if the policy does not route a world's
   hosts. `sandbox.demand_pair` takes `--reference` and `--synthetic` once per site.

## Checking a change

```bash
uv run python -m unittest sandbox.test_sites sandbox.test_demand
```

To prove a refactor keeps a site's responses, record frozen worlds first and compare after:

```bash
uv run python -m sandbox.route_golden --world <frozen world> --runs <runs folder> --output golden.json
```

```bash
uv run python -m sandbox.route_golden --world <frozen world> --compare golden.json
```

The legacy bundle-based Wikipedia path (`truman/`, `sandbox/wikipedia.py`, `rewrite*.py`,
`synthetic.py`, `transparent*.py`) predates profiles and remains Wikipedia-only.
