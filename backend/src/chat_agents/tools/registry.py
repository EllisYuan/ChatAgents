"""工具注册表：目前锁死两个，``web_search`` 与 ``web_reader``。"""

from __future__ import annotations

from typing import Any

from .types import ToolSpec
from .web_reader import SPEC as WEB_READER_SPEC
from .web_search import SPEC as WEB_SEARCH_SPEC

TOOL_SPECS: dict[str, ToolSpec] = {
    WEB_SEARCH_SPEC.name: WEB_SEARCH_SPEC,
    WEB_READER_SPEC.name: WEB_READER_SPEC,
}


def get_tool_spec(name: str) -> ToolSpec | None:
    return TOOL_SPECS.get(name)


def tool_definitions() -> list[dict[str, Any]]:
    """工具定义只写一份：``{名字, 描述, JSON Schema}``，协议序列化交给 ``llm/``。"""
    return [
        {"name": spec.name, "description": spec.description, "parameters": spec.parameters}
        for spec in TOOL_SPECS.values()
    ]
