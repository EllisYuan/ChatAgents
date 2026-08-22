"""ModelPort——llm/ 对项目其余部分的唯一出入口。

按 ``profile.protocol`` 分派到三个适配器之一。**不接受模型名参数**：协议是端点
档案的属性，不是模型的属性（ADR-0025），签名上就没有推断的余地。
"""

from collections.abc import AsyncIterator, Sequence
from typing import Any
from typing import Protocol as TypingProtocol

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

_default_client_cache = HttpClientCache()


class ModelPort(TypingProtocol):
    def stream(
        self,
        *,
        messages: Sequence[ModelMessage],
        tools: Sequence[Any],
        model: str,
        effort: EffortTier,
        profile: EndpointProfile,
        system_prompt: str | None = None,
    ) -> AsyncIterator[ModelEvent]: ...


def get_model_port(
    profile: EndpointProfile, *, client_cache: HttpClientCache | None = None
) -> ModelPort:
    cache = client_cache if client_cache is not None else _default_client_cache
    api_key = profile.api_key.get_secret_value()
    # profile.auth_field 是端点档案声明的鉴权头字段名；SDK 默认头名可能对不上自定义
    # 中转站的约定，显式带上保证密钥确实进了档案指定的那个头。
    auth_headers = {profile.auth_field: api_key}
    # ADR-0015：上游错误原样透传、只重试没回话的调用——SDK 自带的 max_retries 默认值
    # 会对已收到响应的错误（429/5xx）自动重试，与这条纪律冲突，此处关掉。
    # 「只重试没回话的调用」本身是可靠性票（#53-56）的范围，这里先不做。

    if profile.protocol == "anthropic_messages":
        http_client = cache.get_httpx_client(profile.base_url)
        client = AsyncAnthropic(
            api_key=api_key,
            base_url=profile.base_url,
            http_client=http_client,
            default_headers=auth_headers,
            max_retries=0,
        )
        return AnthropicMessagesAdapter(client=client)

    http_client2 = cache.get_httpx2_client(profile.base_url)
    openai_client = AsyncOpenAI(
        api_key=api_key,
        base_url=profile.base_url,
        http_client=http_client2,
        default_headers=auth_headers,
        max_retries=0,
    )
    if profile.protocol == "openai_responses":
        return OpenAIResponsesAdapter(client=openai_client)
    return OpenAIChatCompletionsAdapter(client=openai_client)
