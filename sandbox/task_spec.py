"""Question definitions for target agents, separate from world generation inputs."""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit


def load_task(path):
    value = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(value, dict) or set(value) != {'id', 'prompt', 'required_urls'}:
        raise ValueError('Task file must contain only id, prompt and required_urls')
    if not isinstance(value['id'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}', value['id']):
        raise ValueError('Invalid task id')
    if not isinstance(value['prompt'], str) or not value['prompt'].strip():
        raise ValueError('Task prompt must be nonempty text')
    urls = value['required_urls']
    if not isinstance(urls, list) or not all(isinstance(u, str) for u in urls):
        raise ValueError('required_urls must be a list of web URLs')
    for url in urls:
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Task URLs must be HTTP(S) URLs without credentials')
    return value
