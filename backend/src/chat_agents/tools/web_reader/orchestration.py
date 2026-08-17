"""编排层：规范化、切章节、数 token、判阈值、组装返回。

纯函数，没有一处 IO，谁都不认识——不认识 Jina，不认识执行器。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ...token_estimation import count_tokens, estimate_tokens
from ..types import ToolResult

TOKEN_THRESHOLD = 8_000  # 拍的，不是算的——待评测用章节选错率与答案完整率校准（ADR-0005）
FALLBACK_TRUNCATE_CHARS = 6_000

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)\s*$", re.MULTILINE)

__all__ = [
    "FALLBACK_TRUNCATE_CHARS",
    "TOKEN_THRESHOLD",
    "ReaderDocument",
    "Section",
    "assemble_result",
    "build_document",
    "count_tokens",
    "normalize_markdown",
    "parse_section_indices",
    "parse_sections",
    "render_full",
    "render_sections",
    "render_structure",
    "render_truncated",
]


def normalize_markdown(raw: str) -> str:
    """吸收供应商间的 Markdown 差异，在进编排层之前统一形状（ADR-0004 后果段）。"""
    lines = [line.rstrip() for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    normalized = "\n".join(lines).strip("\n")
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized


@dataclass(frozen=True, slots=True)
class Section:
    index: int
    level: int
    title: str
    content: str  # 含标题行的该节全文
    token_count: int


@dataclass(frozen=True, slots=True)
class ReaderDocument:
    url: str
    markdown: str
    token_count: int
    sections: list[Section] = field(default_factory=list)


def parse_sections(markdown: str, *, calibration: float = 1.0) -> list[Section]:
    """按 Markdown 标题切章节，编号从 1 开始，只做一级（ADR-0005：不做多级路由）。"""
    headings = list(_HEADING_RE.finditer(markdown))
    if not headings:
        return []

    sections: list[Section] = []
    for i, match in enumerate(headings):
        start = match.start()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(markdown)
        content = markdown[start:end].rstrip()
        title = match.group(2)
        level = len(match.group(1))
        sections.append(
            Section(
                index=i + 1,
                level=level,
                title=title,
                content=content,
                token_count=estimate_tokens(content, calibration=calibration),
            )
        )
    return sections


def build_document(url: str, raw_markdown: str, *, calibration: float = 1.0) -> ReaderDocument:
    """`calibration` 是该次运行主模型的校准系数，由调用方（工具执行上下文）
    传入——分节阈值判断要用校准后的估算，编排层本身不查询任何模型（ADR-0020）。
    """
    markdown = normalize_markdown(raw_markdown)
    return ReaderDocument(
        url=url,
        markdown=markdown,
        token_count=estimate_tokens(markdown, calibration=calibration),
        sections=parse_sections(markdown, calibration=calibration),
    )


def parse_section_indices(section_arg: str) -> list[int]:
    indices: list[int] = []
    for piece in section_arg.split(","):
        piece = piece.strip()
        if piece.isdigit():
            indices.append(int(piece))
    return indices


def _structure_summary(sections: list[Section]) -> list[dict]:
    return [
        {"index": s.index, "title": s.title, "level": s.level, "token_count": s.token_count}
        for s in sections
    ]


def render_full(doc: ReaderDocument) -> str:
    return doc.markdown


def render_structure(doc: ReaderDocument) -> str:
    lines = [
        f"{doc.url} 全文约 {doc.token_count} token，超过单次返回阈值，分为 {len(doc.sections)} 节：",
    ]
    for s in doc.sections:
        lines.append(f"{s.index}. {s.title}（约 {s.token_count} token）")
    lines.append("")
    lines.append('如需具体章节，调用 web_reader(url, section="3,5") 这样的编号列表。')
    lines.append("")
    lines.append(f"第 {doc.sections[0].index} 节全文：")
    lines.append(doc.sections[0].content)
    return "\n".join(lines)


def render_sections(doc: ReaderDocument, selected: list[Section]) -> str:
    if not selected:
        available = ", ".join(str(s.index) for s in doc.sections)
        return f"{doc.url} 没有匹配到请求的章节编号，可用编号为：{available}"
    parts = [f"{doc.url} 第 {s.index} 节「{s.title}」：\n{s.content}" for s in selected]
    return "\n\n".join(parts)


def render_truncated(doc: ReaderDocument) -> str:
    full_len = len(doc.markdown)
    truncated = doc.markdown[:FALLBACK_TRUNCATE_CHARS]
    return f"[内容已截断：全文约 {full_len} 字符，以下为前 {len(truncated)} 字符]\n\n{truncated}"


def assemble_result(
    doc: ReaderDocument,
    section_arg: str | None,
    *,
    threshold_tokens: int = TOKEN_THRESHOLD,
) -> ToolResult:
    structured: dict = {
        "url": doc.url,
        "token_count": doc.token_count,
        "section_count": len(doc.sections),
        "sections": _structure_summary(doc.sections),
    }

    if section_arg:
        indices = set(parse_section_indices(section_arg))
        selected = [s for s in doc.sections if s.index in indices]
        structured["mode"] = "sections"
        structured["requested_sections"] = sorted(indices)
        return ToolResult(structured=structured, model_text=render_sections(doc, selected))

    if doc.token_count <= threshold_tokens:
        structured["mode"] = "full"
        structured["truncated"] = False
        return ToolResult(structured=structured, model_text=render_full(doc))

    if doc.sections:
        structured["mode"] = "structure"
        structured["truncated"] = False
        return ToolResult(structured=structured, model_text=render_structure(doc))

    # 兜底路径：没有标题层级的长网页，如实标注截断（ADR-0005）
    structured["mode"] = "truncated"
    structured["truncated"] = True
    structured["truncated_chars"] = FALLBACK_TRUNCATE_CHARS
    return ToolResult(structured=structured, model_text=render_truncated(doc))
