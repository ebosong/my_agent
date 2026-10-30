'''File tools: read_file, write_file, list_dir and exact edit_file.

edit_file design (see docs; idea of matching every edit against the ORIGINAL file and
rejecting ambiguity is borrowed from pi's edit.ts, re-implemented here in Python):
  * every old_text must occur exactly once in the original file (0 or >1 -> error, file untouched)
  * edits must not overlap; all edits are validated before anything is written
  * BOM and CRLF/LF line endings are preserved
  * the write is atomic (temp file + os.replace)
'''
from __future__ import annotations

import difflib
import os
import tempfile

from .base import Tool, ToolContext, ToolResult, resolve_in_workspace

SKIP_DIRS = {'.git', '.harnessx', '__pycache__', '.venv', 'node_modules'}


class EditError(ValueError):
    pass


def read_text_info(p):
    raw = p.read_bytes().decode('utf-8')
    bom = raw.startswith('﻿')
    if bom:
        raw = raw[1:]
    eol = '\r\n' if '\r\n' in raw else '\n'
    return bom, eol, raw.replace('\r\n', '\n')


def apply_edits(content: str, edits: list) -> str:
    '''content must be LF-normalised. Returns new content or raises EditError.'''
    if not isinstance(edits, list) or not edits:
        raise EditError('edits must be a non-empty list of {old_text, new_text}')
    spans = []
    for i, e in enumerate(edits):
        if not isinstance(e, dict) or not isinstance(e.get('old_text'), str) or not isinstance(e.get('new_text'), str):
            raise EditError('edit %d: old_text and new_text must both be strings' % i)
        old = e['old_text'].replace('\r\n', '\n')
        new = e['new_text'].replace('\r\n', '\n')
        if old == '':
            raise EditError('edit %d: old_text must not be empty' % i)
        n = content.count(old)
        if n == 0:
            raise EditError('edit %d: old_text not found (it must match the file exactly, including whitespace)' % i)
        if n > 1:
            raise EditError('edit %d: old_text matches %d places; include more surrounding context so it is unique' % (i, n))
        s = content.index(old)
        spans.append((s, s + len(old), new))
    spans.sort()
    for a, b in zip(spans, spans[1:]):
        if a[1] > b[0]:
            raise EditError('edits overlap; merge them into one edit')
    out, pos = [], 0
    for s, e, new in spans:
        out.append(content[pos:s])
        out.append(new)
        pos = e
    out.append(content[pos:])
    result = ''.join(out)
    if result == content:
        raise EditError('edits produce no change')
    return result


def atomic_write(p, data: bytes) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix='.hx_', suffix='.tmp')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
        os.replace(tmp, p)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


class ReadFileTool(Tool):
    name = 'read_file'
    description = 'Read a UTF-8 text file inside the workspace. Optional offset (1-based line) and limit (lines).'
    parameters = {'type': 'object', 'properties': {
        'path': {'type': 'string'}, 'offset': {'type': 'integer'}, 'limit': {'type': 'integer'}},
        'required': ['path']}

    def run(self, args, ctx: ToolContext) -> ToolResult:
        p = resolve_in_workspace(ctx.workspace, args.get('path'))
        if not p.is_file():
            return ToolResult(1, '', 'not a file: %s' % args.get('path'))
        lines = p.read_bytes().decode('utf-8', 'replace').splitlines(keepends=True)
        off = max(int(args.get('offset') or 1), 1)
        lim = int(args.get('limit') or 2000)
        part = lines[off - 1: off - 1 + lim]
        text = ''.join(part)
        if off > 1 or off - 1 + lim < len(lines):
            text += '\n[showing lines %d-%d of %d]' % (off, off - 1 + len(part), len(lines))
        return ToolResult(0, text)


class WriteFileTool(Tool):
    name = 'write_file'
    description = 'Create or fully overwrite a UTF-8 file in the workspace. For small changes to an existing file prefer edit_file.'
    parameters = {'type': 'object', 'properties': {
        'path': {'type': 'string'}, 'content': {'type': 'string'}}, 'required': ['path', 'content']}

    def run(self, args, ctx: ToolContext) -> ToolResult:
        p = resolve_in_workspace(ctx.workspace, args.get('path'))
        content = args.get('content')
        if not isinstance(content, str):
            return ToolResult(-1, '', 'content must be a string')
        atomic_write(p, content.encode('utf-8'))
        return ToolResult(0, 'wrote %s (%d bytes, %d lines)' % (args['path'], len(content.encode('utf-8')), content.count('\n') + 1))


class ListDirTool(Tool):
    name = 'list_dir'
    description = 'List a directory in the workspace (default: workspace root).'
    parameters = {'type': 'object', 'properties': {'path': {'type': 'string'}}, 'required': []}

    def run(self, args, ctx: ToolContext) -> ToolResult:
        p = resolve_in_workspace(ctx.workspace, args.get('path') or '.')
        if not p.is_dir():
            return ToolResult(1, '', 'not a directory: %s' % args.get('path'))
        rows = []
        for c in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
            if c.name in SKIP_DIRS:
                continue
            rows.append(c.name + '/' if c.is_dir() else '%s  (%d bytes)' % (c.name, c.stat().st_size))
        return ToolResult(0, '\n'.join(rows) or '(empty)')


class EditFileTool(Tool):
    name = 'edit_file'
    description = ('Exact text replacement in an existing file. Each old_text must match exactly one place in the '
                   'ORIGINAL file (include enough context to be unique). Several non-overlapping edits can be '
                   'sent in one call. BOM and line endings are preserved. Fails without changing the file if any '
                   'old_text is missing or ambiguous.')
    parameters = {'type': 'object', 'properties': {
        'path': {'type': 'string'},
        'edits': {'type': 'array', 'items': {'type': 'object', 'properties': {
            'old_text': {'type': 'string'}, 'new_text': {'type': 'string'}},
            'required': ['old_text', 'new_text']}},
        'old_text': {'type': 'string', 'description': 'shortcut for a single edit'},
        'new_text': {'type': 'string'}},
        'required': ['path']}

    def run(self, args, ctx: ToolContext) -> ToolResult:
        p = resolve_in_workspace(ctx.workspace, args.get('path'))
        if not p.is_file():
            return ToolResult(1, '', 'file does not exist: %s (use write_file to create it)' % args.get('path'))
        edits = args.get('edits')
        if edits is None and 'old_text' in args:
            edits = [{'old_text': args.get('old_text'), 'new_text': args.get('new_text')}]
        bom, eol, content = read_text_info(p)
        try:
            new = apply_edits(content, edits)
        except EditError as e:
            return ToolResult(1, '', 'edit rejected, file unchanged: %s' % e)
        data = ('﻿' if bom else '') + (new.replace('\n', eol) if eol != '\n' else new)
        atomic_write(p, data.encode('utf-8'))
        diff = list(difflib.unified_diff(content.splitlines(), new.splitlines(), 'a/' + args['path'], 'b/' + args['path'], lineterm='', n=1))
        added = sum(1 for d in diff if d.startswith('+') and not d.startswith('+++'))
        removed = sum(1 for d in diff if d.startswith('-') and not d.startswith('---'))
        text = 'edited %s: %d block(s), +%d -%d lines\n%s' % (args['path'], len(edits), added, removed, '\n'.join(diff)[:3000])
        return ToolResult(0, text)
