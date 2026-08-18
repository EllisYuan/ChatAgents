from __future__ import annotations

from chat_agents.agent.versioning import prompt_observation_attributes
from chat_agents.llm.adapters.anthropic_messages import build_request as build_anthropic_request
from chat_agents.llm.adapters.openai_chat_completions import build_request as build_chat_request
from chat_agents.llm.adapters.openai_responses import build_request as build_responses_request
from chat_agents.llm.message import ModelMessage, TextBlock

_MESSAGES = [ModelMessage(role="user", content=(TextBlock(text="你好"),))]


def test_system_prompt_is_not_added_to_runner_history() -> None:
    anthropic = build_anthropic_request(
        messages=_MESSAGES,
        tools=[],
        model="model",
        effort="low",
        system_prompt="内部提示词",
    )
    responses = build_responses_request(
        messages=_MESSAGES,
        tools=[],
        model="model",
        effort="low",
        system_prompt="内部提示词",
    )
    chat = build_chat_request(
        messages=_MESSAGES,
        tools=[],
        model="model",
        effort="low",
        system_prompt="内部提示词",
    )

    assert [message.role for message in _MESSAGES] == ["user"]
    assert anthropic["system"] == "内部提示词"
    assert responses["instructions"] == "内部提示词"
    assert chat["messages"][0] == {"role": "system", "content": "内部提示词"}
    assert chat["messages"][1]["role"] == "user"


def test_observation_keeps_only_prompt_reference_and_version_metadata() -> None:
    attributes = prompt_observation_attributes("system@v1")

    assert attributes == {
        "input.value": "{system_prompt@system@v1}",
        "llm.prompt_template.version": "system@v1",
        "llm.prompt_template.variables": ["date", "step_budget"],
    }
    assert "内部提示词" not in attributes["input.value"]
