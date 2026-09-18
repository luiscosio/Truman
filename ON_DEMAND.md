# On-demand Wikipedia worlds

A world has one immutable scenario and source cutoff, and a persistent set of accepted pages. There is no page seed list. An intercepted request for an unknown page captures the original Wikipedia revision at the cutoff, asks Claude Sonnet to rewrite the complete article, validates it, and saves the result. Future requests reuse the saved bytes. An unrelated article can pass through unchanged after review.

The agent runs in the existing managed Docker network. The Wikipedia origin is a small container bridge. A host worker reads its filesystem queue and performs acquisition and generation. The agent cannot mount that queue, reach the origin directly, or access the generator's API credentials. Only the host reads the rewrite key. Existing altered/unaltered/blacklisted site policy remains in force.

## Create and run

Install the repository's Python dependencies and build the network images as described in `MANAGED_NETWORK.md`. Generator A remains available through the existing synthetic runner; `--world` selects the persistent Sonnet rewrite generator B.

```powershell
python -m sandbox.demand create --world data/live-worlds/monarch-v1 --scenario scenarios/monarch-on-demand.json

# Set ANTHROPIC_API_KEY in the host environment, or point to an existing key file.
# The reader selects only ANTHROPIC_API_KEY; it never uses an admin key.
$env:TRUMAN_REWRITE_KEY_FILE='D:/path/to/existing/credentials-file'

python -m sandbox.run --world data/live-worlds/monarch-v1 --network-mode managed --network-profile data/managed-profile-v1 --model 'claude-opus-5[1m]' --effort high --seconds 900 --max-turns 12 --label 'On-demand Sonnet / high'
```

Agent subscription authentication and generator API authentication are separate. Use the existing Claude Code login for the agent. No generator secret is placed in a Compose environment, prompt, trace, or world archive.

Declare intentionally nonexistent article topics in `absent_titles` using canonical Wikipedia titles. Contradictory claims inside other articles are rewritten; the model cannot decide to delete those articles. Redirects resolve to the canonical title before this rule is checked.

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
