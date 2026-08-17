"""OpenAIResponsesAdapter：假 SDK 客户端驱动，不经 HTTP。"""

import asyncio
from types import SimpleNamespace

import pytest
from chat_agents.llm.adapters.openai_responses import OpenAIResponsesAdapter
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
        name="official",
        protocol="openai_responses",
        base_url="https://api.openai.com/v1",
        auth_field="Authorization",
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


class _FakeResponses:
    def __init__(self, stream: _FakeRawStream) -> None:
        self._stream = stream
        self.last_kwargs: dict | None = None

    async def create(self, **kwargs: object) -> _FakeRawStream:
        self.last_kwargs = kwargs
        return self._stream


class _FakeClient:
    def __init__(self, stream: _FakeRawStream) -> None:
        self.responses = _FakeResponses(stream)


def _function_call_item(call_id: str, *, arguments: str = '{"a": 1, "b": 3}') -> SimpleNamespace:
    return SimpleNamespace(
        type="function_call",
        id="item_1",
        call_id=call_id,
        name="add",
        arguments=arguments,
        caller=None,  # 规范外字段，不消费
    )


def _happy_path_events() -> list[object]:
    return [
        SimpleNamespace(
            type="response.output_item.added",
            output_index=0,
            item=SimpleNamespace(type="reasoning", id="rs_1"),
        ),
        SimpleNamespace(
            type="response.reasoning_summary_text.delta",
            item_id="rs_1",
            delta="thinking about it",
        ),
        SimpleNamespace(
            type="response.output_item.added",
            output_index=1,
            item=SimpleNamespace(type="message", id="msg_1"),
        ),
        SimpleNamespace(
            type="response.output_text.delta",
            item_id="msg_1",
            delta="the answer is ",
        ),
        SimpleNamespace(
            type="response.output_item.added",
            output_index=2,
            item=_function_call_item("call_1"),
        ),
        SimpleNamespace(
            type="response.function_call_arguments.delta",
            item_id="call_1",
            delta='{"a": 1,',
        ),
        SimpleNamespace(
            type="response.function_call_arguments.delta",
            item_id="call_1",
            delta=' "b": 3}',
        ),
        SimpleNamespace(
            type="response.output_item.done",
            output_index=2,
            item=_function_call_item("call_1"),
        ),
        SimpleNamespace(
            type="response.completed",
            response=SimpleNamespace(
                status="completed",
                usage=SimpleNamespace(
                    input_tokens=30,
                    output_tokens=55,
                    output_tokens_details=SimpleNamespace(reasoning_tokens=12),
                ),
                output=[
                    SimpleNamespace(
                        type="reasoning",
                        id="rs_1",
                        encrypted_content="opaque-blob",
                        summary=[],
                        native_finish_reason="stop",  # 规范外字段
                    ),
                    SimpleNamespace(
                        type="message",
                        id="msg_1",
                        content=[SimpleNamespace(type="output_text", text="the answer is ")],
                    ),
                    _function_call_item("call_1"),
                ],
            ),
        ),
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


async def _collect(client: _FakeClient, *, effort: EffortTier = "medium") -> list[object]:
    adapter = OpenAIResponsesAdapter(client=client)
    messages = [ModelMessage(role="user", content=(TextBlock(text="what is 1+3?"),))]
    events: list[object] = []
    async for event in adapter.stream(
        messages=messages, tools=[_tool()], model="gpt-5.5", effort=effort, profile=_profile()
    ):
        events.append(event)
    return events


def test_happy_path_emits_text_reasoning_and_tool_call_deltas() -> None:
    events = asyncio.run(_collect(_FakeClient(_FakeRawStream(_happy_path_events()))))

    assert TextDelta(text="the answer is ") in events
    assert ReasoningDelta(text="thinking about it") in events
    assert ToolCallStarted(id="call_1", name="add") in events
    assert ToolCallArgsDelta(id="call_1", args_delta='{"a": 1,') in events
    assert ToolCallArgsDelta(id="call_1", args_delta=' "b": 3}') in events
    assert ToolCallCompleted(id="call_1") in events


def test_happy_path_completed_message_and_usage() -> None:
    events = asyncio.run(_collect(_FakeClient(_FakeRawStream(_happy_path_events()))))

    completed = [e for e in events if isinstance(e, ModelCallCompleted)]
    assert len(completed) == 1
    event = completed[0]
    assert event.stop_reason == "completed"
    assert event.usage.state == "complete"
    assert event.usage.input_tokens == 30
    assert event.usage.output_tokens == 55
    assert event.usage.reasoning_tokens == 12

    opaque, text, tool_call = event.message.content
    assert isinstance(opaque, OpaqueBlock)
    assert opaque.protocol == "openai_responses"
    assert opaque.data == {
        "type": "reasoning",
        "id": "rs_1",
        "encrypted_content": "opaque-blob",
        "summary": [],
    }
    assert text == TextBlock(text="the answer is ")
    assert tool_call == ToolCallBlock(id="call_1", name="add", arguments={"a": 1, "b": 3})


def test_request_payload_maps_tools_effort_and_summary_flag() -> None:
    client = _FakeClient(_FakeRawStream(_happy_path_events()))
    asyncio.run(_collect(client, effort="low"))

    kwargs = client.responses.last_kwargs
    assert kwargs is not None
    assert kwargs["model"] == "gpt-5.5"
    assert kwargs["tools"] == [
        {
            "type": "function",
            "name": "add",
            "description": "Add two numbers.",
            "parameters": {"type": "object", "properties": {}},
        }
    ]
    assert kwargs["reasoning"] == {"effort": "low", "summary": "auto"}


def test_interruption_after_usage_known_reports_partial_usage() -> None:
    events: list[object] = [
        SimpleNamespace(type="response.output_text.delta", item_id="msg_1", delta="partial answer")
    ]
    client = _FakeClient(_FakeRawStream(events, fail_after=len(events)))
    collected: list[object] = []

    async def _run() -> None:
        adapter = OpenAIResponsesAdapter(client=client)
        async for event in adapter.stream(
            messages=[ModelMessage(role="user", content=(TextBlock(text="hi"),))],
            tools=[],
            model="gpt-5.5",
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
    assert completed[0].stop_reason == "interrupted"
