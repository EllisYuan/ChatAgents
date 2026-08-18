"""Conversation DTOs and the JSON representation used by ``app.message``.

The ORM rows remain declared in :mod:`chat_agents.db.app`; this module owns the
conversation capability's boundary types and the protocol-neutral content
encoding used by that table.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ..db.app import Message as MessageRow
from ..db.app import Session as SessionRow
from ..llm.message import (
    ContentBlock,
    ModelMessage,
    OpaqueBlock,
    Role,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)
from ..llm.protocol import PROTOCOLS, Protocol


class SessionSummary(BaseModel):
    """Fields used by the public session list."""

    id: UUID
    title: str | None
    created_at: datetime
    updated_at: datetime
    message_count: int


class SessionView(BaseModel):
    """Business fields used by a session detail response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str | None
    created_at: datetime
    updated_at: datetime
    pruned_run_count: int


class MessageView(BaseModel):
    """A stored message, without observability data."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    seq: int
    role: str
    content: list[dict[str, Any]]
    created_at: datetime


class SessionDetail(SessionView):
    messages: list[MessageView] = Field(default_factory=list)


class RenameSessionRequest(BaseModel):
    title: str | None = None


class UserMessageRequest(BaseModel):
    id: UUID
    content: str


def _encode_block(block: ContentBlock) -> dict[str, Any] | None:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ToolCallBlock):
        return {
            "type": "tool_call",
            "id": block.id,
            "name": block.name,
            "arguments": block.arguments,
        }
    if isinstance(block, ToolResultBlock):
        return {
            "type": "tool_result",
            "tool_call_id": block.tool_call_id,
            "content": block.content,
            "is_error": block.is_error,
        }
    if isinstance(block, OpaqueBlock):
        return None
    raise TypeError(f"Unsupported content block: {type(block)!r}")


def encode_content(message: ModelMessage) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Encode a domain message into table content and opaque payload blocks."""

    content: list[dict[str, Any]] = []
    opaque: list[dict[str, Any]] = []
    for block in message.content:
        encoded = _encode_block(block)
        if encoded is not None:
            content.append(encoded)
        elif isinstance(block, OpaqueBlock):
            entry: dict[str, Any] = {"protocol": block.protocol, "data": block.data}
            # 只有 opaque block 出现在普通内容之后时才记录位置；前置块继续使用
            # 旧的紧凑形状，兼容已有消息行。
            if content:
                entry["content_index"] = len(content)
            opaque.append(entry)
    return content, opaque


def _decode_block(raw: Mapping[str, Any]) -> ContentBlock:
    kind = raw.get("type")
    if kind == "text":
        return TextBlock(text=str(raw.get("text", "")))
    if kind in {"tool_call", "tool_use"}:
        return ToolCallBlock(
            id=str(raw["id"]),
            name=str(raw["name"]),
            arguments=dict(raw.get("arguments", raw.get("input", {}))),
        )
    if kind == "tool_result":
        return ToolResultBlock(
            tool_call_id=str(raw["tool_call_id"]),
            content=str(raw.get("content", "")),
            is_error=bool(raw.get("is_error", False)),
        )
    if kind == "opaque":
        return OpaqueBlock(protocol=raw["protocol"], data=dict(raw["data"]))
    raise ValueError(f"Unknown stored content block type: {kind!r}")


def decode_message(
    *,
    role: str,
    content: Iterable[Mapping[str, Any]],
    round_trip_payload: Mapping[str, Any] | list[Mapping[str, Any]] | None = None,
    include_round_trip: bool = True,
) -> ModelMessage:
    """Decode a row without ever creating a ``system`` message."""

    if role not in {"user", "assistant", "tool"}:
        raise ValueError(f"Stored conversation role is invalid: {role!r}")

    blocks: list[ContentBlock] = [_decode_block(item) for item in content]
    if include_round_trip and round_trip_payload:
        payloads: list[Mapping[str, Any]]
        if isinstance(round_trip_payload, list):
            payloads = round_trip_payload
        elif "blocks" in round_trip_payload:
            payloads = list(round_trip_payload["blocks"])
        else:
            payloads = [round_trip_payload]
        opaque_blocks: list[tuple[int | None, OpaqueBlock]] = []
        for item in payloads:
            protocol = item["protocol"]
            if protocol not in PROTOCOLS:
                raise ValueError(f"Unknown opaque block protocol: {protocol!r}")
            position = item.get("content_index")
            opaque_blocks.append(
                (
                    int(position) if position is not None else None,
                    OpaqueBlock(protocol=cast(Protocol, protocol), data=dict(item["data"])),
                )
            )
        if any(position is not None for position, _ in opaque_blocks):
            # 新记录带有普通内容之前的数量；没有位置的旧前置块仍放在最前面。
            before = [opaque_block for position, opaque_block in opaque_blocks if position is None]
            positioned = [
                (position, opaque_block)
                for position, opaque_block in opaque_blocks
                if position is not None
            ]
            positioned_by_index: dict[int, list[OpaqueBlock]] = {}
            for position, opaque_block in positioned:
                positioned_by_index.setdefault(position, []).append(opaque_block)
            merged: list[ContentBlock] = [*before]
            for index, content_block in enumerate(blocks):
                merged.extend(positioned_by_index.get(index, []))
                merged.append(content_block)
            merged.extend(positioned_by_index.get(len(blocks), []))
            blocks = merged
        else:
            blocks = [block for _, block in opaque_blocks] + blocks
    return ModelMessage(role=cast(Role, role), content=tuple(blocks))


def row_to_model_message(row: MessageRow, *, include_round_trip: bool = True) -> ModelMessage:
    return decode_message(
        role=row.role,
        content=row.content,
        round_trip_payload=row.round_trip_payload,
        include_round_trip=include_round_trip,
    )


def row_to_view(row: MessageRow) -> MessageView:
    view: MessageView = MessageView.model_validate(row)
    return view


def session_to_view(row: SessionRow) -> SessionView:
    view: SessionView = SessionView.model_validate(row)
    return view
