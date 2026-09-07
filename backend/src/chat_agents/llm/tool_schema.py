"""工具定义只写一份 JSON Schema——三协议的序列化差异归 ModelPort（ADR-0025）。

``llm/`` 与 ``tools/`` 都不认识任何能力模块（ADR-0007）——两者互不
import。这里用结构类型描述调用方要传什么，而不是导入 ``tools.types.ToolSpec``
这个具体类型；``ToolSpec`` 天然满足这个结构，调用方（未来的 ``agent/``）不需要
做任何转换。
"""

from collections.abc import Mapping, Sequence
from typing import Any
from typing import Protocol as TypingProtocol

from .protocol import Protocol


class ToolDescription(TypingProtocol):
    """工具的契约身份——名字、描述、入参 schema（CONTEXT.md「工具」词条）。"""

    name: str
    description: str
    parameters: dict[str, Any]


ToolLike = ToolDescription | Mapping[str, Any]


def _fields(tool: ToolLike) -> tuple[str, str, dict[str, Any]]:
    """取出三个契约字段。

    两种入参形状都要收：``ToolSpec`` 这类带属性的对象，以及 ``tools.registry``
    的 ``tool_definitions()`` 产出的 ``{name, description, parameters}`` 映射
    （它同时喂给 ``agent/versioning.py`` 做 schema 版本哈希，那边需要可 JSON
    序列化的字典，所以字典形状不能取消）。只认属性会在运行期炸
    ``'dict' object has no attribute 'name'``，而 ``Sequence[Any]`` 让类型检查
    看不到——这正是它逃过静态检查的原因。
    """

    if isinstance(tool, Mapping):
        return tool["name"], tool["description"], tool["parameters"]
    return tool.name, tool.description, tool.parameters


def to_protocol_tools(tools: Sequence[ToolLike], protocol: Protocol) -> list[dict[str, Any]]:
    """把同一份 ``parameters`` JSON Schema 序列化成协议要求的形状。"""
    fields = [_fields(tool) for tool in tools]
    if protocol == "anthropic_messages":
        return [
            {"name": name, "description": description, "input_schema": parameters}
            for name, description, parameters in fields
        ]
    if protocol == "openai_responses":
        return [
            {
                "type": "function",
                "name": name,
                "description": description,
                "parameters": parameters,
            }
            for name, description, parameters in fields
        ]
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        }
        for name, description, parameters in fields
    ]
