"""ModelPort 边界的确定性录制与回放。

录制的是协议适配器已经产出的 ``ModelEvent``，不包含 HTTP 帧、chunk 时序或
鉴权信息。这样 ``AgentRunner`` 可以在零网络、零数据库的情况下消费同一份事件流。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

from .effort import EffortTier
from .events import (
    ModelCallCompleted,
    ModelEvent,
    ReasoningDelta,
    TextDelta,
    ToolCallArgsDelta,
    ToolCallCompleted,
    ToolCallStarted,
    Usage,
)
from .message import ModelMessage, OpaqueBlock, TextBlock, ToolCallBlock, ToolResultBlock
from .port import ModelPort
from .profile import EndpointProfile

REPLAY_SCHEMA_VERSION = 1


class ReplayError(ValueError):
    """录制物无效，或回放请求与录制请求不一致。"""


def canonical_json_bytes(value: Any) -> bytes:
    """返回跨进程稳定、适合 diff 的 JSON 字节。"""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _message_to_dict(message: ModelMessage) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    for block in message.content:
        if isinstance(block, TextBlock):
            blocks.append({"type": "text", "text": block.text})
        elif isinstance(block, ToolCallBlock):
            blocks.append(
                {
                    "type": "tool_call",
                    "id": block.id,
                    "name": block.name,
                    "arguments": block.arguments,
                }
            )
        elif isinstance(block, ToolResultBlock):
            blocks.append(
                {
                    "type": "tool_result",
                    "tool_call_id": block.tool_call_id,
                    "content": block.content,
                    "is_error": block.is_error,
                }
            )
        elif isinstance(block, OpaqueBlock):
            blocks.append({"type": "opaque", "protocol": block.protocol, "data": block.data})
        else:  # pragma: no cover - ContentBlock 已穷尽，防止未来扩展静默丢数据
            raise TypeError(f"Unsupported message block: {type(block)!r}")
    return {"role": message.role, "content": blocks}


def _message_from_dict(raw: Mapping[str, Any]) -> ModelMessage:
    role = raw.get("role")
    if role not in {"system", "user", "assistant", "tool"}:
        raise ReplayError(f"录制物包含未知消息 role: {role!r}")
    blocks: list[Any] = []
    for item in raw.get("content", []):
        if not isinstance(item, Mapping):
            raise ReplayError("录制物的消息 block 不是对象")
        kind = item.get("type")
        if kind == "text":
            blocks.append(TextBlock(text=str(item.get("text", ""))))
        elif kind == "tool_call":
            blocks.append(
                ToolCallBlock(
                    id=str(item["id"]),
                    name=str(item["name"]),
                    arguments=dict(item.get("arguments", {})),
                )
            )
        elif kind == "tool_result":
            blocks.append(
                ToolResultBlock(
                    tool_call_id=str(item["tool_call_id"]),
                    content=str(item.get("content", "")),
                    is_error=bool(item.get("is_error", False)),
                )
            )
        elif kind == "opaque":
            protocol = item.get("protocol")
            if protocol not in {
                "openai_responses",
                "openai_chat_completions",
                "anthropic_messages",
            }:
                raise ReplayError(f"录制物包含未知 opaque protocol: {protocol!r}")
            blocks.append(
                OpaqueBlock(protocol=cast(Any, protocol), data=dict(item.get("data", {})))
            )
        else:
            raise ReplayError(f"录制物包含未知消息 block type: {kind!r}")
    return ModelMessage(role=cast(Any, role), content=tuple(blocks))


def _event_to_dict(event: ModelEvent) -> dict[str, Any]:
    if isinstance(event, TextDelta):
        return {"type": "text_delta", "text": event.text}
    if isinstance(event, ReasoningDelta):
        return {"type": "reasoning_delta", "text": event.text}
    if isinstance(event, ToolCallStarted):
        return {"type": "tool_call_started", "id": event.id, "name": event.name}
    if isinstance(event, ToolCallArgsDelta):
        return {"type": "tool_call_args_delta", "id": event.id, "args_delta": event.args_delta}
    if isinstance(event, ToolCallCompleted):
        return {"type": "tool_call_completed", "id": event.id}
    if isinstance(event, ModelCallCompleted):
        return {
            "type": "model_call_completed",
            "message": _message_to_dict(event.message),
            "usage": {
                "state": event.usage.state,
                "input_tokens": event.usage.input_tokens,
                "output_tokens": event.usage.output_tokens,
                "reasoning_tokens": event.usage.reasoning_tokens,
            },
            "stop_reason": event.stop_reason,
        }
    raise TypeError(f"Unsupported model event: {type(event)!r}")


def _event_from_dict(raw: Mapping[str, Any]) -> ModelEvent:
    kind = raw.get("type")
    if kind == "text_delta":
        return TextDelta(text=str(raw.get("text", "")))
    if kind == "reasoning_delta":
        return ReasoningDelta(text=str(raw.get("text", "")))
    if kind == "tool_call_started":
        return ToolCallStarted(id=str(_required(raw, "id")), name=str(_required(raw, "name")))
    if kind == "tool_call_args_delta":
        return ToolCallArgsDelta(
            id=str(_required(raw, "id")),
            args_delta=str(_required(raw, "args_delta")),
        )
    if kind == "tool_call_completed":
        return ToolCallCompleted(id=str(_required(raw, "id")))
    if kind == "model_call_completed":
        usage_raw = raw.get("usage")
        if not isinstance(usage_raw, Mapping):
            raise ReplayError("ModelCallCompleted 缺少 usage")
        state = usage_raw.get("state")
        if state not in {"complete", "partial", "unavailable"}:
            raise ReplayError(f"录制物包含未知 usage state: {state!r}")
        if "input_tokens" not in usage_raw:
            raise ReplayError("录制物的 usage 缺少 input_tokens")
        input_tokens = _optional_int(usage_raw.get("input_tokens"))
        if state == "complete" and input_tokens is None:
            raise ReplayError("complete usage 的 input_tokens 不能为 null")
        message_raw = _required(raw, "message")
        if not isinstance(message_raw, Mapping):
            raise ReplayError("ModelCallCompleted 的 message 必须是对象")
        return ModelCallCompleted(
            message=_message_from_dict(message_raw),
            usage=Usage(
                state=cast(Any, state),
                input_tokens=input_tokens,
                output_tokens=_optional_int(usage_raw.get("output_tokens")),
                reasoning_tokens=_optional_int(usage_raw.get("reasoning_tokens")),
            ),
            stop_reason=str(raw.get("stop_reason", "unknown")),
        )
    raise ReplayError(f"录制物包含未知 event type: {kind!r}")


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReplayError(f"usage token 必须是整数或 null: {value!r}")
    return value


def _required(raw: Mapping[str, Any], key: str) -> Any:
    if key not in raw:
        raise ReplayError(f"录制物缺少字段: {key}")
    return raw[key]


def _request_dict(
    *,
    messages: Sequence[ModelMessage],
    tools: Sequence[Any],
    model: str,
    effort: EffortTier,
    profile: EndpointProfile,
) -> dict[str, Any]:
    # 不把 API key 写进录制物；端点的语义身份仍参与输入匹配。
    return {
        "messages": [_message_to_dict(message) for message in messages],
        "tools": list(tools),
        "model": model,
        "effort": effort,
        "profile": {
            "name": profile.name,
            "protocol": profile.protocol,
            "base_url": profile.base_url,
            "auth_field": profile.auth_field,
        },
    }


_REPLAY_RUN_NAMESPACE = uuid5(NAMESPACE_URL, "chat-agents/replay")


def deterministic_run_id(
    *,
    messages: Sequence[ModelMessage],
    tools: Sequence[Any],
    model: str,
    effort: EffortTier,
    profile: EndpointProfile,
) -> str:
    """从一次 replay 输入稳定派生运行标识，不把鉴权信息纳入命名空间。"""

    request = _request_dict(
        messages=messages,
        tools=tools,
        model=model,
        effort=effort,
        profile=profile,
    )
    return str(uuid5(_REPLAY_RUN_NAMESPACE, canonical_json_bytes(request).decode("utf-8")))


@dataclass(frozen=True, slots=True)
class _RecordedTurn:
    request: dict[str, Any]
    events: tuple[ModelEvent, ...]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "request": self.request,
            "events": [_event_to_dict(event) for event in self.events],
        }
        if self.error is not None:
            result["error"] = self.error
        return result

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> _RecordedTurn:
        events_raw = raw.get("events")
        if not isinstance(events_raw, list):
            raise ReplayError("录制 turn 的 events 必须是数组")
        request = raw.get("request")
        if not isinstance(request, Mapping):
            raise ReplayError("录制 turn 缺少 request")
        events: list[ModelEvent] = []
        for event in events_raw:
            if not isinstance(event, Mapping):
                raise ReplayError("录制 turn 的 event 必须是对象")
            events.append(_event_from_dict(event))
        return cls(
            request=dict(request),
            events=tuple(events),
            error=str(raw["error"]) if raw.get("error") is not None else None,
        )


class RecordingModelPort:
    """包裹真实 ``ModelPort``，收集每次调用的完整事件序列。"""

    def __init__(self, delegate: ModelPort) -> None:
        self._delegate = delegate
        self._turns: list[_RecordedTurn] = []

    @property
    def turn_count(self) -> int:
        return len(self._turns)

    async def stream(
        self,
        *,
        messages: Sequence[ModelMessage],
        tools: Sequence[Any],
        model: str,
        effort: EffortTier,
        profile: EndpointProfile,
    ) -> AsyncIterator[ModelEvent]:
        request = _request_dict(
            messages=messages, tools=tools, model=model, effort=effort, profile=profile
        )
        events: list[ModelEvent] = []
        error: str | None = None
        completed = False
        try:
            async for event in self._delegate.stream(
                messages=messages,
                tools=tools,
                model=model,
                effort=effort,
                profile=profile,
            ):
                events.append(event)
                completed = completed or isinstance(event, ModelCallCompleted)
                yield event
        except BaseException as exc:
            error = str(exc) or exc.__class__.__name__
            raise
        finally:
            if error is None and not completed:
                error = "模型流未产出终态事件"
            self._turns.append(_RecordedTurn(request=request, events=tuple(events), error=error))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": REPLAY_SCHEMA_VERSION,
            "turns": [turn.to_dict() for turn in self._turns],
        }

    def to_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def save(self, path: str | Path) -> None:
        Path(path).write_bytes(self.to_bytes())


class ReplayModelPort:
    """按录制顺序回放 ``ModelEvent``，并拒绝错误输入静默复用录制物。"""

    def __init__(self, turns: Iterable[_RecordedTurn]) -> None:
        self._turns = tuple(turns)
        self._next_turn = 0

    @classmethod
    def from_bytes(cls, data: bytes) -> ReplayModelPort:
        try:
            raw = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReplayError("录制物不是有效 UTF-8 JSON") from exc
        if not isinstance(raw, Mapping) or raw.get("schema_version") != REPLAY_SCHEMA_VERSION:
            raise ReplayError("不支持的 replay schema version")
        turns_raw = raw.get("turns")
        if not isinstance(turns_raw, list):
            raise ReplayError("录制物的 turns 必须是数组")
        turns: list[_RecordedTurn] = []
        for turn in turns_raw:
            if not isinstance(turn, Mapping):
                raise ReplayError("录制物的 turn 必须是对象")
            turns.append(_RecordedTurn.from_dict(turn))
        return cls(turns)

    @classmethod
    def load(cls, path: str | Path) -> ReplayModelPort:
        return cls.from_bytes(Path(path).read_bytes())

    async def stream(
        self,
        *,
        messages: Sequence[ModelMessage],
        tools: Sequence[Any],
        model: str,
        effort: EffortTier,
        profile: EndpointProfile,
    ) -> AsyncIterator[ModelEvent]:
        if self._next_turn >= len(self._turns):
            raise ReplayError("回放录制物已耗尽")
        expected = self._turns[self._next_turn]
        actual_request = _request_dict(
            messages=messages, tools=tools, model=model, effort=effort, profile=profile
        )
        if canonical_json_bytes(actual_request) != canonical_json_bytes(expected.request):
            raise ReplayError("回放输入不匹配")
        self._next_turn += 1
        for event in expected.events:
            yield event
        if expected.error is not None:
            raise ReplayError(expected.error)
