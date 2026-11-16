# Running Truman on Windows

Verified on Windows 11 with Docker Desktop on 2026-11-15: both host test suites, every
image build and the in-container tests listed below. A live agent run has not been
made from Windows yet, and the [Mac launchers](MAC_SETUP.md#run) have no Windows
equivalent.

The [Mac guide's](MAC_SETUP.md) layout applies here too: develop in the Dropbox
checkout and keep the runtime (`.venv`, `.env`, `data/`, `runs/`, `reports/`, the
video's `node_modules`) in a separate checkout outside Dropbox, such as
`%LOCALAPPDATA%\truman\windows`.

## Requirements

- Docker Desktop with the Linux engine.
- [uv](https://docs.astral.sh/uv/) 0.13 or later; 0.11 can't download Python 3.13.18.
  `uv self update` upgrades a standalone install.
- Python 3.13.18, the version in `.python-version` and in every image:
  `uv python install 3.13.18`. uv also inspects every `python*.exe` on `PATH`, and a
  shim that points at an uninstalled Python (an old Chocolatey `python3.13.exe`, for
  example) makes `uv sync` fail with "Failed to inspect Python interpreter". Remove the
  stale shim (`choco uninstall python313 --skip-autouninstaller` from an elevated shell
  removes only Chocolatey's record and shim).
- pnpm, for the [explainer video](../../tools/explainer-video/README.md) only. Node.js 25
  and later no longer ship Corepack, so install pnpm on its own (`scoop install pnpm`)
  rather than with `corepack enable`.

## Set up and test

```powershell
uv sync --all-extras
uv run python -m truman test
uv run python -m unittest discover -s sandbox -t . -p "test_*.py"
```

`--all-extras` adds `rewrite` (lxml, mwparserfromhell, PyYAML), `network` (mitmproxy,
dnslib) and `video` (Pillow, for the trace-video tool).

Build the images and run the container tests:

```powershell
docker build -f sandbox/Dockerfile.world -t truman-network-world:local .
docker build -f sandbox/Dockerfile.agent -t truman-network-agent:local .
docker build -f sandbox/Dockerfile.managed-gateway -t truman-managed-gateway:local .
docker build -f sandbox/Dockerfile.gateway -t truman-transparent-gateway:local .
docker compose build viewer
docker compose --profile tools build test

docker compose run --rm test
docker run --rm --network none truman-network-world:local python -m unittest sandbox.test_render sandbox.test_synthetic sandbox.test_archive sandbox.test_suite
docker run --rm --network none truman-transparent-gateway:local python -m unittest sandbox.test_transparent
```

The report viewer (`docker compose up -d viewer`) serves `reports/` at
http://localhost:8765/.
