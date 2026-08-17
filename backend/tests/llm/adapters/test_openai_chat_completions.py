"""OpenAIChatCompletionsAdapter：假 SDK 客户端驱动，不经 HTTP。

ADR-0017：这个协议一概不采原生推理——中转站自造的 ``reasoning_content`` 读到不消费。
"""

import asyncio
from types import SimpleNamespace

import pytest
from chat_agents.llm.adapters.openai_chat_completions import OpenAIChatCompletionsAdapter
from chat_agents.llm.effort import EffortTier
from chat_agents.llm.events import (
    ModelCallCompleted,
    ReasoningDelta,
    TextDelta,
    ToolCallArgsDelta,
    ToolCallCompleted,
    ToolCallStarted,
)
from chat_agents.llm.message import ModelMessage, TextBlock, ToolCallBlock
from chat_agents.llm.profile import EndpointProfile
from chat_agents.tools.types import ToolSpec
from pydantic import SecretStr


def _profile() -> EndpointProfile:
    return EndpointProfile(
        name="official",
        protocol="openai_chat_completions",
        base_url="https://api.openai.com/v1",
        auth_field="Authorization",
        api_key=SecretStr("sk-test"),
    )


class _FakeRawStream:
    def __init__(self, chunks: list[object], *, fail_after: int | None = None) -> None:
        self._chunks = chunks
        self._fail_after = fail_after

    def __aiter__(self) -> "_FakeRawStream":
        self._iter = iter(self._chunks)
        self._yielded = 0
        return self

    async def __anext__(self) -> object:
        if self._fail_after is not None and self._yielded >= self._fail_after:
            raise ConnectionError("upstream dropped the connection")
        try:
            chunk = next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc
        self._yielded += 1
        return chunk


class _FakeCompletions:
    def __init__(self, stream: _FakeRawStream) -> None:
        self._stream = stream
        self.last_kwargs: dict | None = None

    async def create(self, **kwargs: object) -> _FakeRawStream:
        self.last_kwargs = kwargs
        return self._stream


class _FakeClient:
    def __init__(self, stream: _FakeRawStream) -> None:
        self.chat = SimpleNamespace(completions=_FakeCompletions(stream))


def _delta(**kwargs: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "content": None,
        "tool_calls": None,
        "role": None,
        "reasoning_content": None,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


def _chunk(*, choices: list[SimpleNamespace], usage: object | None = None) -> SimpleNamespace:
    return SimpleNamespace(choices=choices, usage=usage)


def _tool_call_delta(
    index: int, *, id: str | None = None, name: str | None = None, arguments: str = ""
) -> SimpleNamespace:
    function = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=id, function=function)


def _happy_path_chunks() -> list[object]:
    return [
        _chunk(
            choices=[SimpleNamespace(delta=_delta(role="assistant"), finish_reason=None, index=0)]
        ),
        _chunk(
            choices=[
                SimpleNamespace(
                    delta=_delta(content="the answer is ", reasoning_content="中转站自造，不消费"),
                    finish_reason=None,
                    index=0,
                )
            ]
        ),
        _chunk(
            choices=[
                SimpleNamespace(
                    delta=_delta(
                        tool_calls=[_tool_call_delta(0, id="call_1", name="add", arguments="")]
                    ),
                    finish_reason=None,
                    index=0,
                )
            ]
        ),
        _chunk(
            choices=[
                SimpleNamespace(
                    delta=_delta(tool_calls=[_tool_call_delta(0, arguments='{"a": 1, "b": 3}')]),
                    finish_reason=None,
                    index=0,
                )
            ]
        ),
        _chunk(choices=[SimpleNamespace(delta=_delta(), finish_reason="tool_calls", index=0)]),
        _chunk(
            choices=[],
            usage=SimpleNamespace(
                prompt_tokens=20, completion_tokens=8, completion_tokens_details=None
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
    adapter = OpenAIChatCompletionsAdapter(client=client)
    messages = [ModelMessage(role="user", content=(TextBlock(text="what is 1+3?"),))]
    events: list[object] = []
    async for event in adapter.stream(
        messages=messages, tools=[_tool()], model="gpt-5.5", effort=effort, profile=_profile()
    ):
        events.append(event)
    return events


def test_happy_path_emits_text_and_tool_call_deltas_but_no_reasoning() -> None:
    events = asyncio.run(_collect(_FakeClient(_FakeRawStream(_happy_path_chunks()))))

    assert TextDelta(text="the answer is ") in events
    assert ToolCallStarted(id="call_1", name="add") in events
    assert ToolCallArgsDelta(id="call_1", args_delta='{"a": 1, "b": 3}') in events
    assert ToolCallCompleted(id="call_1") in events
    assert not any(isinstance(e, ReasoningDelta) for e in events)


def test_happy_path_completed_message_has_no_opaque_block() -> None:
    events = asyncio.run(_collect(_FakeClient(_FakeRawStream(_happy_path_chunks()))))
    completed = [e for e in events if isinstance(e, ModelCallCompleted)]
    assert len(completed) == 1
    event = completed[0]

    assert event.stop_reason == "tool_calls"
    assert event.usage.state == "complete"
    assert event.usage.input_tokens == 20
    assert event.usage.output_tokens == 8
    assert event.usage.reasoning_tokens is None

    text, tool_call = event.message.content
    assert text == TextBlock(text="the answer is ")
    assert tool_call == ToolCallBlock(id="call_1", name="add", arguments={"a": 1, "b": 3})


def test_request_payload_maps_tools_and_effort_but_no_summary_key() -> None:
    client = _FakeClient(_FakeRawStream(_happy_path_chunks()))
    asyncio.run(_collect(client, effort="high"))

    kwargs = client.chat.completions.last_kwargs
    assert kwargs is not None
    assert kwargs["model"] == "gpt-5.5"
    assert kwargs["reasoning_effort"] == "high"
    assert "reasoning" not in kwargs
    assert kwargs["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "add",
                "description": "Add two numbers.",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]
    assert kwargs["stream_options"] == {"include_usage": True}


def test_interruption_reports_unavailable_usage_never_zero() -> None:
    chunks = _happy_path_chunks()[:2]
    client = _FakeClient(_FakeRawStream(chunks, fail_after=len(chunks)))
    collected: list[object] = []

    async def _run() -> None:
        adapter = OpenAIChatCompletionsAdapter(client=client)
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
    assert usage.reasoning_tokens is None
