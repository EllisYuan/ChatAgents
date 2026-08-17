"""``anthropic_messages`` 协议适配器。

原始事件（``client.messages.create(stream=True, ...)``）而非 SDK 的高层累积
helper——中断时需要拿到已到手的碎片，``get_final_message()`` 在没收到终态事件
时会抛 ``RuntimeError``，不是我们要的「局部真值」语义。

上游错误按 ADR-0015 原样向上抛出 SDK 自身异常，这里不包一层分类；中断时先把
已知的用量三态收尾事件 yield 出去，再重新抛出异常。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from anthropic import AsyncAnthropic

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

_DEFAULT_MAX_TOKENS = 8192


def _serialize_message(message: ModelMessage) -> dict[str, Any]:
    role = "assistant" if message.role == "assistant" else "user"
    content: list[dict[str, Any]] = []
    for block in message.content:
        if isinstance(block, TextBlock):
            content.append({"type": "text", "text": block.text})
        elif isinstance(block, ToolCallBlock):
            content.append(
                {"type": "tool_use", "id": block.id, "name": block.name, "input": block.arguments}
            )
        elif isinstance(block, ToolResultBlock):
            content.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.tool_call_id,
                    "content": block.content,
                    "is_error": block.is_error,
                }
            )
        elif isinstance(block, OpaqueBlock):
            # 原样整块传回，包括 thinking 正文——不像 openai_responses 那样能把显示
            # 摘要摘掉再传：Anthropic 官方原文是「must be... complete and unmodified」，
            # 连过滤掉 redacted_thinking 都会 400（ADR-0017），改动 thinking 字段本身
            # 风险同理。这是 ADR-0017「摘要不进模型输入」在这个协议上唯一让步的地方。
            content.append(block.data)
    return {"role": role, "content": content}


def build_request(
    *,
    messages: Sequence[ModelMessage],
    tools: Sequence[Any],
    model: str,
    effort: EffortTier,
) -> dict[str, Any]:
    system_text = "\n\n".join(
        block.text
        for message in messages
        if message.role == "system"
        for block in message.content
        if isinstance(block, TextBlock)
    )
    payload: dict[str, Any] = {
        "model": model,
        "max_tokens": _DEFAULT_MAX_TOKENS,
        "messages": [_serialize_message(m) for m in messages if m.role != "system"],
        "stream": True,
    }
    if system_text:
        payload["system"] = system_text
    if tools:
        payload["tools"] = to_protocol_tools(tools, "anthropic_messages")
    apply_effort("anthropic_messages", payload, effort)
    apply_summary_flag("anthropic_messages", payload)
    return payload


@dataclass
class _BlockState:
    type: str
    id: str | None = None
    name: str | None = None
    text_acc: str = ""
    thinking_acc: str = ""
    signature_acc: str = ""
    json_acc: str = ""
    redacted_data: str | None = None


@dataclass
class _Accumulator:
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    stop_reason: str | None = None
    blocks: dict[int, _BlockState] = field(default_factory=dict)

    def handle(self, raw_event: Any) -> list[ModelEvent]:
        kind = raw_event.type
        if kind == "message_start":
            self.input_tokens = raw_event.message.usage.input_tokens
            return []
        if kind == "content_block_start":
            return self._on_block_start(raw_event)
        if kind == "content_block_delta":
            return self._on_block_delta(raw_event)
        if kind == "content_block_stop":
            return self._on_block_stop(raw_event)
        if kind == "message_delta":
            self.stop_reason = raw_event.delta.stop_reason
            usage = raw_event.usage
            self.output_tokens = usage.output_tokens
            details = usage.output_tokens_details
            self.reasoning_tokens = details.thinking_tokens if details is not None else None
            return []
        return []  # message_stop and any unrecognized event carry nothing further to map

    def _on_block_start(self, raw_event: Any) -> list[ModelEvent]:
        cb = raw_event.content_block
        state = _BlockState(type=cb.type)
        if cb.type == "tool_use":
            state.id = cb.id
            state.name = cb.name
            self.blocks[raw_event.index] = state
            return [ToolCallStarted(id=cb.id, name=cb.name)]
        if cb.type == "redacted_thinking":
            state.redacted_data = cb.data
        self.blocks[raw_event.index] = state
        return []

    def _on_block_delta(self, raw_event: Any) -> list[ModelEvent]:
        state = self.blocks[raw_event.index]
        delta = raw_event.delta
        if delta.type == "text_delta":
            state.text_acc += delta.text
            return [TextDelta(text=delta.text)]
        if delta.type == "input_json_delta":
            state.json_acc += delta.partial_json
            return [ToolCallArgsDelta(id=state.id or "", args_delta=delta.partial_json)]
        if delta.type == "thinking_delta":
            state.thinking_acc += delta.thinking
            return [ReasoningDelta(text=delta.thinking)] if delta.thinking else []
        if delta.type == "signature_delta":
            state.signature_acc += delta.signature
            return []
        return []  # citations_delta and any future delta kinds: read to not consume

    def _on_block_stop(self, raw_event: Any) -> list[ModelEvent]:
        state = self.blocks[raw_event.index]
        if state.type == "tool_use":
            return [ToolCallCompleted(id=state.id or "")]
        return []

    def final_message(self) -> ModelMessage:
        content: list[Any] = []
        for index in sorted(self.blocks):
            state = self.blocks[index]
            if state.type == "text":
                content.append(TextBlock(text=state.text_acc))
            elif state.type == "tool_use":
                args = json.loads(state.json_acc) if state.json_acc else {}
                content.append(
                    ToolCallBlock(id=state.id or "", name=state.name or "", arguments=args)
                )
            elif state.type == "thinking":
                content.append(
                    OpaqueBlock(
                        protocol="anthropic_messages",
                        data={
                            "type": "thinking",
                            "thinking": state.thinking_acc,
                            "signature": state.signature_acc,
                        },
                    )
                )
            elif state.type == "redacted_thinking":
                content.append(
                    OpaqueBlock(
                        protocol="anthropic_messages",
                        data={"type": "redacted_thinking", "data": state.redacted_data},
                    )
                )
        return ModelMessage(role="assistant", content=tuple(content))

    def usage(self, *, interrupted: bool) -> Usage:
        # 状态只看拿到了什么真值，不看 interrupted 本身——流没被打断但提前收工
        # （没等到 message_delta 就 message_stop 了）同样不该被记成 complete。
        del interrupted
        if self.input_tokens is not None and self.output_tokens is not None:
            state: UsageState = "complete"
        elif self.input_tokens is not None or self.output_tokens is not None:
            state = "partial"
        else:
            state = "unavailable"
        return Usage(
            state=state,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            reasoning_tokens=self.reasoning_tokens,
        )


class AnthropicMessagesAdapter:
    def __init__(self, client: AsyncAnthropic) -> None:
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
        del profile  # 鉴权/base_url 已经在客户端构造时定死，这里不再用它
        payload = build_request(messages=messages, tools=tools, model=model, effort=effort)
        acc = _Accumulator()
        raw_stream = await self._client.messages.create(**payload)
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
