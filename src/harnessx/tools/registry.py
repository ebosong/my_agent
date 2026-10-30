'''ToolRegistry: schemas for the model, and execute() that never raises.

Unknown tool, bad JSON, non-dict args, tool exceptions and path escapes all become
ToolResult observations so the model can react; the main loop never sees an exception.
'''
from __future__ import annotations

import json

from .base import PathEscape, Tool, ToolContext, ToolResult, truncate_head_tail


class ToolRegistry:
    def __init__(self):
        self._tools: dict = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def names(self) -> list:
        return list(self._tools)

    def subset(self, names) -> 'ToolRegistry':
        '''New registry with only the named tools; submit is always kept so the run can end explicitly.'''
        reg = ToolRegistry()
        for n, t in self._tools.items():
            if n in names or n == 'submit':
                reg.register(t)
        return reg

    def schemas(self) -> list:
        return [t.schema() for t in self._tools.values()]

    def execute(self, name, args, ctx: ToolContext) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(-1, '', 'unknown tool: %s. available: %s' % (name, ', '.join(self.names())))
        if isinstance(args, (str, bytes)):
            text = args.decode('utf-8', 'replace') if isinstance(args, bytes) else args
            if not text.strip():
                args = {}
            else:
                try:
                    args = json.loads(text)
                except json.JSONDecodeError as e:
                    return ToolResult(-1, '', 'invalid JSON arguments: %s' % e)
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return ToolResult(-1, '', 'arguments must be a JSON object, got %s' % type(args).__name__)
        try:
            res = tool.run(args, ctx)
        except PathEscape as e:
            return ToolResult(-1, '', 'path rejected: %s' % e)
        except Exception as e:  # tool bug or bad argument types: report, do not crash the loop
            return ToolResult(-1, '', '%s: %s' % (type(e).__name__, e))
        if not isinstance(res, ToolResult):
            res = ToolResult(0, str(res))
        out, cut = truncate_head_tail(res.output if isinstance(res.output, str) else str(res.output))
        if cut:
            res.output, res.truncated = out, True
        return res
