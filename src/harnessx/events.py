'''JSONL event log: append-only, one JSON object per line, flushed on every write.

Every event carries id / parent_id so a session is a chain; resume walks the chain.
'''
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path


def _now() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


class EventLog:
    def __init__(self, path, last_id=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.last_id = last_id

    def emit(self, type_: str, payload=None) -> str:
        ev = {'id': uuid.uuid4().hex[:8], 'parent_id': self.last_id, 'type': type_,
              'ts': _now(), 'payload': payload or {}}
        with self.path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(ev, ensure_ascii=False) + '\n')
            f.flush()
        self.last_id = ev['id']
        return ev['id']


def read_events(path) -> list:
    '''Parse a JSONL file. A corrupt line (e.g. torn last write) becomes a corrupt_line event.'''
    events = []
    for i, line in enumerate(Path(path).read_text(encoding='utf-8').splitlines(), 1):
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            ev = {'id': None, 'parent_id': None, 'type': 'corrupt_line', 'ts': '',
                  'payload': {'raw': line[:200]}}
        ev['_line'] = i
        events.append(ev)
    return events


def _clip(s, n=100) -> str:
    s = str(s).replace('\n', ' ')
    return s if len(s) <= n else s[:n] + '...'


def format_trace(events: list) -> str:
    '''Human-readable trace. The leading number is the real JSONL line number.'''
    out = []
    for ev in events:
        p = ev.get('payload') or {}
        t = ev.get('type')
        if t == 'run_start':
            d = 'task=%s model=%s' % (_clip(p.get('task')), p.get('model'))
        elif t == 'message':
            d = '%s %s' % (p.get('role'), _clip(p.get('content', '')))
        elif t == 'tool_call':
            d = '%s id=%s args=%s' % (p.get('name'), p.get('call_id'), _clip(p.get('arguments')))
        elif t == 'tool_result':
            d = 'id=%s rc=%s truncated=%s %s' % (p.get('call_id'), p.get('returncode'),
                                                  p.get('truncated'), _clip(p.get('output', ''), 60))
        elif t == 'run_end':
            d = 'status=%s steps=%s cost=%s' % (p.get('exit_status'), p.get('steps'), p.get('cost'))
        else:
            d = _clip(json.dumps(p, ensure_ascii=False))
        out.append('%03d %s %s' % (ev['_line'], t, d))
    return '\n'.join(out)
