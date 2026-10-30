'''run_python: execute code (or a workspace script) in a child interpreter.

Boundaries actually enforced: cwd = workspace, UTF-8 forced, timeout with process-tree kill,
path argument must stay inside the workspace, output merged and head+tail truncated by the registry.
NOT enforced: the child runs with the user's own privileges and can read/write anywhere the user can,
use the network, or spawn other processes. This is a convenience boundary, not a sandbox.
'''
from __future__ import annotations

import os
import signal
import subprocess
import uuid

from .base import Tool, ToolContext, ToolResult, resolve_in_workspace


def kill_tree(proc) -> None:
    try:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/T', '/F', '/PID', str(proc.pid)], capture_output=True, timeout=10)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_process(cmd, cwd, timeout, env=None, shell=False):
    '''Run cmd, merge stderr into stdout, kill the whole tree on timeout. Returns (rc, text, timed_out).'''
    kwargs = {}
    if os.name == 'nt':
        kwargs['creationflags'] = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
    else:
        kwargs['start_new_session'] = True
    proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, shell=shell, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kwargs)
    try:
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, out.decode('utf-8', 'replace'), False
    except subprocess.TimeoutExpired:
        kill_tree(proc)
        try:
            out, _ = proc.communicate(timeout=5)
        except Exception:
            out = b''
        return -1, (out or b'').decode('utf-8', 'replace'), True


class PythonTool(Tool):
    name = 'run_python'
    description = ('Run Python in the workspace (cwd = workspace, UTF-8). Give either code (inline source) or path '
                   '(a .py file inside the workspace). Non-zero exit codes are returned as results, not errors.')
    parameters = {'type': 'object', 'properties': {
        'code': {'type': 'string'}, 'path': {'type': 'string'},
        'timeout': {'type': 'number', 'description': 'seconds, capped by the harness limit'}},
        'required': []}

    def run(self, args, ctx: ToolContext) -> ToolResult:
        code, path = args.get('code'), args.get('path')
        if (code is None) == (path is None):
            return ToolResult(-1, '', 'provide exactly one of code or path')
        ws = ctx.workspace.resolve()
        if code is not None:
            if not isinstance(code, str):
                return ToolResult(-1, '', 'code must be a string')
            tmp = ws / '.harnessx' / 'tmp'
            tmp.mkdir(parents=True, exist_ok=True)
            script = tmp / ('run_%s.py' % uuid.uuid4().hex[:8])
            script.write_text(code, encoding='utf-8')
        else:
            script = resolve_in_workspace(ws, path)
            if not script.is_file():
                return ToolResult(1, '', 'script not found: %s' % path)
        timeout = ctx.timeout
        if args.get('timeout') is not None:
            timeout = min(float(args['timeout']), ctx.timeout)
        env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
        rc, out, timed_out = run_process([ctx.python_exe, '-X', 'utf8', str(script)], ws, timeout, env)
        if timed_out:
            return ToolResult(-1, out, 'timeout after %ss; process tree killed' % timeout)
        return ToolResult(rc, out)
