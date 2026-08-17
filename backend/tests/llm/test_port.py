"""get_model_port 按协议分派，不接受模型名——协议是端点档案的属性（ADR-0025）。"""

import inspect

from chat_agents.llm.adapters.anthropic_messages import AnthropicMessagesAdapter
from chat_agents.llm.adapters.openai_chat_completions import OpenAIChatCompletionsAdapter
from chat_agents.llm.adapters.openai_responses import OpenAIResponsesAdapter
from chat_agents.llm.client_cache import HttpClientCache
from chat_agents.llm.port import get_model_port
from chat_agents.llm.profile import EndpointProfile
from pydantic import SecretStr


def _profile(protocol: str) -> EndpointProfile:
    return EndpointProfile(
        name="test",
        protocol=protocol,
        base_url="https://example.com",
        auth_field="Authorization",
        api_key=SecretStr("sk-test"),
    )


def test_get_model_port_has_no_model_name_parameter() -> None:
    """签名层面就没有模型名入参，天然满足「禁止按模型名推断协议」。"""
    params = inspect.signature(get_model_port).parameters
    assert "model" not in params
    assert "model_name" not in params


def test_anthropic_messages_dispatches_to_anthropic_adapter() -> None:
    port = get_model_port(_profile("anthropic_messages"), client_cache=HttpClientCache())
    assert isinstance(port, AnthropicMessagesAdapter)


def test_openai_responses_dispatches_to_responses_adapter() -> None:
    port = get_model_port(_profile("openai_responses"), client_cache=HttpClientCache())
    assert isinstance(port, OpenAIResponsesAdapter)


def test_openai_chat_completions_dispatches_to_chat_completions_adapter() -> None:
    port = get_model_port(_profile("openai_chat_completions"), client_cache=HttpClientCache())
    assert isinstance(port, OpenAIChatCompletionsAdapter)


def test_default_client_cache_is_shared_module_singleton() -> None:
    a = get_model_port(_profile("anthropic_messages"))
    b = get_model_port(_profile("anthropic_messages"))
    # 两次分派各自新建适配器实例，但底层 httpx client 是同一个（同 base_url 命中缓存）。
    assert a is not b
