'''Skills: on-demand domain knowledge.

A skill is a directory containing SKILL.md with a small front matter (name, description) and a markdown body.
Only names and one-line descriptions go into the system prompt (index_text); the body is loaded by the model on demand
with load_skill, so unused skills cost almost no context. Every load is an ordinary tool_call/tool_result pair in the
JSONL log, so skill use is traceable and replayed correctly on resume.

Design idea (progressive disclosure: index first, body on demand) is the same as the skill mechanism documented for
Claude and coding agents; this implementation is written from scratch for this project.
'''
from __future__ import annotations

from pathlib import Path

from .base import Tool, ToolContext, ToolResult

MAX_SKILL_CHARS = 12000


def parse_skill(path):
    text = Path(path).read_text(encoding='utf-8-sig').replace('\r\n', '\n')
    meta, body = {}, text
    if text.startswith('---\n'):
        end = text.find('\n---', 4)
        if end != -1:
            for line in text[4:end].splitlines():
                if ':' in line:
                    k, v = line.split(':', 1)
                    meta[k.strip()] = v.strip()
            body = text[end + 4:].lstrip('\n')
    return meta, body


def discover(dirs) -> dict:
    '''Earlier directories win on duplicate names (workspace skills override repo skills).'''
    found = {}
    for d in dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for p in sorted(d.glob('*/SKILL.md')):
            try:
                meta, _ = parse_skill(p)
            except Exception:
                continue
            name = meta.get('name') or p.parent.name
            if name not in found:
                found[name] = {'name': name, 'description': meta.get('description', ''), 'path': p}
    return found


def index_text(skills: dict) -> str:
    if not skills:
        return ''
    lines = ['Available skills (call load_skill with the name to read the full instructions before doing a task they cover):']
    lines += ['- %s: %s' % (s['name'], s['description']) for s in skills.values()]
    return '\n'.join(lines)


class ListSkillsTool(Tool):
    name = 'list_skills'
    description = 'List the available skills (name and one-line description).'
    parameters = {'type': 'object', 'properties': {}, 'required': []}

    def __init__(self, dirs):
        self.dirs = list(dirs)

    def run(self, args, ctx: ToolContext) -> ToolResult:
        sk = discover(self.dirs)
        return ToolResult(0, index_text(sk) or '(no skills available)')


class LoadSkillTool(Tool):
    name = 'load_skill'
    description = 'Load the full instructions of one skill by name. Use it before a task that a listed skill covers.'
    parameters = {'type': 'object', 'properties': {'name': {'type': 'string'}}, 'required': ['name']}

    def __init__(self, dirs):
        self.dirs = list(dirs)

    def run(self, args, ctx: ToolContext) -> ToolResult:
        sk = discover(self.dirs)
        name = args.get('name')
        if name not in sk:
            return ToolResult(1, '', 'unknown skill: %s. available: %s' % (name, ', '.join(sk) or '(none)'))
        _, body = parse_skill(sk[name]['path'])
        cut = len(body) > MAX_SKILL_CHARS
        return ToolResult(0, body[:MAX_SKILL_CHARS], '', cut)
