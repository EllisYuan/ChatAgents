"""努力档位与摘要开关按协议映射参数名（issue #45），不映射取值——三协议同名同序（issue #49 实测）。"""

import pytest
from chat_agents.llm.effort import EFFORT_TIERS, apply_effort, apply_summary_flag


@pytest.mark.parametrize("effort", EFFORT_TIERS)
def test_anthropic_effort_goes_under_thinking(effort: str) -> None:
    payload: dict = {}
    apply_effort("anthropic_messages", payload, effort)
    assert payload == {"thinking": {"effort": effort}}


@pytest.mark.parametrize("effort", EFFORT_TIERS)
def test_openai_responses_effort_goes_under_reasoning(effort: str) -> None:
    payload: dict = {}
    apply_effort("openai_responses", payload, effort)
    assert payload == {"reasoning": {"effort": effort}}


@pytest.mark.parametrize("effort", EFFORT_TIERS)
def test_openai_chat_completions_effort_is_top_level(effort: str) -> None:
    payload: dict = {}
    apply_effort("openai_chat_completions", payload, effort)
    assert payload == {"reasoning_effort": effort}


def test_apply_effort_merges_into_existing_thinking_key() -> None:
    payload: dict = {"thinking": {"budget_tokens": 1600}}
    apply_effort("anthropic_messages", payload, "high")
    assert payload == {"thinking": {"budget_tokens": 1600, "effort": "high"}}


def test_anthropic_summary_flag_sets_display_summarized() -> None:
    payload: dict = {}
    apply_summary_flag("anthropic_messages", payload)
    assert payload == {"thinking": {"display": "summarized"}}


def test_openai_responses_summary_flag_sets_reasoning_summary_auto() -> None:
    payload: dict = {}
    apply_summary_flag("openai_responses", payload)
    assert payload == {"reasoning": {"summary": "auto"}}


def test_openai_chat_completions_summary_flag_writes_nothing() -> None:
    payload: dict = {}
    apply_summary_flag("openai_chat_completions", payload)
    assert payload == {}


def test_summary_flag_merges_into_existing_reasoning_key() -> None:
    payload: dict = {"reasoning": {"effort": "xhigh"}}
    apply_summary_flag("openai_responses", payload)
    assert payload == {"reasoning": {"effort": "xhigh", "summary": "auto"}}
