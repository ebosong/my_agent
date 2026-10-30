'''OpenAI-compatible chat client (stdlib urllib only) and a scripted FakeModel for tests.

chat() returns {'message', 'tool_calls', 'usage', 'finish_reason'}; message is the
assistant message exactly as it will be appended to history.
'''
from __future__ import annotations

import copy
import json
import time
import urllib.error
import urllib.request


class ModelError(RuntimeError):
    pass


def normalize(msg: dict, usage, finish) -> dict:
    calls = []
    for tc in msg.get('tool_calls') or []:
        fn = tc.get('function') or {}
        calls.append({'id': tc.get('id'), 'name': fn.get('name'), 'arguments': fn.get('arguments', '')})
    message = {'role': 'assistant', 'content': msg.get('content') or ''}
    if calls:
        message['tool_calls'] = [
            {'id': c['id'], 'type': 'function',
             'function': {'name': c['name'],
                          'arguments': c['arguments'] if isinstance(c['arguments'], str)
                          else json.dumps(c['arguments'], ensure_ascii=False)}}
            for c in calls]
    return {'message': message, 'tool_calls': calls, 'usage': usage or {}, 'finish_reason': finish}


class OpenAICompatModel:
    def __init__(self, base_url: str, model: str, api_key: str, timeout: float = 120.0, retries: int = 3):
        self.base_url, self.model, self.api_key = base_url, model, api_key
        self.timeout, self.retries = timeout, retries

    def chat(self, messages: list, tools: list) -> dict:
        body = {'model': self.model, 'messages': messages}
        if tools:
            body['tools'] = tools
            body['tool_choice'] = 'auto'
        data = json.dumps(body, ensure_ascii=False).encode('utf-8')
        url = self.base_url.rstrip('/') + '/chat/completions'
        headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.api_key}
        last = None
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(url, data=data, headers=headers, method='POST')
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    payload = json.loads(r.read().decode('utf-8'))
                choice = payload['choices'][0]
                return normalize(choice['message'], payload.get('usage'), choice.get('finish_reason'))
            except urllib.error.HTTPError as e:
                detail = e.read().decode('utf-8', 'replace')[:300]
                last = ModelError('HTTP %s: %s' % (e.code, detail))
                if e.code not in (429, 500, 502, 503, 504):
                    raise last  # 401/400 etc: retrying will not help
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last = ModelError('network error: %s' % e)
            time.sleep(min(2 ** attempt, 8))
        raise last


class FakeModel:
    '''Scripted responses; each item is {content?, tool_calls?, usage?} or an Exception to raise.
    requests keeps a deep copy of every messages list it was sent, for assertions.'''

    def __init__(self, script: list):
        self.script = list(script)
        self.requests: list = []
        self.tool_sets: list = []

    def chat(self, messages: list, tools: list) -> dict:
        self.requests.append(copy.deepcopy(messages))
        self.tool_sets.append(copy.deepcopy(tools))
        if not self.script:
            raise ModelError('FakeModel script exhausted')
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        msg = {'content': item.get('content', '')}
        if item.get('tool_calls'):
            msg['tool_calls'] = [
                {'id': c['id'], 'type': 'function',
                 'function': {'name': c['name'], 'arguments': c['arguments']}}
                for c in item['tool_calls']]
        return normalize(msg, item.get('usage'), 'tool_calls' if item.get('tool_calls') else 'stop')
