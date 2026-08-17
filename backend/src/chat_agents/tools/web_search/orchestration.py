"""编排层：组装 :class:`ToolResult`。纯函数，不做 IO，谁都不认识——``SearchHit``
是编排层自己的领域类型，端口层把供应商响应映射成它，而不是反过来。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..types import ToolResult


@dataclass(frozen=True, slots=True)
class SearchHit:
    title: str
    url: str
    content: str
    score: float | None


def build_structured(query: str, hits: list[SearchHit]) -> dict:
    return {
        "query": query,
        "result_count": len(hits),
        "results": [
            {
                "title": hit.title,
                "url": hit.url,
                "content": hit.content,
                "score": hit.score,
            }
            for hit in hits
        ],
    }


def render_for_model(query: str, hits: list[SearchHit]) -> str:
    if not hits:
        return f'搜索 "{query}" 没有找到结果。'

    lines = [f'搜索 "{query}" 的结果：']
    for i, hit in enumerate(hits, start=1):
        lines.append(f"{i}. {hit.title}\n   {hit.url}\n   {hit.content}")
    return "\n".join(lines)


def assemble_result(query: str, hits: list[SearchHit]) -> ToolResult:
    return ToolResult(
        structured=build_structured(query, hits),
        model_text=render_for_model(query, hits),
    )
