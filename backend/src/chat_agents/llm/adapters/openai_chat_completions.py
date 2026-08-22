"""``openai_chat_completions`` 协议适配器。

ADR-0017：这个协议一概不采原生推理——不往返（协议里没有这个位置）也不显示。
中转站自造的 ``reasoning_content`` 字段读到不消费：代码里没有分支去访问它。

原始 chunk（``stream_options={"include_usage": True}``），不用 SDK 的
``chat.completions.stream()`` helper，理由与另两个适配器一致。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI

from ..effort import EffortTier, apply_effort, apply_summary_flag
from ..events import (
    ModelCallCompleted,
    ModelEvent,
    TextDelta,
    ToolCallArgsDelta,
    ToolCallCompleted,
    ToolCallStarted,
    Usage,
)
from ..message import ModelMessage, TextBlock, ToolCallBlock, ToolResultBlock
from ..profile import EndpointProfile
from ..tool_schema import to_protocol_tools


def _serialize_message(message: ModelMessage) -> list[dict[str, Any]]:
    if message.role == "tool":
        return [
            {"role": "tool", "tool_call_id": block.tool_call_id, "content": block.content}
            for block in message.content
            if isinstance(block, ToolResultBlock)
        ]
    text = "".join(block.text for block in message.content if isinstance(block, TextBlock))
    tool_calls = [
        {
            "id": block.id,
            "type": "function",
            "function": {"name": block.name, "arguments": json.dumps(block.arguments)},
        }
        for block in message.content
        if isinstance(block, ToolCallBlock)
    ]
    native: dict[str, Any] = {"role": message.role, "content": text}
    if tool_calls:
        native["tool_calls"] = tool_calls
    return [native]


def build_request(
    *,
    messages: Sequence[ModelMessage],
    tools: Sequence[Any],
    model: str,
    effort: EffortTier,
    system_prompt: str | None = None,
) -> dict[str, Any]:
    native_messages: list[dict[str, Any]] = []
    if system_prompt:
        native_messages.append({"role": "system", "content": system_prompt})
    for message in messages:
        native_messages.extend(_serialize_message(message))
    payload: dict[str, Any] = {
        "model": model,
        "messages": native_messages,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if tools:
        payload["tools"] = to_protocol_tools(tools, "openai_chat_completions")
    apply_effort("openai_chat_completions", payload, effort)
    apply_summary_flag("openai_chat_completions", payload)  # 不写任何字段，此协议不采摘要
    return payload


@dataclass
class _ToolCallState:
    id: str | None = None
    name: str | None = None
    args_acc: str = ""


@dataclass
class _Accumulator:
    text_acc: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    stop_reason: str | None = None
    tool_calls: dict[int, _ToolCallState] = field(default_factory=dict)
    started_tool_call_indices: set[int] = field(default_factory=set)

    def handle(self, chunk: Any) -> list[ModelEvent]:
        events: list[ModelEvent] = []
        if chunk.usage is not None:
            self.input_tokens = chunk.usage.prompt_tokens
            self.output_tokens = chunk.usage.completion_tokens
        for choice in chunk.choices:
            events.extend(self._on_choice(choice))
        return events

    def _on_choice(self, choice: Any) -> list[ModelEvent]:
        events: list[ModelEvent] = []
        delta = choice.delta
        if choice.finish_reason:
            self.stop_reason = choice.finish_reason
        if delta.content:
            self.text_acc += delta.content
            events.append(TextDelta(text=delta.content))
        for tool_call_delta in delta.tool_calls or []:
            events.extend(self._on_tool_call_delta(tool_call_delta))
        return events

    def _on_tool_call_delta(self, tool_call_delta: Any) -> list[ModelEvent]:
        events: list[ModelEvent] = []
        index = tool_call_delta.index
        state = self.tool_calls.setdefault(index, _ToolCallState())
        if tool_call_delta.id:
            state.id = tool_call_delta.id
        function = tool_call_delta.function
        if function is not None and function.name:
            state.name = function.name
        if index not in self.started_tool_call_indices and state.id and state.name:
            self.started_tool_call_indices.add(index)
            events.append(ToolCallStarted(id=state.id, name=state.name))
        if function is not None and function.arguments:
            state.args_acc += function.arguments
            events.append(ToolCallArgsDelta(id=state.id or "", args_delta=function.arguments))
        return events

    def tool_call_completed_events(self) -> list[ModelEvent]:
        return [
            ToolCallCompleted(id=state.id or "")
            for _, state in sorted(self.tool_calls.items())
            if state.id
        ]

    def final_message(self) -> ModelMessage:
        content: list[Any] = []
        if self.text_acc:
            content.append(TextBlock(text=self.text_acc))
        for _, state in sorted(self.tool_calls.items()):
            arguments = json.loads(state.args_acc) if state.args_acc else {}
            content.append(
                ToolCallBlock(id=state.id or "", name=state.name or "", arguments=arguments)
            )
        return ModelMessage(role="assistant", content=tuple(content))

    def usage(self, *, interrupted: bool) -> Usage:
        # 中断，或流正常结束但没等到 usage chunk（服务端没按 include_usage 承诺回），
        # 两种都归 unavailable——没有任何一个真实数字，不得记 0。
        if interrupted or self.input_tokens is None:
            return Usage(
                state="unavailable", input_tokens=None, output_tokens=None, reasoning_tokens=None
            )
        return Usage(
            state="complete",
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            reasoning_tokens=None,
        )


class OpenAIChatCompletionsAdapter:
    def __init__(self, client: AsyncOpenAI) -> None:
        self._client = client

    async def stream(
        self,
        *,
        messages: Sequence[ModelMessage],
        tools: Sequence[Any],
        model: str,
        effort: EffortTier,
        profile: EndpointProfile,
        system_prompt: str | None = None,
    ) -> AsyncIterator[ModelEvent]:
        del profile
        payload = build_request(
            messages=messages,
            tools=tools,
            model=model,
            effort=effort,
            system_prompt=system_prompt,
        )
        acc = _Accumulator()
        raw_stream = await self._client.chat.completions.create(**payload)
        try:
            async for chunk in raw_stream:
                for event in acc.handle(chunk):
                    yield event
        except Exception:
            yield ModelCallCompleted(
                message=acc.final_message(),
                usage=acc.usage(interrupted=True),
                stop_reason="interrupted",
            )
            raise
        else:
            for event in acc.tool_call_completed_events():
                yield event
            yield ModelCallCompleted(
                message=acc.final_message(),
                usage=acc.usage(interrupted=False),
                stop_reason=acc.stop_reason or "unknown",
            )
