"""契约层：名字、描述、入参 schema——只认识模型。"""

from __future__ import annotations

from typing import Any

NAME = "web_reader"

DESCRIPTION = (
    "读取一个网页并转成 Markdown 全文返回。短文档直接给全文；"
    "长文档先给出文档结构（各章节标题与编号），可用 section 参数按编号索取指定章节的全文，"
    '例如 section="3,5" 读取第 3 节与第 5 节。'
)

PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "要读取的网页 URL。",
        },
        "section": {
            "type": "string",
            "description": (
                '逗号分隔的章节编号，例如 "3,5"。'
                "只在此前收到过该 URL 的文档结构、需要索取具体章节时传入。"
            ),
        },
    },
    "required": ["url"],
    "additionalProperties": False,
}
