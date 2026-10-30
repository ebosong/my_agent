'''Agent loop.

Invariants (checked by tests/test_loop.py):
  1. One model call per step(); a step may execute several tool calls.
  2. messages is append-only inside a step (compaction, when enabled, is the only rewrite and is logged).
  3. Every tool_call id gets exactly one role=tool message with the same tool_call_id; content is a string.
  4. Only an assistant message WITHOUT tool_calls ends the run as FinalAnswer; content alone is not a stop signal.

Stop priority: Submitted > MaxSteps > MaxCost > MaxTime > FinalAnswer. Three consecutive steps in which
every tool call was a format error (unknown tool, bad JSON, non-object args) end the run as RepeatedFormatError.
Control flow uses a stop reason string, not exceptions (a deliberate difference from mini-swe-agent).
'''
from __future__ import annotations

import time

from .events import EventLog
from .model import ModelError
from .prompts import SYSTEM_PROMPT, task_message
from .tools.base import ToolContext
from .tools.registry import ToolRegistry

FORMAT_ERROR_PREFIXES = ('unknown tool', 'invalid JSON', 'arguments must be')


class Agent:
    def __init__(self, model, tools: ToolRegistry, ctx: ToolContext, log: EventLog, system: str = SYSTEM_PROMPT,
                 max_steps: int = 30, max_cost: float = 0.5, max_seconds: float = 600.0,
                 price_in: float = 1.0, price_out: float = 2.0, max_format_errors: int = 3, compactor=None):
        self.model, self.tools, self.ctx, self.log, self.system = model, tools, ctx, log, system
        self.max_steps, self.max_cost, self.max_seconds = max_steps, max_cost, max_seconds
        self.price_in, self.price_out = price_in, price_out
        self.max_format_errors = max_format_errors
        self.compactor = compactor
        self.messages: list = []
        self.steps = 0
        self.cost = 0.0
        self.usage = {'prompt_tokens': 0, 'completion_tokens': 0}
        self.exit_status = None
        self.format_errors = 0
        self._start = time.time()

    def should_stop(self):
        if self.ctx.submitted:
            return 'Submitted'
        if self.steps >= self.max_steps:
            return 'MaxSteps'
        if self.cost >= self.max_cost:
            return 'MaxCost'
        if time.time() - self._start >= self.max_seconds:
            return 'MaxTime'
        return None

    def _add(self, msg: dict) -> None:
        self.messages.append(msg)
        self.log.emit('message', msg)

    def _account(self, usage: dict) -> None:
        pt = int(usage.get('prompt_tokens') or 0)
        ct = int(usage.get('completion_tokens') or 0)
        self.usage['prompt_tokens'] += pt
        self.usage['completion_tokens'] += ct
        self.cost += (pt * self.price_in + ct * self.price_out) / 1e6

    def step(self) -> None:
        self.steps += 1
        if self.compactor is not None:
            self.messages = self.compactor.maybe_compact(self.messages, self.log, self.steps)
            if getattr(self.compactor, 'pending_usage', None):
                self._account(self.compactor.pending_usage)  # summarizer tokens are real cost
        resp = self.model.chat(self.messages, self.tools.schemas())
        self._account(resp.get('usage') or {})
        self._add(resp['message'])
        calls = resp.get('tool_calls') or []
        if not calls:
            self.exit_status = 'FinalAnswer'
            return
        bad = 0
        for i, c in enumerate(calls):
            cid = c.get('id') or 'call_%d_%d' % (self.steps, i)
            self.log.emit('tool_call', {'name': c.get('name'), 'arguments': c.get('arguments'), 'call_id': cid})
            res = self.tools.execute(c.get('name'), c.get('arguments'), self.ctx)
            if res.returncode == -1 and res.error.startswith(FORMAT_ERROR_PREFIXES):
                bad += 1
            self.log.emit('tool_result', dict(res.as_dict(), call_id=cid, name=c.get('name')))
            self._add({'role': 'tool', 'tool_call_id': cid, 'content': res.to_content()})
        self.format_errors = self.format_errors + 1 if bad == len(calls) else 0
        if self.max_format_errors and self.format_errors >= self.max_format_errors:
            self.exit_status = 'RepeatedFormatError'

    def run(self, task: str, messages: list | None = None) -> dict:
        '''Start fresh with [system, user] or continue from restored messages (resume).'''
        self.log.emit('run_start', {'task': task, 'model': getattr(self.model, 'model', type(self.model).__name__),
                                    'workspace': str(self.ctx.workspace), 'resumed': messages is not None,
                                    'limits': {'max_steps': self.max_steps, 'max_cost': self.max_cost,
                                               'max_seconds': self.max_seconds}})
        if messages is None:
            self._add({'role': 'system', 'content': self.system})
            self._add({'role': 'user', 'content': task_message(task)})
        else:
            self.messages = list(messages)
            self._add({'role': 'user', 'content': task_message(task)}) if task and messages[-1].get('role') == 'assistant' else None
        while True:
            reason = self.exit_status or self.should_stop()
            if reason:
                self.exit_status = reason
                break
            try:
                self.step()
            except ModelError as e:
                self.log.emit('error', {'where': 'model', 'error': str(e)})
                self.exit_status = 'ModelError'
                break
        result = {'exit_status': self.exit_status, 'submission': self.ctx.submission, 'steps': self.steps,
                  'cost': round(self.cost, 6), 'usage': dict(self.usage)}
        self.log.emit('run_end', result)
        return result
