# Local Qwen world simulator: implementation and retest plan

Requested 2026-09-17. Documented before implementation.

## Goal

Run Qwen-AgentWorld-35B-A3B locally on the RTX 5090 and use it behind Truman's intercepted Wikipedia requests. Claude Code remains the evaluated agent, using its normal tools and cloud inference. The model is an environment simulator, not a replacement for Claude.

## Implementation

1. Download the Unsloth UD-Q4_K_M GGUF (about 22.1 GB) into a local cache outside Dropbox and Git. Record the upstream revision and file hash. Run the CUDA llama.cpp server in Docker, initially with a 16K context and one concurrent request. Record the image digest and actual GPU memory use. Reduce context or offload some weights if required; report any such change.
2. Retain the existing static reference and historical modes. Add an explicitly labeled synthetic mode using historical facts in a counterfactual present-day Wikipedia. This is a separate experimental condition, not an authentic old revision.
3. Give the simulator a fixed world specification, request URL, and relevant saved source excerpt. Generate a structured article representation, then render HTML and MediaWiki JSON through deterministic code. Keep revision IDs, timestamps, titles, raw text and extracts consistent. Cache each generated article within a run. Never hide generation failures behind a successful static response.
4. Keep the simulator on a separate internal Docker network reachable by the Wikipedia service, not by the agent. Do not change host DNS or trust. Keep provider traffic through the existing restricted gateway. The host-only inference endpoint is for diagnostics.
5. Save prompts, model identity/settings, generated content, timings, validation failures and hashes outside the agent. Preserve the old corpus and prior reports. Add CLI selection and reproducible startup instructions.

## Validation and retest

- Run existing tests plus meaningful checks for cross-endpoint consistency, cache reuse, malformed model output, failure handling, and synthetic labeling.
- Verify CUDA loading and perform a real local generation; measure latency and memory, not estimated throughput.
- Probe Wikipedia HTML, raw text and revision/extract APIs from the agent network. Check that the agent cannot access the simulator API or unrestricted internet.
- Rerun matching reference, historical and synthetic monarch tasks with the same Claude model, task, follow-up, tools and limits. Follow up by explicitly pressing the discrepancy. Preserve complete traces and intercepted requests.
- Report what Claude actually observed and said, including whether it identifies stale evidence, conflicting claims, or a simulation. A single run per condition is a smoke evaluation, not a statistically reliable improvement claim.

## Constraints and interpretation

The 5090 has 32 GB VRAM, with roughly 25 GiB free at inspection. Quantized model size is not total runtime memory. Short-context, quantized inference is not the paper's full setup: Qwen recommends at least 128K context for extended trajectories. A generated encyclopedia can contradict itself; this first integration only controls a small declared world and supported Wikipedia endpoints. TLS certificates and network topology remain discoverable. Model downloads and setup need internet; simulated responses run locally. Claude still needs its provider connection.

## Sources

- https://huggingface.co/Qwen/Qwen-AgentWorld-35B-A3B
- https://huggingface.co/unsloth/Qwen-AgentWorld-35B-A3B-GGUF
- https://github.com/ggml-org/llama.cpp/blob/master/docs/docker.md

Implementation outcomes, deviations and measured retest results will be recorded separately in QWEN_RESULTS.md.
