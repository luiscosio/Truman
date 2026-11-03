# Running Truman on a Mac

Two checkouts of the same repository:

| Checkout | Holds | Why |
| --- | --- | --- |
| The Dropbox folder | Development: edits, commits, `git push` | Synced and backed up |
| `~/.local/share/truman/mac` | The runtime: `.venv`, `.env`, Docker builds, `data/`, `runs/`, `reports/`, the video's `node_modules` | Large, machine-specific and fast-changing; keep it out of Dropbox |

Bring the runtime up to date after committing in the Dropbox checkout (or pull from GitHub):

```sh
git -C ~/.local/share/truman/mac fetch <Dropbox checkout> main
git -C ~/.local/share/truman/mac merge --ff-only FETCH_HEAD
```

Don't create a `.venv` or `node_modules` inside Dropbox. Marking a synced folder as
ignored [removes it from Dropbox's servers and other devices](https://help.dropbox.com/sync/ignored-files),
so the runtime lives elsewhere instead.

## Requirements

- Docker Desktop.
- [uv](https://docs.astral.sh/uv/) 0.13 or later; older releases don't know Python 3.13.18.
  `uv self update` upgrades a standalone install.
- Python 3.13.18, the version in `.python-version` and in every image
  (`python:3.13.18-slim-trixie`): `uv python install 3.13.18`.
- pnpm, for the [explainer video](../../tools/explainer-video/README.md) only.

## Set up the runtime

```sh
cd ~/.local/share/truman/mac
uv sync --extra rewrite --extra network
```

`rewrite` brings the page tools (lxml, mwparserfromhell, PyYAML); `network` brings
mitmproxy and dnslib, which the managed network and its tests use. Put the project API
key in the Git-ignored `.env` as `ANTHROPIC_API_KEY=...`; it is never committed or
built into an image.

Build the images (they share one base, `python:3.13.18-slim-trixie`):

```sh
docker build -f sandbox/Dockerfile.world -t truman-network-world:local .
docker build -f sandbox/Dockerfile.agent -t truman-network-agent:local .
docker build -f sandbox/Dockerfile.managed-gateway -t truman-managed-gateway:local .
docker build -f sandbox/Dockerfile.gateway -t truman-transparent-gateway:local .
docker build -f Dockerfile -t truman-wikipedia:local .
```

The agent image pins the Claude Code version (`CLAUDE_VERSION` in
`sandbox/Dockerfile.agent`). A network profile builds its own agent image from it and
records the image ids, so build a new profile after rebuilding the agent:

```sh
.venv/bin/python -m sandbox.transparent --managed --profile data/managed-profile-mac-v7 \
  --site-policy experiments/pluto-planet-20261001/sites.json
```

## Run

Two launchers, both in `tools/` and both run from the runtime checkout:

- `tools/run-mac.py` uses this Mac's Claude Code subscription login. It reads the login
  from Keychain into a protected temporary file outside the checkout, mounts it for the
  run and removes it afterwards.
- `tools/run-mac-api.py` uses the project API key from `.env`, passed through the
  environment, never in arguments or logs.

Arguments go to `python -m sandbox.run`. A single run:

```sh
tools/run-mac-api.py --world <frozen world> [--world <frozen world> ...] --condition synthetic \
  --task-file <task.json> --network-mode managed --network-profile data/managed-profile-mac-v7 \
  --model 'claude-opus-5[1m]' --effort high --follow-up "What do you think is happening?" --run-id <id>
```

A paired run (reference and edited worlds, the same task and follow-up):

```sh
.venv/bin/python -m sandbox.demand_pair --reference <frozen world> ... --synthetic <frozen world> ... \
  --profile data/managed-profile-mac-v7 --task-file <task.json> --model 'claude-opus-5[1m]' --effort high \
  --launcher tools/run-mac-api.py --run-id <id>
```

Run on the UTC day a world is dated: the task date, the agent's clock and the HTTP
`Date` header then agree. Worlds pin the renderer image that serves them; if that image
was rebuilt or removed, fork the world onto the new one
([Recording and repeatability](REPRODUCIBILITY.md)).

The report viewer (`docker compose up -d viewer`) serves `reports/` at
http://localhost:8765/.
