"""窄测试：只测 SSE 解析与超时行为，本项目唯一区分 httpx 与 httpx2 的地方（ADR-0025）。

回放注入点在 ModelPort 边界，不在 HTTP transport（ADR-0025）——那一层测不到
「那串字节怎么变成事件」。这里补一层十几行的窄测试：anthropic 侧用
``httpx.MockTransport``、openai 侧用 ``httpx2.MockTransport``，覆盖 SSE 解析
与超时行为。**项目其余任何地方都不应该出现区分两库的代码**——业务语义（用量
三态、工具序列化、摘要开关……）已经在各自的假客户端测试里覆盖，这里只验证
「真实 SDK 客户端经真实（伪造）HTTP 响应确实能喂到我们的适配器」。
"""

import asyncio

import httpx
import httpx2
import pytest
from anthropic import APITimeoutError as AnthropicAPITimeoutError
from anthropic import AsyncAnthropic
from chat_agents.llm.adapters.anthropic_messages import AnthropicMessagesAdapter
from chat_agents.llm.adapters.openai_chat_completions import OpenAIChatCompletionsAdapter
from chat_agents.llm.adapters.openai_responses import OpenAIResponsesAdapter
from chat_agents.llm.events import ModelCallCompleted, TextDelta
from chat_agents.llm.message import ModelMessage, TextBlock
from chat_agents.llm.profile import EndpointProfile
from openai import APITimeoutError as OpenAIAPITimeoutError
from openai import AsyncOpenAI
from pydantic import SecretStr

_ANTHROPIC_SSE_BODY = (
    b"event: message_start\n"
    b'data: {"type":"message_start","message":{"id":"msg_1","type":"message","role":"assistant",'
    b'"content":[],"model":"claude-sonnet-5","stop_reason":null,"stop_sequence":null,'
    b'"usage":{"input_tokens":10,"output_tokens":0}}}\n\n'
    b"event: content_block_start\n"
    b'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}\n\n'
    b"event: content_block_delta\n"
    b'data: {"type":"content_block_delta","index":0,'
    b'"delta":{"type":"text_delta","text":"hello from SSE"}}\n\n'
    b"event: content_block_stop\n"
    b'data: {"type":"content_block_stop","index":0}\n\n'
    b"event: message_delta\n"
    b'data: {"type":"message_delta","delta":{"stop_reason":"end_turn","stop_sequence":null},'
    b'"usage":{"output_tokens":5}}\n\n'
    b"event: message_stop\n"
    b'data: {"type":"message_stop"}\n\n'
)

_OPENAI_SSE_BODY = (
    b'data: {"id":"c1","object":"chat.completion.chunk","created":0,"model":"gpt-5.5",'
    b'"choices":[{"index":0,"delta":{"role":"assistant","content":"hello from SSE"},'
    b'"finish_reason":null}]}\n\n'
    b'data: {"id":"c1","object":"chat.completion.chunk","created":0,"model":"gpt-5.5",'
    b'"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
    b'data: {"id":"c1","object":"chat.completion.chunk","created":0,"model":"gpt-5.5",'
    b'"choices":[],"usage":{"prompt_tokens":10,"completion_tokens":5}}\n\n'
    b"data: [DONE]\n\n"
)


_OPENAI_RESPONSES_SSE_BODY = (
    b"event: response.completed\n"
    b'data: {"type":"response.completed","sequence_number":0,"response":{'
    b'"id":"resp_1","created_at":0.0,"model":"gpt-5.5","object":"response",'
    b'"output":[{"id":"msg_1","type":"message","status":"completed","role":"assistant",'
    b'"content":[{"type":"output_text","text":"hello from SSE","annotations":[],"logprobs":null}]}],'
    b'"parallel_tool_calls":true,"tool_choice":"auto","tools":[],"status":"completed",'
    b'"usage":{"input_tokens":10,"output_tokens":5,"total_tokens":15,'
    b'"input_tokens_details":{"cached_tokens":0,"cache_write_tokens":0},'
    b'"output_tokens_details":{"reasoning_tokens":0}}}}\n\n'
)


def _anthropic_profile() -> EndpointProfile:
    return EndpointProfile(
        name="anthropic-official",
        protocol="anthropic_messages",
        base_url="https://api.anthropic.com",
        auth_field="x-api-key",
        api_key=SecretStr("sk-test"),
    )


def _openai_profile() -> EndpointProfile:
    return EndpointProfile(
        name="openai-official",
        protocol="openai_chat_completions",
        base_url="https://api.openai.com/v1",
        auth_field="Authorization",
        api_key=SecretStr("sk-test"),
    )


def test_anthropic_sse_parses_via_real_httpx_mock_transport() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=_ANTHROPIC_SSE_BODY, headers={"content-type": "text/event-stream"}
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AsyncAnthropic(api_key="sk-test", http_client=http_client)
    adapter = AnthropicMessagesAdapter(client=client)

    async def _run() -> list[object]:
        events = []
        async for event in adapter.stream(
            messages=[ModelMessage(role="user", content=(TextBlock(text="hi"),))],
            tools=[],
            model="claude-sonnet-5",
            effort="medium",
            profile=_anthropic_profile(),
        ):
            events.append(event)
        await http_client.aclose()
        return events

    events = asyncio.run(_run())
    assert TextDelta(text="hello from SSE") in events
    completed = [e for e in events if isinstance(e, ModelCallCompleted)]
    assert completed[0].usage.state == "complete"
    assert completed[0].usage.input_tokens == 10


def test_anthropic_timeout_reports_interruption_not_a_hang() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("upstream took too long", request=request)

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AsyncAnthropic(api_key="sk-test", http_client=http_client, max_retries=0)
    adapter = AnthropicMessagesAdapter(client=client)

    async def _run() -> list[object]:
        events = []
        try:
            async for event in adapter.stream(
                messages=[ModelMessage(role="user", content=(TextBlock(text="hi"),))],
                tools=[],
                model="claude-sonnet-5",
                effort="medium",
                profile=_anthropic_profile(),
            ):
                events.append(event)
        finally:
            await http_client.aclose()
        return events

    with pytest.raises(AnthropicAPITimeoutError):
        asyncio.run(_run())


def test_openai_sse_parses_via_real_httpx2_mock_transport() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200, content=_OPENAI_SSE_BODY, headers={"content-type": "text/event-stream"}
        )

    http_client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    client = AsyncOpenAI(api_key="sk-test", http_client=http_client)
    adapter = OpenAIChatCompletionsAdapter(client=client)

    async def _run() -> list[object]:
        events = []
        async for event in adapter.stream(
            messages=[ModelMessage(role="user", content=(TextBlock(text="hi"),))],
            tools=[],
            model="gpt-5.5",
            effort="medium",
            profile=_openai_profile(),
        ):
            events.append(event)
        await http_client.aclose()
        return events

    events = asyncio.run(_run())
    assert TextDelta(text="hello from SSE") in events
    completed = [e for e in events if isinstance(e, ModelCallCompleted)]
    assert completed[0].usage.state == "complete"
    assert completed[0].usage.input_tokens == 10


def _openai_responses_profile() -> EndpointProfile:
    return EndpointProfile(
        name="openai-official",
        protocol="openai_responses",
        base_url="https://api.openai.com/v1",
        auth_field="Authorization",
        api_key=SecretStr("sk-test"),
    )


def test_openai_responses_sse_parses_via_real_httpx2_mock_transport() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200, content=_OPENAI_RESPONSES_SSE_BODY, headers={"content-type": "text/event-stream"}
        )

    http_client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    client = AsyncOpenAI(api_key="sk-test", http_client=http_client)
    adapter = OpenAIResponsesAdapter(client=client)

    async def _run() -> list[object]:
        events = []
        async for event in adapter.stream(
            messages=[ModelMessage(role="user", content=(TextBlock(text="hi"),))],
            tools=[],
            model="gpt-5.5",
            effort="medium",
            profile=_openai_responses_profile(),
        ):
            events.append(event)
        await http_client.aclose()
        return events

    events = asyncio.run(_run())
    completed = [e for e in events if isinstance(e, ModelCallCompleted)]
    assert len(completed) == 1
    assert TextBlock(text="hello from SSE") in completed[0].message.content
    assert completed[0].usage.state == "complete"
    assert completed[0].usage.input_tokens == 10


def test_openai_timeout_reports_interruption_not_a_hang() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("upstream took too long", request=request)

    http_client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    client = AsyncOpenAI(api_key="sk-test", http_client=http_client, max_retries=0)
    adapter = OpenAIChatCompletionsAdapter(client=client)

    async def _run() -> list[object]:
        events = []
        try:
            async for event in adapter.stream(
                messages=[ModelMessage(role="user", content=(TextBlock(text="hi"),))],
                tools=[],
                model="gpt-5.5",
                effort="medium",
                profile=_openai_profile(),
            ):
                events.append(event)
        finally:
            await http_client.aclose()
        return events

    with pytest.raises(OpenAIAPITimeoutError):
        asyncio.run(_run())
