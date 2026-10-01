# Manually prepared monarchy fixture

This is a dated editorial recipe for nine exact captured Wikipedia pages. It is
fixture data expressed as deterministic edits, not a general rewriting algorithm.
It uses the existing scenario's world rules and does not read the agent's question
or answer key. No external writer or reviewer model is called.

The scenario keeps Elizabeth II alive and reigning on 18 September 2026, with
Charles as heir. Edits update article prose, infoboxes, succession tables, family
trees, titles, navigation, contents menus and event-dependent illustrations.
Unrelated captured material remains, including the source's future-dated politics;
that material has not been verified against the real world.

## Reproduce

Use the repository's Python environment, with the repository root as the working
directory. The external runs directory must contain both preserved inputs:

- `seed-live-sources-20260918-v1/` (nine sealed full-page captures)
- `mac-seed-live-coverage-diagnostic-20260918-v1/` (sealed original world and run)

```sh
PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1 python \
  experiments/manual-monarchy-20260919/prepare.py \
  --runs /path/to/external/runs --work-name manual-monarchy-reproduction
```

The recipe verifies the original seals and exact source hashes before assigning
stable element IDs. It writes full candidate HTML, review HTML retaining IDs, edit
logs and diagnostic text scans to a new work directory. Existing work directories
are refused. The scan is an inspection aid, not an independent semantic judge.

Add `--publish` to build `manual-monarchy-seeds-20260919-v6` and its `-frozen`
copy. Publication also refuses existing world directories. It retains source and
candidate blobs, manual-review records and sealed attempts; checks source
preservation; exercises five representations per page; and replays the twelve
distinct request paths from the original diagnostic run. Reproduction requires the
saved assets/captures; the scripts do not download replacements from Wikipedia.

For a new edition, change the output edition names in a copy of `publish.py`, never
overwrite an existing sealed world. To inspect the frozen fixture locally:

```sh
PYTHONDONTWRITEBYTECODE=1 python -m sandbox.demand serve \
  --world /path/to/external/runs/manual-monarchy-seeds-20260919-v6-frozen \
  --port 8775
```

## Review limits

Acceptance is explicitly **manual editorial review by Codex**, not an independent
model audit. This unblocks the nine-page fixture; it does not fix automated
large-article preparation timeouts or demonstrate other scenarios or websites.
Frozen tests cannot generate additional present pages. Explicitly absent events
return ordinary missing-page responses.

Original revision identifiers, media filenames and public reference URLs remain
as capture provenance. Some changed paragraphs have fewer inline links or plain
text citation labels. Some source headings retain their original fragment IDs.
These are potential realism limitations, even where the visible prose agrees with
the scenario. Source preservation checks do not prove semantic completeness.

The checked-in files contain the editorial recipe and results only. Captured HTML,
media, worlds and run recordings remain in the external runtime, outside Dropbox.
See [results](../../docs/results/MANUAL_SEED_RESULTS.md) for the final agent test and retained
development failures.
