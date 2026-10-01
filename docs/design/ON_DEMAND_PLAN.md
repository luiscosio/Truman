# Persistent on-demand Wikipedia world

Implementation plan, 2026-09-18. Supersedes the preselected-page workflow for exploration.

The operator fixes a scenario, source cutoff, model and budgets when creating a world. A host-side world service captures Wikipedia originals and asks Claude Sonnet to rewrite them only when requested. The isolated origin container communicates through a per-run filesystem queue; the agent has neither that mount nor access to the generator's credentials or upstream internet. No new host HTTP listener is needed.

Persistent storage records immutable generation attempts, content-addressed bodies, source revisions, accepted facts, aliases, missing pages and request responses. SQLite transactions serialize first writes, preventing duplicate generation and conflicting fact commitments. Accepted articles never change in-place. HTML, extracts, raw-source projections and search snippets derive from one accepted DOM. All article text nodes, including infoboxes and navigation templates, are eligible for edits; the original layout is retained. A separate Sonnet review must accept edits and added facts before publication. This is a consistency check, not a proof of truth.

History is acquired lazily at the pinned cutoff, preserving source revision ordering and timestamps while rewriting each requested revision under the same world rules. Intentional missing pages return MediaWiki missing-page responses. Unsupported operations, generation failures and exhausted budgets remain distinct recorded coverage failures; there is no live-response fallback.

Exploration grows the world. An export freezes the committed articles, revision records, assets, request cache and provenance. Replay uses the same deterministic adapter with acquisition/generation disabled. Requests outside the export fail coverage, rather than extending it. New comparisons use new exports.

Delivery checks: concurrent request deduplication; restart persistence; transaction rollback after rejected edits; fixed-cutoff acquisition; HTML/API consistency; credential isolation; unchanged response bytes on repeat requests; no network/model access during frozen replay; original and patched bytes archived; container interception; real Sonnet generation and an agent smoke run. Keep the next/back report viewer and single-trace export.

Limits to report explicitly: model review cannot guarantee global semantic consistency; capture-time templates can differ from source-time templates; projected wikitext is not the original template source; first requests can be slow; only supported Wikipedia read routes are emulated. Do not describe the service as indistinguishable from Wikipedia.
