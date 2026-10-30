'''run_shell: run a command through Git Bash / bash (preferred) or PowerShell as a fallback on Windows.

Same boundary as run_python: cwd = workspace, timeout kills the process tree, output is merged and
truncated by the registry. It is NOT a sandbox: the command runs with the user own privileges and can
reach any path the user can. Commands are not filtered; the model is told to prefer run_python.
'''
from __future__ import annotations

import os
import shutil

from .base import Tool, ToolContext, ToolResult
from .python_tool import run_process


def find_shell():
    '''Return (name, argv_prefix). Git Bash is preferred on Windows because models think in bash.'''
    if os.name == 'nt':
        for env in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
            base = os.environ.get(env)
            if not base:
                continue
            for sub in (('Git', 'bin', 'bash.exe'), ('Programs', 'Git', 'bin', 'bash.exe')):
                p = os.path.join(base, *sub)
                if os.path.exists(p):
                    return 'git-bash', [p, '-c']
        ps = shutil.which('pwsh') or shutil.which('powershell')
        if ps:
            return 'powershell', [ps, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command']
        return 'none', []
    return 'bash', [shutil.which('bash') or '/bin/sh', '-c']


class ShellTool(Tool):
    name = 'run_shell'
    description = 'Run a shell command in the workspace (git, pip, system commands). For file/text work prefer run_python.'
    parameters = {'type': 'object', 'properties': {
        'command': {'type': 'string'},
        'timeout': {'type': 'number', 'description': 'seconds, capped by the harness limit'}},
        'required': ['command']}

    def __init__(self):
        self.shell_name, self.argv = find_shell()

    def run(self, args, ctx: ToolContext) -> ToolResult:
        cmd = args.get('command')
        if not isinstance(cmd, str) or not cmd.strip():
            return ToolResult(-1, '', 'command must be a non-empty string')
        if not self.argv:
            return ToolResult(-1, '', 'no usable shell found on this machine')
        timeout = ctx.timeout
        if args.get('timeout') is not None:
            timeout = min(float(args['timeout']), ctx.timeout)
        env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8', LANG='C.UTF-8')
        rc, out, timed_out = run_process(self.argv + [cmd], ctx.workspace.resolve(), timeout, env)
        if timed_out:
            return ToolResult(-1, out, 'timeout after %ss; process tree killed' % timeout)
        return ToolResult(rc, out)
