#!/usr/bin/env python3
"""Run Truman on a Mac with temporary Claude subscription credentials.

Reads this Mac's Claude Code login from Keychain into a protected temporary file
outside the checkout, mounts it for the run and removes it afterwards. Run from the
runtime checkout (outside Dropbox); arguments go to `python -m sandbox.run`.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    env = os.environ.copy()
    env.pop('ANTHROPIC_API_KEY', None)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    env['TRUMAN_REWRITE_KEY_FILE'] = str(ROOT / '.env')
    auth = subprocess.run(['security', 'find-generic-password', '-s', 'Claude Code-credentials', '-w'],
                          capture_output=True, text=True, check=True)
    data = json.loads(auth.stdout)
    if not data.get('claudeAiOauth', {}).get('accessToken'):
        raise SystemExit('Sign into Claude Code on this Mac before running an agent.')
    with tempfile.TemporaryDirectory(prefix='auth-', dir=ROOT.parent) as temporary:
        credential = Path(temporary) / 'credentials.json'
        fd = os.open(credential, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump({'claudeAiOauth': data['claudeAiOauth']}, stream)
        env['TRUMAN_CLAUDE_CREDENTIALS'] = str(credential)
        return subprocess.call([str(ROOT / '.venv/bin/python'), '-m', 'sandbox.run', *sys.argv[1:]], cwd=ROOT, env=env)


if __name__ == '__main__':
    raise SystemExit(main())
