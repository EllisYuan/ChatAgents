"""模型输入中的观察掩蔽（ADR-0019）。

掩蔽只修改投影，不修改消息表中的完整内容。最近固定数量的工具调用/结果对
保留正文，更早的结果换成可行动的来源指代；工具调用及其入参始终原样保留。
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ..llm.message import ModelMessage, ToolCallBlock, ToolResultBlock

# 首版取值是评测自变量，不随努力档位变化。
OBSERVATION_KEEP = 2
# 兼容领域命名；两者必须始终是同一个全局窗口。
RETENTION_WINDOW = OBSERVATION_KEEP
MASKED_OBSERVATION_IDS_KEY = "masked_observation_ids"

_URL_RE = re.compile(r"https?://[^\s<>\]\[)\}>,]+")
_SEARCH_TITLE_RE = re.compile(r"^\s*(?:\d+[.)]|[-*])\s*(.+?)\s*$")
_SECTION_TITLE_RE = re.compile(r"第\s*\d+\s*节[「『](.+?)[」』]")
_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")


@dataclass(frozen=True, slots=True)
class SourceReference:
    """被掩蔽结果中仍可供模型重新获取的来源。"""

    title: str
    url: str


@dataclass(frozen=True, slots=True)
class MaskedObservation:
    """一次被掩蔽的工具调用/结果对。"""

    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    sources: tuple[SourceReference, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "sources": [{"title": source.title, "url": source.url} for source in self.sources],
        }


@dataclass(frozen=True, slots=True)
class MaskingProjection:
    """投影后的消息及本次输入发生的掩蔽事实。"""

    messages: list[ModelMessage]
    masked_observations: tuple[MaskedObservation, ...]

    @property
    def attributes(self) -> dict[str, Any]:
        return {
            MASKED_OBSERVATION_IDS_KEY: [
                observation.tool_call_id for observation in self.masked_observations
            ],
            "masked_observations": [
                observation.as_dict() for observation in self.masked_observations
            ],
        }


def _clean_url(value: str) -> str:
    return value.rstrip(".,;:!?\"'")


def _source_references(call: ToolCallBlock, result: ToolResultBlock) -> tuple[SourceReference, ...]:
    """从现有工具结果文本提取标题与 URL，不对正文做摘要。"""

    lines = result.content.splitlines()
    references: list[SourceReference] = []
    pending_title: str | None = None
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        heading = _HEADING_RE.match(stripped)
        numbered = _SEARCH_TITLE_RE.match(stripped)
        section = _SECTION_TITLE_RE.search(stripped)
        if heading is not None:
            pending_title = heading.group(1).strip()
            continue
        if numbered is not None and "http" not in stripped:
            pending_title = numbered.group(1).strip()
            continue
        url_match = _URL_RE.search(stripped)
        if url_match is None:
            continue
        url = _clean_url(url_match.group(0))
        title = (
            pending_title
            or (section.group(1).strip() if section is not None else "")
            or str(call.arguments.get("title", ""))
            or url
        )
        references.append(SourceReference(title=title, url=url))
        pending_title = None

    argument_url = call.arguments.get("url")
    if isinstance(argument_url, str) and argument_url:
        url = _clean_url(argument_url)
        if not any(source.url == url for source in references):
            references.append(SourceReference(title=url, url=url))
    return tuple(references)


def _placeholder(call: ToolCallBlock, result: ToolResultBlock) -> tuple[str, MaskedObservation]:
    observation = MaskedObservation(
        tool_call_id=call.id,
        tool_name=call.name,
        arguments=dict(call.arguments),
        sources=_source_references(call, result),
    )
    arguments = json.dumps(observation.arguments, ensure_ascii=False, sort_keys=True)
    lines = [
        "[观察已掩蔽]",
        f"工具名：{observation.tool_name}",
        f"入参：{arguments}",
        "来源：",
    ]
    if observation.sources:
        lines.extend(f"- 标题：{source.title}；URL：{source.url}" for source in observation.sources)
    else:
        lines.append("- 无来源 URL")
    return "\n".join(lines), observation


def mask_tool_observations(
    messages: Sequence[ModelMessage], *, retention_window: int = RETENTION_WINDOW
) -> MaskingProjection:
    """掩蔽较早工具结果，窗口按工具调用/结果对全局滑动。"""

    if retention_window < 0:
        raise ValueError("retention_window must be non-negative")

    pairs: list[tuple[int, int, ToolCallBlock, ToolResultBlock]] = []
    for message_index, message in enumerate(messages):
        if message.role != "assistant":
            continue
        calls = [block for block in message.content if isinstance(block, ToolCallBlock)]
        if not calls or message_index + 1 >= len(messages):
            continue
        result_message = messages[message_index + 1]
        if result_message.role != "tool":
            continue
        results = {
            block.tool_call_id: block
            for block in result_message.content
            if isinstance(block, ToolResultBlock)
        }
        for call in calls:
            result = results.get(call.id)
            if result is not None:
                result_index = next(
                    index for index, block in enumerate(result_message.content) if block is result
                )
                pairs.append((message_index + 1, result_index, call, result))

    keep_from = max(0, len(pairs) - retention_window)
    masked = pairs[:keep_from]
    masked_by_message: dict[int, dict[int, tuple[str, MaskedObservation]]] = {}
    for message_index, block_index, call, result in masked:
        placeholder, observation = _placeholder(call, result)
        masked_by_message.setdefault(message_index, {})[block_index] = (placeholder, observation)

    projected: list[ModelMessage] = []
    observations: list[MaskedObservation] = []
    for message_index, message in enumerate(messages):
        replacements = masked_by_message.get(message_index)
        if not replacements:
            projected.append(message)
            continue
        content = list(message.content)
        for block_index, (placeholder, observation) in replacements.items():
            block = content[block_index]
            if isinstance(block, ToolResultBlock):
                content[block_index] = ToolResultBlock(
                    tool_call_id=block.tool_call_id,
                    content=placeholder,
                    is_error=block.is_error,
                )
                observations.append(observation)
        projected.append(ModelMessage(role=message.role, content=tuple(content)))

    return MaskingProjection(messages=projected, masked_observations=tuple(observations))
