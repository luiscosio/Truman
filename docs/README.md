# Documentation

## Guides

| Guide | Covers |
| --- | --- |
| [Mac setup](guides/MAC_SETUP.md) | The runtime checkout outside Dropbox, Python and uv versions, images, profiles and the launchers |
| [Windows setup](guides/WINDOWS_SETUP.md) | uv, Python and pnpm on Windows, host tests, image builds and container tests |
| [Site profiles](guides/SITES.md) | Defining a simulated website in YAML, linking sites, running several in one experiment |
| [On-demand worlds](guides/ON_DEMAND.md) | Persistent worlds: seeds, live generation, freezing and preparation |
| [Configurable generators](guides/REWRITE.md) | Rewriting captured pages against a world specification |
| [Network sandbox](guides/SANDBOX.md) | Running the agent inside containers with an isolated web |
| [Transparent network](guides/TRANSPARENT_NETWORK.md) | Ordinary DNS and TLS interception without agent-visible proxies |
| [Managed network](guides/MANAGED_NETWORK.md) | The mitmproxy gateway, site policy and pinned DNS used by current runs |
| [Recording and repeatability](guides/REPRODUCIBILITY.md) | Sealed archives, frozen worlds and replay |
| [Local Qwen simulator](guides/QWEN.md) | Generating pages with a local model |

## Results

Dated write-ups; newer experiments keep their results in [experiments](../experiments/README.md).

- [Build verification, 2026-09-17](results/VALIDATION.md)
- [Local Qwen integration, 2026-09-17](results/QWEN_RESULTS.md)
- [World-model rewrite, 2026-09-18](results/WORLD_MODEL_RESULTS.md)
- [Reliability fixes, 2026-09-19](results/RELIABILITY_RESULTS.md)
- [Manual seed preparation, 2026-09-19](results/MANUAL_SEED_RESULTS.md)

## Design history

The original plans, kept as written: [project plan](design/PLAN.md),
[Wikipedia MVP](design/WIKIPEDIA-MVP.md), [Qwen plan](design/QWEN_PLAN.md),
[generator plan](design/REWRITE_GENERATOR_PLAN.md) and
[on-demand plan](design/ON_DEMAND_PLAN.md).
