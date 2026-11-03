#!/usr/bin/env python3
"""Run Truman on a Mac with the project API key, never in argv or logs.

Reads ANTHROPIC_API_KEY from the checkout's Git-ignored .env and passes it to the run
through the environment, with an empty credentials file in place of a subscription
login. Run from the runtime checkout (outside Dropbox); arguments go to
`python -m sandbox.run`. Also the --launcher for `python -m sandbox.demand_pair`.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    values = {}
    for line in (ROOT / '.env').read_text().splitlines():
        if line.strip() and not line.lstrip().startswith('#') and '=' in line:
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    key = values.get('ANTHROPIC_API_KEY')
    if not key:
        raise SystemExit('Project API key is missing')
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE='1', TRUMAN_TARGET_API_KEY=key, TRUMAN_REWRITE_KEY_FILE=str(ROOT / '.env'))
    with tempfile.TemporaryDirectory(prefix='api-auth-', dir=ROOT.parent) as temporary:
        credential = Path(temporary) / 'credentials.json'
        fd = os.open(credential, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump({}, stream)
        env['TRUMAN_CLAUDE_CREDENTIALS'] = str(credential)
        return subprocess.call([str(ROOT / '.venv/bin/python'), '-m', 'sandbox.run', *sys.argv[1:]], cwd=ROOT, env=env)


if __name__ == '__main__':
    raise SystemExit(main())
