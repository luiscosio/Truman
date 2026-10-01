# On-demand Wikipedia worlds

A world has one immutable scenario and source cutoff, and a persistent set of accepted pages. It can start with validated seeds. An intercepted request for an unknown page captures the original Wikipedia revision at the cutoff, asks the configured Claude model to rewrite the complete article, validates it, and saves the result. Future requests reuse the saved bytes. An unrelated article can pass through unchanged after review.

The agent runs in the existing managed Docker network. The Wikipedia origin is a small container bridge. A host worker reads its filesystem queue and performs acquisition and generation. The agent cannot mount that queue, reach the origin directly, or access the generator's API credentials. Only the host reads the rewrite key. Existing altered/unaltered/blacklisted site policy remains in force.

## Create and run

Install the repository's Python dependencies and build the network images as described in `MANAGED_NETWORK.md`. Generator A remains available through the existing synthetic runner; `--world` selects the persistent Claude rewrite generator B.

```powershell
python -m sandbox.demand create --world data/live-worlds/monarch-v1 --scenario scenarios/monarch-on-demand.json

# Set ANTHROPIC_API_KEY in the host environment, or point to an existing key file.
# The reader selects only ANTHROPIC_API_KEY; it never uses an admin key.
$env:TRUMAN_REWRITE_KEY_FILE='D:/path/to/existing/credentials-file'

python -m sandbox.run --world data/live-worlds/monarch-v1 --network-mode managed --network-profile data/managed-profile-v1 --model 'claude-opus-5[1m]' --effort high --seconds 900 --max-turns 12 --label 'On-demand Sonnet / high'
```

Agent subscription authentication and generator API authentication are separate. Use the existing Claude Code login for the agent. No generator secret is placed in a Compose environment, prompt, trace, or world archive.

Explicit nonexistent topics and their aliases come from the world specification. For other world-v2 topics, a separate availability decision receives the world rules and an adapter-provided source summary before rewriting. A topic solely about a ruled-out event becomes a cached missing page; an existing subject with false claims is rewritten. An uncertain decision fails closed. No target questions or answer keys enter this decision.

The scenario fixes the date, source cutoff, world rules, initial shared facts, display-title aliases, Sonnet model/settings, and generation budgets. Change those by creating a new world. Do not edit a world in place. The example allows 40 accepted versions, 100 acquisition attempts and 20 model chunks per article. Up to four section calls run concurrently, with facts merged in DOM order. Validation permits one local malformed-patch retry and two consistency-repair passes that retain previous edits. Structural/absence failures allow one full-article retry; exhausted consistency repair fails closed. These are request/token bounds, not a dollar spending cap.

For a host-side diagnostic request:

Large model chunks are bounded to 400 DOM entries and 24 KB before prompt overhead. A response truncated at the output-token limit is retained and split into smaller requests, to at most two subdivision levels. Only complete, validated edits can reach publication.

```powershell
python -m sandbox.demand request --world data/live-worlds/monarch-v1 --path /wiki/Monarchy_of_the_United_Kingdom
```

This prints response metadata and a body hash; the exact body is in the world's content-addressed storage. A failed HTTP request exits nonzero. Articles are generated only in response to requests, including diagnostic requests and search results that need article snippets. There is no automatic prewarming during network setup.

## Freeze and compare agents

Each finished run records a frozen world copy in its run directory. A separate export is also available:

```powershell
python -m sandbox.demand freeze --world data/live-worlds/monarch-v1 --output data/worlds/monarch-frozen-v1
python -m sandbox.run --world data/worlds/monarch-frozen-v1 --network-mode managed --network-profile data/managed-profile-v1 --model 'claude-opus-5[1m]' --effort high --seconds 180 --label 'Frozen replay / high'
```

A sealed world opens its database read-only. Replay never calls Wikipedia or Sonnet. It serves saved pages and can derive supported API representations from them; a request requiring an uncaptured page, revision or upstream query is recorded as a coverage miss. Freeze the same world once and use that export for matched agent comparisons. Running two agents against a growing world can expose different coverage and acquisition times.

The report retains next/back navigation, role filters and single-trace HTML export. For local visual inspection of a frozen page:

```powershell
python -m sandbox.demand serve --world data/worlds/monarch-frozen-v1 --port 8767
```

Open `http://localhost:8767/wiki/Monarchy_of_the_United_Kingdom`. This preview is a host-only read-only listener, separate from agent networking.

## What is recorded

- Original source text, rendered HTML, captured assets, source revision metadata and acquisition responses.
- Every Sonnet request, raw response, model identity, usage, duration, validation rejection and accepted edit.
- Committed shared facts, title aliases, accepted pages and intentional missing pages.
- Exact served response bodies and hashes, filesystem queue requests/responses, intercepted HTTP fields, agent messages and tool results.
- Code snapshots and integrity seals for attempts, frozen worlds and complete runs.

Rejected attempts remain available but do not change published pages or shared facts. Repeated requests converge on the same accepted version through a SQLite transaction. Internal coverage/evidence headers are removed at the gateway. Operator provenance stays in audit files rather than appearing as labels in the page.

## Supported surfaces and limits

HTML pages, REST summaries, extracts, raw-source projections, query/parse APIs, a bounded search, revision lookup/history and revision comparisons share the accepted article representation. History is acquired only when requested. Original revision IDs, order and timestamps are retained; each requested version is rewritten under the scenario. Intentional absence and actual upstream missing pages produce missing-page responses. Unsupported operations and generation failures are recorded separately and never fall back to unmodified live content.

This is still a fidelity experiment:

- First requests can take minutes and exceed an agent tool's timeout. Retry can reuse an in-progress/accepted article, but the delay is observable.
- Sonnet reviews all visible article text and the edit log; this does not prove global consistency. Images can be removed, not invented. Page layout and media may still reveal seams.
- Raw wikitext is projected from the accepted HTML, not a reconstruction of original templates. Template expansion uses capture-time templates even for old revisions.
- Original edit comments are retained. They can mention events or titles that no longer fit the scenario; full revision-history fidelity remains incomplete.
- Search ranking comes from acquisition-time Wikipedia and is cached; it is not a historical search engine. Search results may acquire several pages.
- The adapter supports a bounded subset of Wikipedia read APIs. Revision history currently caps each request at five versions; arbitrary revision filters and special pages are not implemented.
- Frozen replay fixes the content and coverage. It does not make agent outputs or fresh model generations deterministic.

Wikipedia provenance and license attribution remain in the source records. This system serves altered pages only inside the experiment's sandbox.

## General world model and rewrite pipeline (world-v2)

For new experiments, compile natural-language scenario rules into a shared world
specification before creating the world. This is a paid model operation. Existing
worlds and scenarios without a compiled specification retain the legacy pipeline
for reproducibility; compilation opts into `world-v2`.

```sh
python -m sandbox.demand_world --scenario scenarios/monarch-on-demand.json \
  --output data/monarch-world-v2.json --audit runs/monarch-compilation-v2
python -m sandbox.demand create --world data/live-worlds/monarch-v2 \
  --scenario data/monarch-world-v2.json
```

The schema supports entities, stable identities, source/world page titles, aliases,
existence, dated subject/predicate/value facts, given versus derived facts and their
basis, preservation rules, invariants and unknowns. Date intervals are inclusive at
the start and exclusive at the end. Empty bounds are unbounded. The compiler and a
separate review check the specification; deterministic validation rejects overlapping
conflicting values and ambiguous aliases. Semantic equivalence of differently named
predicates is still a model judgement, not a theorem prover.

The compiled specification is fixed for the experiment. Pages cannot append facts.
Before publication, each candidate also receives pairwise semantic review against every committed page. Contradictions block publication and trigger a repair attempt; existing pages remain unchanged. This is deliberately conservative and adds quadratic review cost as worlds grow.

All pages record their world hash and conservative dependencies on the complete fact
set. To change the world, create a new world version and regenerate pages: in-place
fact edits or partial invalidation are intentionally unsupported. Renamed titles and
aliases resolve before the first page is generated. Explicitly absent topics return
normal missing-page responses even when they were not requested before freezing.

The new pipeline plans from the complete document. Large articles use a concise conceptual plan and inspect every block during patching, avoiding large lists of model-generated node IDs. It patches coherent paragraphs,
table rows and captions, then reviews the original and final document independently.
Review includes unchanged content, page titles, links, tooltips, alt text and metadata.
Repairs target the blocks identified by review. A separate deterministic check rejects
links/tooltips retaining a replaced canonical entity title. HTML, extracts and source
projections derive from the accepted DOM. Original edit comments and usernames stay
in the source audit and are omitted from world-v2 served revision metadata because
they were not authored for the rewritten page.

`generators.b` sets the default model/effort. Optional `models.planner`, `models.writer`
and `models.reviewer` override those settings independently. Sonnet, Opus and Fable
model IDs are accepted; the returned model must exactly match the requested ID. Keep
model IDs explicit for repeatability. For example:

```json
{"generators":{"b":{"provider":"anthropic","model":"claude-sonnet-5","effort":"high","max_tokens":32768}},
 "models":{"reviewer":{"model":"claude-opus-5","effort":"high"}}}
```

Complete-document planning is bounded to 1.5 MB of compact structured node data. Semantic
rewrite batches are bounded to 48 KB, with at most three patch/review passes. These
are request-size bounds, not a dollar spending cap. Model/schema/network failures
remain recorded and never publish a partial page. Images are assessed through their
captions/attributes, not pixel-level vision; misleading pictures can still escape
review. External citations, original revision dates, capture-time templates, unsupported
Wikipedia APIs and uncaptured pages remain fidelity limitations. A successful review
is not proof of global consistency or undetectability.

The final-content review sees the complete final page in normal sentence order,
with attributes attached to their semantic blocks. A separate preservation review
receives every changed or removed original field and the corresponding final blocks;
unchanged fields need not be duplicated. Cross-page review retains every textual
and attribute field, grouped by semantic block, but omits patch-address IDs and
interns repeated long fields without dropping their positions.
Large cross-page comparisons split between blocks into bounded pairs, covering
every cross-document block combination. Up to four pairs run concurrently; this
avoids oversized prompts but can increase model calls on large biographies.

Independent batches run concurrently (default four; set `on_demand.model_concurrency`
to a value from one to four). Each reads the same document state and receives only
relevant review feedback, plus normal reading-order text for its blocks. Validated
edits are applied in document order. If a patch exhausts its output budget, the
batch can split between semantic blocks, to at most two split levels. An indivisible
block or exhausted split budget fails the page; incomplete output is never applied.
Current-page reviews use the scenario date, including cross-page comparisons;
explicit historical reads use the requested revision date.

### Optional bounded exploration

On-demand generation remains available without a seed list. Before a frozen evaluation,
optionally explore links automatically and check HTML, REST summary, query, parse and
raw response forms. The declared depth/page budget makes incomplete coverage visible:

```sh
python -m sandbox.demand_prepare --world data/live-worlds/monarch-v2 \
  --pages 'Monarchy of the United Kingdom' --depth 1 --max-pages 12 \
  --report reports/preparation-v2.json
```

Add `--freeze data/worlds/monarch-v2` to freeze only when every discovered page within
the requested depth has been handled and its checked routes work. If the budget leaves
unvisited pages or any generation fails, the report is incomplete and this command
refuses to freeze. This is scoped coverage, not a guarantee about arbitrary navigation.

### Repeated model comparison

```sh
python -m sandbox.demand_benchmark --output runs/world-model-comparison \
  --repeats 2 --workers 4
```

The harness compiles one shared specification per scenario, then compares the legacy
Sonnet-medium pipeline with world-v2 Sonnet-medium, Sonnet-high and Opus-high. Three
controlled scenarios cover leadership, event cancellation and technology timing/name
changes. Each has two linked pages; the second repeat reverses their request order.
A separate, blind Opus evaluator sees source/candidate/world content without the writer
identity, alongside explicit preservation and contradiction checks. It records failures,
repairs, token usage, elapsed time and estimated costs, preserving all requests and responses.
Account authentication or insufficient-credit errors stop further model requests in the process. Blocked/unrun pages are reported separately from evaluated pages; incomplete comparisons exit nonzero. `--compiled-from runs/earlier-comparison` reuses already-reviewed specifications in a fresh run directory, preserving earlier evidence.

The fixtures measure rewriting consistency, not realistic Wikipedia coverage, whole-web
fidelity, or target-agent awareness. An Opus judge may favor related models; human spot
checks and larger captured-page tests are required before drawing general conclusions.

### Captured-page regression

Run the original documents from an existing sealed world through the new pipeline
without changing that world or fetching replacement source content:

```sh
python -m sandbox.demand_capture_test --source-world runs/previous/world-snapshot \
  --scenario scenarios/monarch-on-demand.json --output runs/captured-page-comparison
```

This compiles one shared specification (or reuses `world_model` when the scenario is already compiled), compares Sonnet-high and Opus-high, checks
five response forms, exports new HTML and frozen worlds, and verifies the original
evidence seal again. It tests only captured pages, not their uncaptured neighbors.
Large documents use a compact node encoding preserving every field; no article
content is silently truncated to fit a context window.

See [WORLD_MODEL_RESULTS.md](../results/WORLD_MODEL_RESULTS.md) for the measured results and
remaining limitations. On this Mac, run commands from the external runtime checkout
under `~/.local/share/truman/mac`; keep environments, audits and generated worlds
there, outside Dropbox.

The captured-page test defaults to `--max-tokens 32768` to leave room for reasoning and structured output on long articles. Smaller fixture comparisons keep 16384. The provider client allows up to 600 seconds for requests above 16384 output tokens and 240 for smaller requests, but a growing world now applies its shorter shared generation deadline across acquisition, model calls, retries and validation. A truncated response is recorded as a failure, never accepted as a partial plan.

New `/wiki/` link targets must already occur in the captured document or be declared world page identities with a source title. Removing a link converts it to plain text; absent attributes are omitted from review inputs. Semantic entities without their own article do not create page routes or empty-title rewrite rules.

### Seeded worlds with live rewriting

Fork a sealed world into a new growing world to keep accepted seed pages and allow
generation when the agent requests something new. The fork preserves seed bytes,
source audits and the parent seal. It only permits operational changes (model roles,
generation budgets and labels); changing world facts or dates requires regeneration.

```sh
python -m sandbox.demand fork --from-world data/worlds/reviewed-seeds \
  --world data/live-worlds/seeded-live --scenario data/compiled-fast-world.json
python -m sandbox.demand_prepare --world data/live-worlds/seeded-live \
  --from-run runs/previous-agent-run --report reports/request-coverage.json
python -m sandbox.run --world data/live-worlds/seeded-live --network-mode managed \
  --network-profile data/managed-profile-mac-v1 --model 'claude-opus-5[1m]' \
  --effort high --seconds 600 --max-turns 20
```

`--from-run` verifies the prior recording and prepares its exact request paths,
including aliases, API forms and history queries. Multiple paths may refer to one
article. Metadata-only history queries acquire revision metadata without rewriting
historical article bodies; later requests for those bodies still need generation.

For a fast writer, set the following role overrides in a copy of the compiled
scenario while retaining the fixed world specification:

```json
{"models":{
  "planner":{"model":"claude-sonnet-5","effort":"low","max_tokens":8192},
  "writer":{"model":"claude-haiku-4-5-20251001","max_tokens":8192},
  "reviewer":{"model":"claude-sonnet-5","effort":"high","max_tokens":32768}
}}
```

Haiku uses structured output without adaptive thinking or effort (which it does not
support). Invalid Haiku patches and review-requested repairs escalate to the
configured reviewer model. Seed pages retain their original recorded model; only
new generation uses these settings. Full-article planning and review remain on
Sonnet because Haiku's 200K context is too small for some captured biographies.
Unsupported proposed link destinations are removed rather than invented; the final
content and preservation reviews must still accept the resulting page. Low-effort
review was unreliable in the preparation trial, so this example keeps high effort
for review and repairs while using Haiku for first-pass block edits.
See [Haiku specifications](https://platform.claude.com/docs/en/models/haiku-4-5/overview).

The editor can remove complete semantic units (paragraphs, list items, table rows,
headings and figures), so nonexistent events need not leave misleading empty rows.
Removals are constrained to complete units contained in the current batch and are
included in the audit. Removed descendants are excluded from later reviews.
Preservation checks use bounded before/after blocks with normal sentence context;
every changed field is checked. Cross-page comparisons run with bounded concurrency
and still must all pass before publication. Proposed replacement images are removed,
never synthesized or assigned invented filenames.

Fast block calls do not guarantee fast first-page responses: acquisition, all block
edits, review and any repairs must finish before publication. Accepted pages are
cached. A live run can acquire different coverage on each repetition; freeze its
finished world before making matched agent comparisons.


### Reliability safeguards added 19 September 2026

- Planning describes conceptual changes without selecting edit IDs. Every block is
  examined on the first pass, avoiding skipped paragraphs from mistaken plan IDs.
- The plan quotes complete independent source paragraphs to preserve. Their text
  is excluded from editing and checked deterministically before publication; link
  attributes can still be updated. Mixed paragraphs receive semantic preservation
  review. These are source-derived constraints, not
  answers supplied by the experiment operator.
- Proposed whole-block deletions receive review before mutation. Rejected deletions
  become forbidden in later passes. Detached blocks can be restored, and repair
  calls receive original blocks as well as the current candidate. Empty original
  leads, blanked paragraphs and loss of more than half of substantial original prose
  block publication. These conservative checks can reject legitimate large changes;
  they are not a semantic correctness guarantee.
- All reviewers distinguish excluded-event consequences from unrelated history.
  Missing details in the specification do not invalidate existing source facts.
  Compiler unknowns remain in the audit, outside rewriting constraints. Reviewers
  receive exact source-text provenance and original text for changed blocks.
  Entity IDs and declared names are equivalent; other differing claim values get a
  semantic comparison rather than treating every string difference as a contradiction.
- The bridge polls committed pages through a separate read connection while one
  cold generation runs. Cached HTML and derived API responses, known missing pages
  and unsupported routes do not wait for the generator's transaction. Cold writes
  remain serialized to preserve consistency across processes.
- `on_demand.generation_seconds` and `on_demand.request_seconds` default to 90.
  The former is one shared acquisition/generation budget, including model retries;
  the latter bounds the bridge response wait. A request can receive a retryable 503
  while generation finishes under its own budget. Every queued request gets a
  terminal record at timeout or shutdown; undelivered failures affect run status.
  Offline preparation may explicitly allow a longer generation budget.
- Transient provider responses (429, 500, 502, 503, 504 and 529) receive at most one
  retry within that deadline; both responses remain in the audit. Account/billing
  errors still trip the existing circuit breaker. Unsupported or excessively long
  Retry-After delays are not automatically retried.
- Unvalidated diagnostic seeds cannot be forked into a new world or marked ready by
  preparation. Original sealed runs stay readable as evidence; they are not repaired
  in place. Reusing a source capture also strips original revision-editor banners to
  agree with the public metadata API.

This remains a Wikipedia adapter. Controlled multi-scenario checks do not establish
cross-site support or reliable full-Wikipedia generation. Failed preparations are
retained and must not be counted as successful agent or content evaluations.

### Custom target questions

`--task-file` accepts a JSON object with `id`, `prompt` and `required_urls` instead
of the built-in `--task` names. These are target-agent inputs only; they never enter
world compilation or rewriting. The prompt and URLs are recorded with the run and
its experiment hash. Site access is still controlled by the managed profile.
See [the counterfactual CEO fixture](../../experiments/musk-openai-20260919/README.md).

### Native Wikipedia source and revision metadata

Set `wikipedia.raw` to `"native"` and `wikipedia.revision_metadata` to
`"preserve"` in the scenario before creating a world. Reference worlds retain
captured native source. Synthetic worlds edit native paragraph blocks against
the fixed world and accepted HTML, then require a separate semantic review.
Repairs retain earlier edits; invalid anchors, overlaps, HTML substituted for
source, and newly undefined named citations fail before publication. Writer and
reviewer settings are configurable through `models.native_writer` and
`models.native_reviewer`. These calls share the generation deadline and audit.

Raw, parse-wikitext, revision-content API and export routes use the same accepted
native text. Author names and timestamps remain source provenance. Original
comments remain unless a world conflict requires an audited edit. Prepared
revision metadata takes precedence over source history records. Template
expansion remains capture-time HTML, not a running MediaWiki installation.

Existing frozen worlds are immutable and retain their old representations. Build
a new prepared world to upgrade them. The Musk fixture's `prepare_native_pair.py`
records exact native edits, preserves historical source differences, restores
metadata and adds the previously missing sources. Its editorial transfer rules
are fixture-specific; the shared native rewriting mechanism is not.

This does not turn a frozen corpus into the entire internet. New titles require
growing mode and available acquisition/generation budgets. When reusing seeds,
`max_versions` must exceed the already prepared revision count; otherwise the
first new page will exhaust the budget. Cold generation, cached latency and
semantic quality remain separate measurements.
