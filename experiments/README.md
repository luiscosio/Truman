# Experiments

Every recorded experiment, oldest first. Folders here hold an experiment's scenario,
task, scripts and results; dated write-ups that predate these folders live in
[docs/results](../docs/results). Sealed runs, worlds and HTML reports stay outside
the repository (`runs/`, `data/`, `reports/`).

| Date | Experiment | Sites | What it tested | Outcome |
| --- | --- | --- | --- | --- |
| 2026-09-17 | [Build verification](../docs/results/VALIDATION.md) | Wikipedia (2016 snapshot) | First network-level runs: Claude Code in a container reaching a local Wikipedia over real DNS and TLS. | Historical and reference runs completed; stale content was handled as staleness, not flagged as a simulation. |
| 2026-09-17 | [Local Qwen simulator](../docs/results/QWEN_RESULTS.md) | Wikipedia | Generating counterfactual pages with a local Qwen model on an RTX 5090. | Infrastructure worked; Claude identified the generated encyclopedia as synthetic. |
| 2026-09-18 | [World-model rewrite](../docs/results/WORLD_MODEL_RESULTS.md) | Wikipedia | A fixed, dated world specification with full-document planning, block rewriting and cross-page review, across three scenarios and both request orders. | Sonnet and Opus at high effort each passed 11 of 12 planned pages; no clear winner on this sample. |
| 2026-09-19 | [Reliability fixes](../docs/results/RELIABILITY_RESULTS.md) | Wikipedia | Seed plus live generation: availability checks, preservation, deadlines, cached reads during cold generation. | Fixes validated; automated preparation of large pages still timed out. |
| 2026-09-19 | [Manual monarchy seeds](manual-monarchy-20260919/README.md) ([results](../docs/results/MANUAL_SEED_RESULTS.md)) | Wikipedia | Nine hand-edited pages (Elizabeth II still reigning) as a frozen fixture. | Agent runs completed against the fixture. |
| 2026-09-19 | [Musk as OpenAI CEO](musk-openai-20260919/README.md) | Wikipedia | Four hand-edited articles; paired reference/synthetic runs, then native wikitext and preserved revision metadata. | Synthetic agents inferred a modified Wikipedia from coverage errors and history probes; findings fed the MediaWiki-native error handling. |
| 2026-09-20 | [Router over SSH](router-route-20260920/README.md) | SSH appliance | A real OpenSSH session to an isolated Linux router with an injected stale route. | The agent found and removed the bad route, restoring the health endpoint; it also noticed it was in a container. |
| 2026-10-01 | [ISA Mining Code, two sites](isa-mining-code-20261001/README.md) | Wikipedia, Global Voices | One compiled world served by two linked sites with cross-site review; paired agent run. | Both runs completed with no coverage errors; neither agent suspected a simulation. |

## Browsing runs

Generate a sorted, searchable index of every run, suite and world, linked to its HTML
report and to the write-up above that documents it:

```bash
python -m truman.report_index --runs runs --reports reports --experiments experiments --results docs/results
```

It writes `reports/index.html`. Run folders are sealed records and are never moved.
