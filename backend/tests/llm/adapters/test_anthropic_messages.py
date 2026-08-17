"""AnthropicMessagesAdapter：假 SDK 客户端驱动，不经 HTTP。

规范外字段（如 ``caller``/``stop_details``）与缺失字段用 ``SimpleNamespace``
自由构造，验证「读到不消费」——代码里没有分支去访问它们，出现与否都不影响结果。
"""

import asyncio
from types import SimpleNamespace

import pytest
from chat_agents.llm.adapters.anthropic_messages import AnthropicMessagesAdapter
from chat_agents.llm.effort import EffortTier
from chat_agents.llm.events import (
    ModelCallCompleted,
    ReasoningDelta,
    TextDelta,
    ToolCallArgsDelta,
    ToolCallCompleted,
    ToolCallStarted,
)
from chat_agents.llm.message import ModelMessage, OpaqueBlock, TextBlock, ToolCallBlock
from chat_agents.llm.profile import EndpointProfile
from chat_agents.tools.types import ToolSpec
from pydantic import SecretStr


def _profile() -> EndpointProfile:
    return EndpointProfile(
        name="anthropic-official",
        protocol="anthropic_messages",
        base_url="https://api.anthropic.com",
        auth_field="x-api-key",
        api_key=SecretStr("sk-test"),
    )


class _FakeRawStream:
    def __init__(self, events: list[object], *, fail_after: int | None = None) -> None:
        self._events = events
        self._fail_after = fail_after

    def __aiter__(self) -> "_FakeRawStream":
        self._iter = iter(self._events)
        self._yielded = 0
        return self

    async def __anext__(self) -> object:
        if self._fail_after is not None and self._yielded >= self._fail_after:
            raise ConnectionError("upstream dropped the connection")
        try:
            event = next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc
        self._yielded += 1
        return event


class _FakeMessages:
    def __init__(self, stream: _FakeRawStream) -> None:
        self._stream = stream
        self.last_kwargs: dict | None = None

    async def create(self, **kwargs: object) -> _FakeRawStream:
        self.last_kwargs = kwargs
        return self._stream


class _FakeClient:
    def __init__(self, stream: _FakeRawStream) -> None:
        self.messages = _FakeMessages(stream)


def _happy_path_events() -> list[object]:
    return [
        SimpleNamespace(
            type="message_start",
            message=SimpleNamespace(usage=SimpleNamespace(input_tokens=25)),
        ),
        SimpleNamespace(
            type="content_block_start",
            index=0,
            content_block=SimpleNamespace(type="thinking", thinking="", signature=""),
        ),
        SimpleNamespace(
            type="content_block_delta",
            index=0,
            delta=SimpleNamespace(type="thinking_delta", thinking="let me think"),
        ),
        SimpleNamespace(
            type="content_block_delta",
            index=0,
            delta=SimpleNamespace(type="signature_delta", signature="sig-abc"),
        ),
        SimpleNamespace(type="content_block_stop", index=0),
        SimpleNamespace(
            type="content_block_start",
            index=1,
            content_block=SimpleNamespace(type="text"),
        ),
        SimpleNamespace(
            type="content_block_delta",
            index=1,
            delta=SimpleNamespace(type="text_delta", text="the answer is "),
        ),
        SimpleNamespace(type="content_block_stop", index=1),
        SimpleNamespace(
            type="content_block_start",
            index=2,
            content_block=SimpleNamespace(type="tool_use", id="toolu_1", name="add", caller=None),
        ),
        SimpleNamespace(
            type="content_block_delta",
            index=2,
            delta=SimpleNamespace(type="input_json_delta", partial_json='{"a": 1,'),
        ),
        SimpleNamespace(
            type="content_block_delta",
            index=2,
            delta=SimpleNamespace(type="input_json_delta", partial_json=' "b": 3}'),
        ),
        SimpleNamespace(type="content_block_stop", index=2),
        SimpleNamespace(
            type="message_delta",
            delta=SimpleNamespace(
                stop_reason="tool_use",
                stop_sequence=None,
                stop_details=SimpleNamespace(extra="unspecified field, must not be read"),
            ),
            usage=SimpleNamespace(
                output_tokens=42,
                output_tokens_details=SimpleNamespace(thinking_tokens=7),
            ),
        ),
        SimpleNamespace(type="message_stop"),
    ]


def _tool() -> ToolSpec:
    async def _handler(_args: dict, _ctx: object) -> None:  # pragma: no cover
        raise NotImplementedError

    return ToolSpec(
        name="add",
        description="Add two numbers.",
        parameters={"type": "object", "properties": {}},
        handler=_handler,
        timeout_s=5.0,
        retryable=True,
    )


async def _collect(
    client: _FakeClient, *, effort: EffortTier = "medium", tools: list[ToolSpec] | None = None
) -> list[object]:
    adapter = AnthropicMessagesAdapter(client=client)
    messages = [ModelMessage(role="user", content=(TextBlock(text="what is 1+3?"),))]
    events: list[object] = []
    async for event in adapter.stream(
        messages=messages,
        tools=tools if tools is not None else [_tool()],
        model="claude-sonnet-5",
        effort=effort,
        profile=_profile(),
    ):
        events.append(event)
    return events


def test_happy_path_emits_text_reasoning_and_tool_call_deltas() -> None:
    client = _FakeClient(_FakeRawStream(_happy_path_events()))
    events = asyncio.run(_collect(client))

    assert TextDelta(text="the answer is ") in events
    assert ReasoningDelta(text="let me think") in events
    assert ToolCallStarted(id="toolu_1", name="add") in events
    assert ToolCallArgsDelta(id="toolu_1", args_delta='{"a": 1,') in events
    assert ToolCallArgsDelta(id="toolu_1", args_delta=' "b": 3}') in events
    assert ToolCallCompleted(id="toolu_1") in events


def test_happy_path_completed_message_and_usage() -> None:
    client = _FakeClient(_FakeRawStream(_happy_path_events()))
    events = asyncio.run(_collect(client))

    completed = [e for e in events if isinstance(e, ModelCallCompleted)]
    assert len(completed) == 1
    event = completed[0]
    assert event.stop_reason == "tool_use"
    assert event.usage.state == "complete"
    assert event.usage.input_tokens == 25
    assert event.usage.output_tokens == 42
    assert event.usage.reasoning_tokens == 7

    assert event.message.role == "assistant"
    opaque, text, tool_call = event.message.content
    assert isinstance(opaque, OpaqueBlock)
    assert opaque.protocol == "anthropic_messages"
    assert opaque.data == {"type": "thinking", "thinking": "let me think", "signature": "sig-abc"}
    assert text == TextBlock(text="the answer is ")
    assert tool_call == ToolCallBlock(id="toolu_1", name="add", arguments={"a": 1, "b": 3})


def test_request_payload_maps_tools_effort_and_summary_flag() -> None:
    client = _FakeClient(_FakeRawStream(_happy_path_events()))
    asyncio.run(_collect(client, effort="xhigh"))

    kwargs = client.messages.last_kwargs
    assert kwargs is not None
    assert kwargs["model"] == "claude-sonnet-5"
    assert kwargs["tools"] == [
        {
            "name": "add",
            "description": "Add two numbers.",
            "input_schema": {"type": "object", "properties": {}},
        }
    ]
    assert kwargs["thinking"] == {"effort": "xhigh", "display": "summarized"}


def test_interruption_after_message_start_reports_partial_usage() -> None:
    events = _happy_path_events()[:3]  # stop right after message_start + a couple of deltas
    client = _FakeClient(_FakeRawStream(events, fail_after=len(events)))

    collected: list[object] = []

    async def _run() -> None:
        adapter = AnthropicMessagesAdapter(client=client)
        async for event in adapter.stream(
            messages=[ModelMessage(role="user", content=(TextBlock(text="hi"),))],
            tools=[],
            model="claude-sonnet-5",
            effort="medium",
            profile=_profile(),
        ):
            collected.append(event)

    with pytest.raises(ConnectionError):
        asyncio.run(_run())

    completed = [e for e in collected if isinstance(e, ModelCallCompleted)]
    assert len(completed) == 1
    usage = completed[0].usage
    assert usage.state == "partial"
    assert usage.input_tokens == 25
    assert usage.output_tokens is None
    assert usage.output_tokens != 0
    assert completed[0].stop_reason == "interrupted"


def test_interruption_before_any_data_reports_unavailable_usage() -> None:
    client = _FakeClient(_FakeRawStream([], fail_after=0))
    collected: list[object] = []

    async def _run() -> None:
        adapter = AnthropicMessagesAdapter(client=client)
        async for event in adapter.stream(
            messages=[ModelMessage(role="user", content=(TextBlock(text="hi"),))],
            tools=[],
            model="claude-sonnet-5",
            effort="medium",
            profile=_profile(),
        ):
            collected.append(event)

    with pytest.raises(ConnectionError):
        asyncio.run(_run())

    completed = [e for e in collected if isinstance(e, ModelCallCompleted)]
    assert len(completed) == 1
    usage = completed[0].usage
    assert usage.state == "unavailable"
    assert usage.input_tokens is None
    assert usage.output_tokens is None
    assert usage.reasoning_tokens is None
