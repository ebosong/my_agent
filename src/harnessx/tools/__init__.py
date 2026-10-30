from .base import ToolContext, ToolResult
from .files import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from .python_tool import PythonTool
from .registry import ToolRegistry
from .shell import ShellTool
from .skills import ListSkillsTool, LoadSkillTool
from .submit import SubmitTool


def build_registry(with_shell: bool = True, with_edit: bool = True, skill_dirs=None) -> ToolRegistry:
    reg = ToolRegistry()
    for t in (ReadFileTool(), WriteFileTool(), ListDirTool()):
        reg.register(t)
    if with_edit:
        reg.register(EditFileTool())
    reg.register(PythonTool())
    if with_shell:
        reg.register(ShellTool())
    if skill_dirs:
        reg.register(ListSkillsTool(skill_dirs))
        reg.register(LoadSkillTool(skill_dirs))
    reg.register(SubmitTool())
    return reg


__all__ = ['ToolContext', 'ToolResult', 'ToolRegistry', 'build_registry']
