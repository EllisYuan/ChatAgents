"""契约层：名字、描述、入参 schema——只认识模型。"""

from __future__ import annotations

from typing import Any

NAME = "web_search"

DESCRIPTION = (
    "在公开互联网上搜索与查询相关的网页，返回按相关性排序的结果列表"
    "（标题、URL、内容片段）。用于获取时效性信息或本地知识库中没有的事实。"
)

PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "搜索查询词，应尽量具体、贴近信息需求本身。",
        },
        "max_results": {
            "type": "integer",
            "minimum": 1,
            "maximum": 10,
            "description": "返回结果条数，默认 5。",
        },
    },
    "required": ["query"],
    "additionalProperties": False,
}
