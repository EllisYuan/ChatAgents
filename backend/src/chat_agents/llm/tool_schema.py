"""工具定义只写一份 JSON Schema——三协议的序列化差异归 ModelPort（ADR-0025）。

``llm/`` 对项目其余部分零依赖（ADR-0007），``tools/`` 同样零依赖——两者互不
import。这里用结构类型描述调用方要传什么，而不是导入 ``tools.types.ToolSpec``
这个具体类型；``ToolSpec`` 天然满足这个结构，调用方（未来的 ``agent/``）不需要
做任何转换。
"""

from collections.abc import Sequence
from typing import Any
from typing import Protocol as TypingProtocol

from .protocol import Protocol


class ToolDescription(TypingProtocol):
    """工具的契约身份——名字、描述、入参 schema（CONTEXT.md「工具」词条）。"""

    name: str
    description: str
    parameters: dict[str, Any]


def to_protocol_tools(tools: Sequence[ToolDescription], protocol: Protocol) -> list[dict[str, Any]]:
    """把同一份 ``parameters`` JSON Schema 序列化成协议要求的形状。"""
    if protocol == "anthropic_messages":
        return [
            {"name": tool.name, "description": tool.description, "input_schema": tool.parameters}
            for tool in tools
        ]
    if protocol == "openai_responses":
        return [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in tools
        ]
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
        for tool in tools
    ]
