"""工具层：两个工具，三层切缝，一个执行器（ADR-0004）。

``tools/`` 本身零依赖——不认识 ``agent/``、不认识数据库，只产出
``{名字, 描述, JSON Schema}`` 与一个可调用的处理函数。
"""

from .registry import TOOL_SPECS, get_tool_spec, tool_definitions
from .types import ToolExecutionContext, ToolExternalFailure, ToolResult, ToolSpec

__all__ = [
    "TOOL_SPECS",
    "ToolExecutionContext",
    "ToolExternalFailure",
    "ToolResult",
    "ToolSpec",
    "get_tool_spec",
    "tool_definitions",
]
