# Standing product requirements

Truman is intended to be a reusable simulated-web research testbed. The operator
will define different scenarios and ask agents multiple different questions across
different websites. The monarchy/Wikipedia experiment is one benchmark fixture.
Keep this scope when proposing architecture, implementing fixes and reporting results.

- Keep scenario facts, dates, entities, aliases and invariants in scenario data.
  Keep example-specific rules and expected answers out of shared implementation
  and shared prompts. Fix mechanisms that transfer to other scenarios.
- Compile a shared world specification independently of the target questions.
  Rewriters and topic-availability decisions receive world rules and source
  material, without target question prompts or answer keys. Reuse the same world
  across different questions and request orders.
- Separate world reasoning, persistence, generation and validation from website
  adapters. Site-specific acquisition, routes, HTML, APIs, search, metadata and
  rendering belong in adapters. Wikipedia conventions must not become universal
  assumptions in the world engine.
- Maintain consistent entities, events and time across pages and websites.
  Distinguish topics ruled out by the scenario from unsupported routes, missing
  source coverage and generation failures. A new topic must be assessed against
  the world rules before spending time rewriting an impossible article.
- Support reusable seeds plus live generation for new requests. Cache and freeze
  results for repeatable comparisons. Cached requests should remain responsive
  during cold generation. Measure cold latency, cached latency, cost and quality
  separately; a fast writing model alone does not establish fast service.
- Evaluate generalization with multiple unrelated scenarios, held-out questions,
  different request orders and multiple website adapters. A single successful
  Wikipedia example does not establish cross-scenario or cross-site support.
- Report implemented capabilities and tested coverage precisely. Preserve failed
  audits, label unvalidated diagnostic content, and distinguish agent task
  completion from generation success and explicit simulation awareness.

The current implementation is Wikipedia-focused. Other website adapters and broad
cross-site validation remain work to implement; do not describe them as available.
