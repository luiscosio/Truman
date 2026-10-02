"""Claude rewrite client. Credentials never enter serialized records."""
import json
import os
import re
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler

from sandbox.archive import encoded
from sandbox.demand_budget import remaining


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


def exchange(opener, request, timeout):
    """One HTTP exchange bounded in total, as (body, status, headers).

    urllib's timeout limits each socket read, so a server that keeps sending
    bytes can hold a request open indefinitely. The worker is abandoned on
    expiry and its late result discarded.
    """
    result = {}

    def run():
        try:
            with opener.open(request, timeout=timeout) as response:
                result['value'] = (response.read(2_000_001), response.status, list(response.headers.items()))
        except HTTPError as exc:
            result['value'] = (exc.read(2_000_001), exc.code, list(exc.headers.items()))
        except BaseException as exc:
            result['error'] = exc
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        raise TimeoutError(f'Model request exceeded {timeout:.0f} seconds')
    if 'error' in result:
        raise result['error']
    return result['value']


def call_claude(payload, store, article, attempt):
    global _blocked_reason
    if _blocked_reason:
        raise ProviderBlocked(_blocked_reason)
    if not payload['model'].startswith(('claude-sonnet-', 'claude-opus-', 'claude-fable-', 'claude-haiku-')):
        raise ValueError('Unsupported Claude rewrite model')
    if payload['model'].startswith('claude-haiku-'):
        # Legacy generators also build adaptive requests. Normalize before
        # recording so the audit contains exactly what this model receives.
        payload={**payload,'output_config':{k:v for k,v in payload.get('output_config',{}).items() if k!='effort'}}
        if payload.get('thinking',{}).get('type')=='adaptive':payload.pop('thinking')
    request = Request('https://api.anthropic.com/v1/messages', data=encoded(payload), headers={
        'Content-Type':'application/json', 'anthropic-version':'2023-06-01', 'x-api-key':api_key()})
    opener = build_opener(ProxyHandler({}))
    for retry in range(2):
        timeout=remaining(store,600 if payload.get('max_tokens',0)>16384 else 240)
        store.event('generation_request', article=article, attempt=attempt, provider='anthropic', retry=retry,
                    request_blob=store.blob(encoded(payload)))
        started = time.monotonic()
        try:
            raw,status,headers=exchange(opener,request,timeout)
        except OSError as exc:
            # Timeouts and dropped connections get one retry within the attempt's deadline.
            store.event('generation_transport_error',article=article,attempt=attempt,
                        error_type=type(exc).__name__,seconds=time.monotonic()-started)
            if retry:raise
            store.event('generation_retry',article=article,attempt=attempt,status=None,delay_seconds=0)
            continue
        store.event('generation_response', article=article, attempt=attempt, provider='anthropic',
                    status=status, headers=headers, response_blob=store.blob(raw), seconds=time.monotonic()-started)
        if retry or status not in (429,500,502,503,504,529):break
        delay=1.0
        for key,value in headers:
            if key.lower()=='retry-after':
                try:delay=max(1,float(value))
                except ValueError:pass
        if delay>5 or remaining(store)<=delay:break
        store.event('generation_retry',article=article,attempt=attempt,status=status,delay_seconds=delay)
        time.sleep(delay)
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
    remaining(store)
    if result.get('stop_reason')!='end_turn':
        error=OutputTruncated if result.get('stop_reason')=='max_tokens' else ValueError
        raise error('Claude did not complete the structured rewrite: '+str(result.get('stop_reason')))
    return json.loads(''.join(block['text'] for block in result.get('content',[]) if block.get('type')=='text'))


# Kept for the recorded baseline and existing callers.
call_sonnet = call_claude
