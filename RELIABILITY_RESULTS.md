# Seed/live reliability fixes — 19 September 2026

The seed + live-generation design remains in place. Topic availability is checked
before rewriting; source preservation and recoverable edits protect existing
content; cached reads no longer wait for cold generation; and request/provider
failures have deadlines and explicit audit outcomes. The changes use scenario data,
not monarchy-specific rules or target questions.

## Validation

- **141 automated tests pass**: 109 sandbox and 32 core tests. Fourteen focused
  regressions cover cached reads during generation, terminal queue outcomes,
  rollback on deadline, absent/uncertain topics, deleted-lead recovery, source
  preservation, canonical links, seed validation and bounded provider retries.
- **12/12 controlled page generations passed** the existing required-content,
  forbidden-content and source-preservation checks across three scenarios, each
  requested in both orders in independent worlds. The scenarios cover leadership,
  a cancelled event, and delayed technology with a renamed organization.
- The writing model was `claude-haiku-4-5-20251001`; planning and validation used
  `claude-sonnet-5` (low planning effort, medium review effort). Failed first-pass
  edits could escalate to Sonnet. These are not Haiku-only timings.
- Cold generation took **20.2–46.9 seconds**, median **29.4 seconds**. Derived cached
  summaries took **1.0–6.7 milliseconds**, median **1.6 milliseconds**, measured
  inside the host service; this excludes gateway, browser and network overhead.
- The original problematic accession topic was classified **absent in 3.4 seconds**
  from its already captured source. No rewriting was needed. This timing does not
  include source acquisition.
- The final controlled comparison used 95 successful provider calls, approximately
  **$1.05** using the project's recorded token-price estimates, not an invoice.
  Earlier development comparisons, including failures, remain separately recorded;
  together the controlled development runs cost approximately **$10.21**, including
  the final comparison and excluding the full-page preparations below.

Manual inspection of all 12 accepted outputs found no additional world-fact
contradictions. Minor presentation defects remain: one redundant inline name link
and empty containers after legitimate deletions. This was a controlled rewrite
comparison, without an additional blind model judge or a new target-agent run.

## Scope and evidence

The new structural checks also flag the previously damaged Elizabeth II, Charles,
monarchs-list and royal-family seeds. Passing a structural check is not semantic
validation of the other seeds. Unvalidated diagnostic seeds are blocked from
forking or being marked ready; the old sealed reports remain unchanged.

Final controlled audit under the external Mac runtime:
`~/.local/share/truman/mac/runs/reliability-fix-live-20260919-provenance/`.
It contains source/response audits, six frozen worlds, accepted HTML, the reproduction
script, result JSON and a manual review. Its seal is
`c9467ff1d8e0298746208435fe496f53b545f3fc34c4ebebc5e6c67ce7cf35c6`.

Earlier development results are retained in `reliability-fix-live-20260919-v1`
through `v7` and `reliability-fix-live-20260919-final`; the directory named `final`
preceded the source-provenance correction and is not the final successful comparison.

This remains a Wikipedia-focused prototype. These tests do not establish coverage
of new website adapters, held-out agent questions, simulation awareness, or readiness
of the complete original nine-page seed set. Large captured pages require separate
preparation and validation; a deadline failure never publishes a partial page.

## Full Wikipedia preparation remains incomplete

The original captured *List of British monarchs* was also rebuilt from its saved
source in two separate worlds. Both attempts exhausted a 300-second offline
preparation budget and published **no page**. The first used high review effort;
the second used medium review effort and the final source-provenance logic.
Their estimated provider usage was $1.44 and $2.18 respectively. Both failed audits
and frozen worlds are retained under the runtime's
`runs/reliability-real-list-seed-20260919-v1/` and `v2/`.

The core failure-handling and integrity mechanisms are implemented, but **the full
nine-page seed set is not ready for another agent experiment**. Large-article
preparation still needs performance work. There was no replacement target-agent
awareness run. The original diagnostic evidence seal remains
`ebeeab471f965af0fc3924ed508bfe1a619f30806fe21555a6cac85950d56c78`.

Total estimated provider usage for this implementation's controlled development
and two full-page preparations was approximately **$13.83**. Figures use the
project's recorded token prices, exclude unreported failed-call billing, and are
not invoices. Earlier runs are development evidence, not extra independent
confirmation of the final successful controlled comparison.
