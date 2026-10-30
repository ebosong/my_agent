'''Session restore from the JSONL event log.

Replay rules: `message` events rebuild the history in order; a `compaction` event replays the same rewrite
(messages[2:2+dropped] replaced by the logged summary message). If the process died while tools were running,
an assistant message may have tool_calls without matching tool messages; repair() adds one explicit
"interrupted" observation per missing id so the pairing invariant holds and the model is told the result is unknown.
'''
from __future__ import annotations

import json

from .events import read_events

INTERRUPTED = {'returncode': -1, 'output': '', 'truncated': False,
               'error': 'interrupted: the harness stopped before this tool finished; its result is unknown and side effects may have happened. Check the workspace before repeating it.'}


def repair(messages: list):
    out, fixed, i = [], [], 0
    while i < len(messages):
        m = messages[i]
        out.append(m)
        i += 1
        if m.get('role') == 'assistant' and m.get('tool_calls'):
            want = [tc['id'] for tc in m['tool_calls']]
            seen = set()
            while i < len(messages) and messages[i].get('role') == 'tool':
                seen.add(messages[i].get('tool_call_id'))
                out.append(messages[i])
                i += 1
            for cid in want:
                if cid not in seen:
                    out.append({'role': 'tool', 'tool_call_id': cid, 'content': json.dumps(INTERRUPTED, ensure_ascii=False)})
                    fixed.append(cid)
    return out, fixed


def restore(path):
    '''Return (messages, last_event_id, info). messages are repaired; info lists synthesized call ids.'''
    events = read_events(path)
    messages, corrupt, last_id = [], 0, None
    for ev in events:
        if ev.get('id'):
            last_id = ev['id']
        t, p = ev.get('type'), ev.get('payload') or {}
        if t == 'corrupt_line':
            corrupt += 1
        elif t == 'message':
            messages.append(p)
        elif t == 'compaction' and p.get('summary_message'):
            messages = messages[:2] + [p['summary_message']] + messages[2 + int(p.get('dropped', 0)):]
    last_end = next((e for e in reversed(events) if e.get('type') == 'run_end'), None)
    task = next((e['payload'].get('task') for e in events if e.get('type') == 'run_start'), '')
    messages, fixed = repair(messages)
    info = {'events': len(events), 'corrupt_lines': corrupt, 'interrupted_call_ids': fixed,
            'previous_exit_status': (last_end or {}).get('payload', {}).get('exit_status'), 'task': task}
    return messages, last_id, info
