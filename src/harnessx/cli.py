'''Command line: run / resume / doctor / trace.'''
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path

from . import __version__
from .agent import Agent
from .config import Config
from .context import Compactor
from .events import EventLog, format_trace, read_events
from .model import ModelError, OpenAICompatModel
from .session import restore
from .tools import ToolContext, build_registry
from .prompts import SYSTEM_PROMPT
from .tools.shell import ShellTool
from .tools.skills import discover, index_text

ROOT = Path(__file__).resolve().parents[2]


def _utf8() -> None:
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass


def _config(args, ws: Path) -> Config:
    return Config.load(ROOT, ws, model=getattr(args, 'model', None), max_steps=getattr(args, 'max_steps', None),
                       max_cost=getattr(args, 'max_cost', None), max_seconds=getattr(args, 'max_seconds', None),
                       context_limit=getattr(args, 'context_limit', None), tool_timeout=getattr(args, 'tool_timeout', None),
                       summarizer=getattr(args, 'summarizer', None))


def _make_agent(cfg: Config, ws: Path, log: EventLog, no_edit: bool = False, only=None, no_skills: bool = False) -> Agent:
    model = OpenAICompatModel(cfg.base_url, cfg.model, cfg.api_key, cfg.request_timeout)
    compactor = None
    if cfg.context_limit > 0:
        compactor = Compactor(cfg.context_limit, cfg.keep_turns, model if cfg.summarizer == 'llm' else None)
    # workspace skills override repo skills with the same name
    skill_dirs = [] if no_skills else [ws / 'skills', ROOT / 'skills']
    reg = build_registry(with_edit=not no_edit, skill_dirs=skill_dirs)
    if only:
        reg = reg.subset([n.strip() for n in only.split(',') if n.strip()])
    system = SYSTEM_PROMPT
    if 'load_skill' in reg.names():
        idx = index_text(discover(skill_dirs))
        if idx:
            system = SYSTEM_PROMPT + '\n' + idx + '\n'
    return Agent(model, reg, ToolContext(workspace=ws, timeout=cfg.tool_timeout), log, system=system,
                 max_steps=cfg.max_steps, max_cost=cfg.max_cost, max_seconds=cfg.max_seconds,
                 price_in=cfg.price_in, price_out=cfg.price_out, compactor=compactor)


def _finish(res: dict, path: Path) -> int:
    print(json.dumps(res, ensure_ascii=False))
    print('session: %s' % path)
    return 0 if res['exit_status'] in ('Submitted', 'FinalAnswer') else 1


def cmd_run(args) -> int:
    ws = Path(args.workspace).resolve()
    ws.mkdir(parents=True, exist_ok=True)
    cfg = _config(args, ws)
    if not cfg.api_key:
        print('no API key: set HARNESSX_API_KEY in .env (see .env.example)', file=sys.stderr)
        return 2
    path = ws / '.harnessx' / 'sessions' / ('session_%s.jsonl' % time.strftime('%Y%m%d_%H%M%S'))
    agent = _make_agent(cfg, ws, EventLog(path), args.no_edit, args.tools, args.no_skills)
    return _finish(agent.run(args.task), path)


def cmd_resume(args) -> int:
    path = Path(args.session).resolve()
    if not path.is_file():
        print('session file not found: %s' % path, file=sys.stderr)
        return 2
    messages, last_id, info = restore(path)
    if not messages:
        print('nothing to resume: no message events in %s' % path, file=sys.stderr)
        return 2
    start = next((e for e in read_events(path) if e.get('type') == 'run_start'), None)
    ws = Path(args.workspace or (start or {}).get('payload', {}).get('workspace') or '.').resolve()
    cfg = _config(args, ws)
    if not cfg.api_key:
        print('no API key: set HARNESSX_API_KEY in .env', file=sys.stderr)
        return 2
    log = EventLog(path, last_id)
    log.emit('resume', info)
    print('resuming: %s' % json.dumps(info, ensure_ascii=False))
    agent = _make_agent(cfg, ws, log, args.no_edit, args.tools, args.no_skills)
    return _finish(agent.run(args.task or info['task'], messages=messages), path)


def cmd_trace(args) -> int:
    print(format_trace(read_events(args.session)))
    return 0


def cmd_doctor(args) -> int:
    ws = Path(args.workspace).resolve()
    ws.mkdir(parents=True, exist_ok=True)
    cfg = _config(args, ws)
    ok = True
    print('harnessx %s' % __version__)
    print('os: %s %s' % (platform.system(), platform.release()))
    print('python: %s' % sys.version.split()[0])
    print('sys.executable: %s' % sys.executable)
    print('workspace: %s' % ws)
    print('base_url: %s' % cfg.base_url)
    print('model: %s' % cfg.model)
    print('api_key: %s' % (cfg.redacted()['api_key'] or '(empty)'))
    if sys.version_info < (3, 10):
        print('python check: FAIL (need 3.10+)')
        ok = False
    sh = ShellTool()
    print('shell: %s %s' % (sh.shell_name, sh.argv[:1]))
    res = sh.run({'command': 'echo shell-ok'}, ToolContext(workspace=ws, timeout=20))
    good = res.returncode == 0 and 'shell-ok' in res.output
    print('shell test: %s' % ('pass' if good else 'FAIL rc=%s %s' % (res.returncode, res.error or res.output[:100])))
    ok = ok and good
    if args.no_model:
        print('tool_call test: skipped (--no-model)')
    elif not cfg.api_key:
        print('tool_call test: FAIL (no API key)')
        ok = False
    else:
        tools = [{'type': 'function', 'function': {'name': 'echo', 'description': 'echo text', 'parameters': {
            'type': 'object', 'properties': {'text': {'type': 'string'}}, 'required': ['text']}}}]
        try:
            r = OpenAICompatModel(cfg.base_url, cfg.model, cfg.api_key, cfg.request_timeout, retries=1).chat(
                [{'role': 'user', 'content': 'Call the echo tool with text hi.'}], tools)
            good = bool(r['tool_calls']) and r['tool_calls'][0]['name'] == 'echo'
            print('tool_call test: %s usage=%s' % ('pass' if good else 'FAIL (model did not call the tool)', r['usage']))
            ok = ok and good
        except ModelError as e:
            print('tool_call test: FAIL %s' % e)
            ok = False
    print('RESULT: %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='harnessx', description='A small evidence-first agent harness')
    sub = p.add_subparsers(dest='cmd', required=True)

    def limits(sp):
        sp.add_argument('--model')
        sp.add_argument('--max-steps', type=int)
        sp.add_argument('--max-cost', type=float)
        sp.add_argument('--max-seconds', type=float)
        sp.add_argument('--tool-timeout', type=float)
        sp.add_argument('--context-limit', type=int, help='estimated-token threshold that triggers compaction (0 = off)')
        sp.add_argument('--summarizer', choices=['rule', 'llm'], help='compaction summary: deterministic rule (free) or llm (costs tokens)')
        sp.add_argument('--no-edit', action='store_true', help='do not expose edit_file')
        sp.add_argument('--no-skills', action='store_true', help='do not expose skills')
        sp.add_argument('--tools', help='comma-separated whitelist of tool names (submit is always kept)')

    r = sub.add_parser('run', help='run a task')
    r.add_argument('task')
    r.add_argument('--workspace', default='.')
    limits(r)
    r.set_defaults(fn=cmd_run)

    rs = sub.add_parser('resume', help='continue a session from its .jsonl file')
    rs.add_argument('session')
    rs.add_argument('--task', help='extra instruction; default: the original task')
    rs.add_argument('--workspace')
    limits(rs)
    rs.set_defaults(fn=cmd_resume)

    t = sub.add_parser('trace', help='print a human-readable trace of a .jsonl session')
    t.add_argument('session')
    t.set_defaults(fn=cmd_trace)

    d = sub.add_parser('doctor', help='check environment, shell and model endpoint')
    d.add_argument('--workspace', default='.')
    d.add_argument('--report', action='store_true', help='compatibility flag; diagnostic output is always printed')
    d.add_argument('--no-model', action='store_true')
    d.add_argument('--model')
    d.set_defaults(fn=cmd_doctor)
    return p


def main(argv=None) -> int:
    _utf8()
    args = build_parser().parse_args(argv)
    return args.fn(args)
