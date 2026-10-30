"""Tool-layer primitives: ToolResult, ToolContext, path boundary, head+tail truncation.

Security note: the workspace check below is a path-prefix guard for the file tools and
for the `path` argument of run_python. It is NOT a sandbox: code run by run_python or
run_shell executes with the user's own privileges and can touch anything the user can.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath

MAX_OUTPUT_CHARS = 8000


class PathEscape(ValueError):
    pass


@dataclass
class ToolResult:
    returncode: int = 0
    output: str = ''
    error: str = ''
    truncated: bool = False

    def as_dict(self) -> dict:
        return {'returncode': self.returncode, 'output': self.output,
                'error': self.error, 'truncated': self.truncated}

    def to_content(self) -> str:
        # tool message content must be a string, never a dict
        return json.dumps(self.as_dict(), ensure_ascii=False)


@dataclass
class ToolContext:
    workspace: Path
    python_exe: str = sys.executable
    timeout: float = 60.0
    submitted: bool = False
    submission: str = ''
    extra: dict = field(default_factory=dict)


def resolve_in_workspace(workspace: Path, rel: str) -> Path:
    """Resolve rel inside workspace; reject absolute paths, drives and '..' escapes."""
    if not isinstance(rel, str) or not rel.strip():
        raise PathEscape('path must be a non-empty string')
    p = Path(rel)
    if p.is_absolute() or p.drive or PureWindowsPath(rel).anchor or rel.startswith(('/', '\\')):
        raise PathEscape(f'absolute paths are not allowed: {rel}')
    root = Path(workspace).resolve()
    target = (root / p).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise PathEscape(f'path escapes workspace: {rel}') from None
    return target


def truncate_head_tail(text: str, limit: int = MAX_OUTPUT_CHARS) -> tuple[str, bool]:
    """Keep head and tail (conclusions are often at the end) and say how much was dropped."""
    if len(text) <= limit:
        return text, False
    half = limit // 2
    omitted = len(text) - 2 * half
    return text[:half] + f'\n...[omitted {omitted} chars]...\n' + text[-half:], True


class Tool:
    name = ''
    description = ''
    parameters: dict = {'type': 'object', 'properties': {}}

    def schema(self) -> dict:
        return {'type': 'function', 'function': {
            'name': self.name, 'description': self.description, 'parameters': self.parameters}}

    def run(self, args: dict, ctx: ToolContext) -> ToolResult:  # pragma: no cover
        raise NotImplementedError
