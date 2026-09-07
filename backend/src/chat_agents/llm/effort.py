"""努力档位——四档，与 Claude 的 effort 档位同名同序（issue #49 实测确认）。

只映射**参数名**，不映射取值：三协议接受同一套字面量，差异只在 JSON 请求体里
这个值该挂在哪个 key 路径下。摘要开关同理——只改返回形态，不进 ADR-0011 的
版本化体系（ADR-0017）。
"""

from typing import Any, Final, Literal

from .protocol import Protocol

EffortTier = Literal["low", "medium", "high", "xhigh"]

EFFORT_TIERS: Final[tuple[EffortTier, ...]] = ("low", "medium", "high", "xhigh")


def apply_effort(protocol: Protocol, payload: dict[str, Any], effort: EffortTier) -> None:
    """原地修改 ``payload``，把努力档位写到该协议对应的参数路径上。

    ``anthropic_messages`` 的档位挂在顶层 ``output_config`` 下，不在 ``thinking``
    里——写进 ``thinking`` 会被上游以 ``thinking.adaptive.effort: Extra inputs are
    not permitted`` 拒掉（2026-09-01 实测 claude-opus-5 与 claude-sonnet-5）。
    ``thinking`` 只承载思考模式与摘要开关，两者是不同的参数路径。
    """
    if protocol == "anthropic_messages":
        payload.setdefault("output_config", {})["effort"] = effort
    elif protocol == "openai_responses":
        payload.setdefault("reasoning", {})["effort"] = effort
    elif protocol == "openai_chat_completions":
        payload["reasoning_effort"] = effort


def apply_summary_flag(protocol: Protocol, payload: dict[str, Any]) -> None:
    """原地修改 ``payload``，按协议开启显示摘要（ADR-0017）。"""
    if protocol == "anthropic_messages":
        # 自适应思考是 4.6+ 模型上唯一的开启方式；``display`` 决定摘要是否回传。
        thinking = payload.setdefault("thinking", {})
        thinking["type"] = "adaptive"
        thinking["display"] = "summarized"
    elif protocol == "openai_responses":
        payload.setdefault("reasoning", {})["summary"] = "auto"
    # openai_chat_completions：不采摘要，不写任何字段。
