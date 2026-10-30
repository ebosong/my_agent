'''submit: the explicit end-of-task signal (highest stop priority).'''
from __future__ import annotations

from .base import Tool, ToolContext, ToolResult


class SubmitTool(Tool):
    name = 'submit'
    description = 'Call when the task is complete. Give a short summary of what was produced.'
    parameters = {'type': 'object',
                  'properties': {'summary': {'type': 'string', 'description': 'What was done and where the outputs are'}},
                  'required': []}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:
        ctx.submitted = True
        ctx.submission = str(args.get('summary', ''))
        return ToolResult(0, 'submitted')
