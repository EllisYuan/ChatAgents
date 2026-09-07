"""ModelPort——llm/ 对项目其余部分的唯一出入口。

按 ``profile.protocol`` 分派到三个适配器之一。**不接受模型名参数**：协议是端点
档案的属性，不是模型的属性（ADR-0025），签名上就没有推断的余地。

HTTP 客户端有两条生命周期，由 :func:`model_port_scope` 的 ``shared_client`` 区分：
服务端预设档案走进程级 LRU 缓存（档案只有两三个，缓存对它们工作良好）；访客自带
的中转站每次运行新建、用完关闭（issue #82）。后者不进缓存有两个理由，都与
ADR-0016「访客的东西不进全局设施」同源——缓存容量是 8，访客一多就互相淘汰；而
淘汰时不关闭客户端，每次淘汰泄漏一个连接池。
"""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Protocol as TypingProtocol

import httpx
import httpx2
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from .adapters.anthropic_messages import AnthropicMessagesAdapter
from .adapters.openai_chat_completions import OpenAIChatCompletionsAdapter
from .adapters.openai_responses import OpenAIResponsesAdapter
from .client_cache import HttpClientCache
from .effort import EffortTier
from .events import ModelEvent
from .message import ModelMessage
from .profile import EndpointProfile
from .tool_schema import ToolLike

_default_client_cache = HttpClientCache()


class ModelPort(TypingProtocol):
    def stream(
        self,
        *,
        messages: Sequence[ModelMessage],
        tools: Sequence[ToolLike],
        model: str,
        effort: EffortTier,
        profile: EndpointProfile,
        system_prompt: str | None = None,
    ) -> AsyncIterator[ModelEvent]: ...


def _build_port(
    profile: EndpointProfile, http_client: httpx.AsyncClient | httpx2.AsyncClient
) -> ModelPort:
    """把一个已经建好的 HTTP 客户端包成对应协议的适配器；不决定它的生命周期。"""

    api_key = profile.api_key.get_secret_value()
    # profile.auth_field 是端点档案声明的鉴权头字段名；SDK 默认头名可能对不上自定义
    # 中转站的约定，显式带上保证密钥确实进了档案指定的那个头。
    auth_headers = {profile.auth_field: api_key}
    # ADR-0015：上游错误原样透传、只重试没回话的调用——SDK 自带的 max_retries 默认值
    # 会对已收到响应的错误（429/5xx）自动重试，与这条纪律冲突，此处关掉。
    # 「只重试没回话的调用」本身是可靠性票（#53-56）的范围，这里先不做。

    if profile.protocol == "anthropic_messages":
        assert isinstance(http_client, httpx.AsyncClient)
        return AnthropicMessagesAdapter(
            client=AsyncAnthropic(
                api_key=api_key,
                base_url=profile.base_url,
                http_client=http_client,
                default_headers=auth_headers,
                max_retries=0,
            )
        )

    assert isinstance(http_client, httpx2.AsyncClient)
    openai_client = AsyncOpenAI(
        api_key=api_key,
        base_url=profile.base_url,
        http_client=http_client,
        default_headers=auth_headers,
        max_retries=0,
    )
    if profile.protocol == "openai_responses":
        return OpenAIResponsesAdapter(client=openai_client)
    return OpenAIChatCompletionsAdapter(client=openai_client)


def _new_http_client(profile: EndpointProfile) -> httpx.AsyncClient | httpx2.AsyncClient:
    """两库并存是预期状态（ADR-0025）：anthropic SDK 用 httpx，openai SDK 用 httpx2。"""

    if profile.protocol == "anthropic_messages":
        return httpx.AsyncClient(base_url=profile.base_url)
    return httpx2.AsyncClient(base_url=profile.base_url)


def get_model_port(
    profile: EndpointProfile, *, client_cache: HttpClientCache | None = None
) -> ModelPort:
    """服务端预设档案的入口——HTTP 客户端取自进程级缓存，调用方不必收尾。"""

    cache = client_cache if client_cache is not None else _default_client_cache
    http_client: httpx.AsyncClient | httpx2.AsyncClient = (
        cache.get_httpx_client(profile.base_url)
        if profile.protocol == "anthropic_messages"
        else cache.get_httpx2_client(profile.base_url)
    )
    return _build_port(profile, http_client)


@asynccontextmanager
async def model_port_scope(
    profile: EndpointProfile, *, shared_client: bool = True
) -> AsyncIterator[ModelPort]:
    """把一次运行要用的 ``ModelPort`` 绑到一个 ``async with`` 块上。

    ``shared_client`` 为真时退出块什么都不关——那个客户端归进程级缓存所有，一次
    运行结束就关掉它会连累下一次运行。为假时（访客自带的中转站）本函数自己建
    客户端、自己关，与工具层的做法同款。
    """

    if shared_client:
        yield get_model_port(profile)
        return

    http_client = _new_http_client(profile)
    try:
        yield _build_port(profile, http_client)
    finally:
        await http_client.aclose()
