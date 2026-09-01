"""努力档位与摘要开关按协议映射参数名（issue #45），不映射取值——三协议同名同序（issue #49 实测）。"""

import pytest
from chat_agents.llm.effort import EFFORT_TIERS, apply_effort, apply_summary_flag


@pytest.mark.parametrize("effort", EFFORT_TIERS)
def test_anthropic_effort_goes_under_output_config(effort: str) -> None:
    """挂 ``output_config`` 而不是 ``thinking``——后者会被上游以
    ``thinking.adaptive.effort: Extra inputs are not permitted`` 拒掉。"""

    payload: dict = {}
    apply_effort("anthropic_messages", payload, effort)
    assert payload == {"output_config": {"effort": effort}}


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


def test_apply_effort_merges_into_existing_output_config_key() -> None:
    payload: dict = {"output_config": {"format": {"type": "text"}}}
    apply_effort("anthropic_messages", payload, "high")
    assert payload == {"output_config": {"format": {"type": "text"}, "effort": "high"}}


def test_anthropic_effort_does_not_touch_thinking() -> None:
    """努力档位与思考模式是两条独立的参数路径，别把档位写进 thinking。"""

    payload: dict = {}
    apply_effort("anthropic_messages", payload, "high")
    assert "thinking" not in payload


def test_anthropic_summary_flag_enables_adaptive_thinking_with_summary() -> None:
    """4.6+ 模型上自适应是唯一的开启方式；``display`` 决定摘要是否回传。"""

    payload: dict = {}
    apply_summary_flag("anthropic_messages", payload)
    assert payload == {"thinking": {"type": "adaptive", "display": "summarized"}}


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
