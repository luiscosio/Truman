"""Claude rewrite client. Credentials never enter serialized records."""
import json
import os
import re
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler

from sandbox.archive import encoded


class ProviderBlocked(ValueError):
    """Account/billing failure: stop issuing further paid requests in this process."""


_blocked_reason = None


class OutputTruncated(ValueError):
    pass


def api_key():
    value = os.environ.get('ANTHROPIC_API_KEY')
    if value:
        return value
    path = os.environ.get('TRUMAN_REWRITE_KEY_FILE')
    if path:
        for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
            match = re.match(r'^\s*(?:export\s+)?ANTHROPIC_API_KEY\s*=\s*(.*?)\s*$', line)
            if match:
                value = match[1].strip().strip('"\'')
                if value:
                    return value
    raise ValueError('Set ANTHROPIC_API_KEY or TRUMAN_REWRITE_KEY_FILE for the Claude rewriter')


def call_claude(payload, store, article, attempt):
    global _blocked_reason
    if _blocked_reason:
        raise ProviderBlocked(_blocked_reason)
    if not payload['model'].startswith(('claude-sonnet-', 'claude-opus-', 'claude-fable-')):
        raise ValueError('Unsupported Claude rewrite model')
    store.event('generation_request', article=article, attempt=attempt, provider='anthropic',
                request_blob=store.blob(encoded(payload)))
    request = Request('https://api.anthropic.com/v1/messages', data=encoded(payload), headers={
        'Content-Type':'application/json', 'anthropic-version':'2023-06-01', 'x-api-key':api_key()})
    opener = build_opener(ProxyHandler({}))
    started = time.monotonic()
    try:
        with opener.open(request, timeout=600 if payload.get('max_tokens',0)>16384 else 240) as response:
            raw=response.read(2_000_001);status=response.status;headers=list(response.headers.items())
    except HTTPError as exc:
        raw=exc.read(2_000_001);status=exc.code;headers=list(exc.headers.items())
    store.event('generation_response', article=article, attempt=attempt, provider='anthropic',
                status=status, headers=headers, response_blob=store.blob(raw), seconds=time.monotonic()-started)
    if status != 200:
        try:
            error=json.loads(raw).get('error',{})
            message=error.get('message','') if isinstance(error,dict) else str(error)
        except (ValueError,AttributeError):message=''
        if status in (401,403) or 'credit balance' in message.lower():
            _blocked_reason='Anthropic account blocked: '+(message[:500] or 'HTTP '+str(status))
            raise ProviderBlocked(_blocked_reason)
    if status != 200 or len(raw)>2_000_000:
        raise ValueError('Claude response failed; HTTP '+str(status)+' (see audited response)')
    result=json.loads(raw)
    if result.get('model') != payload['model']:
        raise ValueError('Provider returned a different model than requested')
    store.event('generation_usage', article=article, model=result['model'], usage=result.get('usage',{}), request_id=result.get('id'))
    if result.get('stop_reason')!='end_turn':
        error=OutputTruncated if result.get('stop_reason')=='max_tokens' else ValueError
        raise error('Claude did not complete the structured rewrite: '+str(result.get('stop_reason')))
    return json.loads(''.join(block['text'] for block in result.get('content',[]) if block.get('type')=='text'))


# Kept for the recorded baseline and existing callers.
call_sonnet = call_claude
