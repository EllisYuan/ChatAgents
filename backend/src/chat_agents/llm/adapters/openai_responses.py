"""``openai_responses`` 协议适配器。

原始事件（``client.responses.create(stream=True, ...)``），不用 SDK 的
``responses.stream()`` helper——理由与 anthropic 适配器一致：中断时要局部真值。

Responses 协议的用量只在 ``response.completed`` 里给，中断前拿不到任何一个
真实数字，所以中断态恒为 ``unavailable``（这是协议结构，不是本适配器偷懒）。
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
    ReasoningDelta,
    TextDelta,
    ToolCallArgsDelta,
    ToolCallCompleted,
    ToolCallStarted,
    Usage,
    UsageState,
)
from ..message import ModelMessage, OpaqueBlock, TextBlock, ToolCallBlock, ToolResultBlock
from ..profile import EndpointProfile
from ..tool_schema import to_protocol_tools


def _serialize_message(message: ModelMessage) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for block in message.content:
        if isinstance(block, TextBlock):
            items.append(
                {
                    "role": message.role,
                    "content": [
                        {
                            "type": "input_text" if message.role != "assistant" else "output_text",
                            "text": block.text,
                        }
                    ],
                }
            )
        elif isinstance(block, ToolCallBlock):
            items.append(
                {
                    "type": "function_call",
                    "call_id": block.id,
                    "name": block.name,
                    "arguments": json.dumps(block.arguments),
                }
            )
        elif isinstance(block, ToolResultBlock):
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": block.tool_call_id,
                    "output": block.content,
                }
            )
        elif isinstance(block, OpaqueBlock):
            items.append(_strip_display_summary(block.data))
    return items


def _strip_display_summary(reasoning_item: dict[str, Any]) -> dict[str, Any]:
    """显示摘要永不进模型输入（ADR-0017）——往返载荷只有 ``encrypted_content``。

    OpenAI 官方措辞是「highly recommend」按原样传回而非强制逐字节不变（这一点与
    Anthropic 的「must be... unmodified」不同，见该协议适配器的对应处理），所以
    这里可以放心去掉 ``summary``，不会像 Anthropic 那样有被判定为改动过而 400 的
    风险。
    """
    if reasoning_item.get("type") != "reasoning":
        return reasoning_item
    return {k: v for k, v in reasoning_item.items() if k != "summary"}


def build_request(
    *, messages: Sequence[ModelMessage], tools: Sequence[Any], model: str, effort: EffortTier
) -> dict[str, Any]:
    instructions = "\n\n".join(
        block.text
        for message in messages
        if message.role == "system"
        for block in message.content
        if isinstance(block, TextBlock)
    )
    input_items: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "system":
            continue
        input_items.extend(_serialize_message(message))
    payload: dict[str, Any] = {"model": model, "input": input_items, "stream": True}
    if instructions:
        payload["instructions"] = instructions
    if tools:
        payload["tools"] = to_protocol_tools(tools, "openai_responses")
    apply_effort("openai_responses", payload, effort)
    apply_summary_flag("openai_responses", payload)
    return payload


@dataclass
class _ToolCallState:
    call_id: str
    name: str


@dataclass
class _Accumulator:
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    stop_reason: str | None = None
    final_output: list[Any] | None = None
    tool_calls_by_item_id: dict[str, _ToolCallState] = field(default_factory=dict)

    def handle(self, raw_event: Any) -> list[ModelEvent]:
        kind = raw_event.type
        if kind == "response.output_text.delta":
            return [TextDelta(text=raw_event.delta)]
        if kind == "response.reasoning_summary_text.delta":
            return [ReasoningDelta(text=raw_event.delta)] if raw_event.delta else []
        if kind == "response.output_item.added":
            return self._on_output_item_added(raw_event.item)
        if kind == "response.function_call_arguments.delta":
            state = self.tool_calls_by_item_id.get(raw_event.item_id)
            call_id = state.call_id if state else raw_event.item_id
            return [ToolCallArgsDelta(id=call_id, args_delta=raw_event.delta)]
        if (
            kind == "response.output_item.done"
            and getattr(raw_event.item, "type", None) == "function_call"
        ):
            state = self.tool_calls_by_item_id.get(raw_event.item.id)
            call_id = state.call_id if state else raw_event.item.call_id
            return [ToolCallCompleted(id=call_id)]
        if kind == "response.completed":
            response = raw_event.response
            self.stop_reason = response.status
            usage = response.usage
            self.input_tokens = usage.input_tokens
            self.output_tokens = usage.output_tokens
            details = usage.output_tokens_details
            self.reasoning_tokens = (
                getattr(details, "reasoning_tokens", None) if details is not None else None
            )
            self.final_output = list(response.output)
            return []
        return []  # response.created/in_progress/text.done/... and anything unrecognized: no-op

    def _on_output_item_added(self, item: Any) -> list[ModelEvent]:
        if getattr(item, "type", None) == "function_call":
            state = _ToolCallState(call_id=item.call_id, name=item.name)
            self.tool_calls_by_item_id[item.id] = state
            return [ToolCallStarted(id=item.call_id, name=item.name)]
        return []

    def final_message(self) -> ModelMessage:
        content: list[Any] = []
        for item in self.final_output or []:
            item_type = getattr(item, "type", None)
            if item_type == "message":
                for part in getattr(item, "content", []) or []:
                    if getattr(part, "type", None) == "output_text":
                        content.append(TextBlock(text=part.text))
            elif item_type == "function_call":
                arguments = json.loads(item.arguments) if item.arguments else {}
                content.append(ToolCallBlock(id=item.call_id, name=item.name, arguments=arguments))
            elif item_type == "reasoning":
                content.append(
                    OpaqueBlock(
                        protocol="openai_responses",
                        data={
                            "type": "reasoning",
                            "id": item.id,
                            "encrypted_content": getattr(item, "encrypted_content", None),
                            "summary": getattr(item, "summary", []),
                        },
                    )
                )
        return ModelMessage(role="assistant", content=tuple(content))

    def usage(self, *, interrupted: bool) -> Usage:
        # Responses 协议的用量是原子的——只在 response.completed 里一次性给全部三个
        # 数字。中断，或流正常结束但没等到 response.completed（同样拿不到任何真值），
        # 两者都归 unavailable；拿到了就是 complete，没有半真半假的中间态。
        del interrupted
        if self.input_tokens is None:
            state: UsageState = "unavailable"
        else:
            state = "complete"
        return Usage(
            state=state,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            reasoning_tokens=self.reasoning_tokens,
        )


class OpenAIResponsesAdapter:
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
    ) -> AsyncIterator[ModelEvent]:
        del profile
        payload = build_request(messages=messages, tools=tools, model=model, effort=effort)
        acc = _Accumulator()
        raw_stream = await self._client.responses.create(**payload)
        try:
            async for raw_event in raw_stream:
                for event in acc.handle(raw_event):
                    yield event
        except Exception:
            yield ModelCallCompleted(
                message=acc.final_message(),
                usage=acc.usage(interrupted=True),
                stop_reason="interrupted",
            )
            raise
        else:
            yield ModelCallCompleted(
                message=acc.final_message(),
                usage=acc.usage(interrupted=False),
                stop_reason=acc.stop_reason or "unknown",
            )
