"""五个零成本确定性指标。"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from chat_agents.agent.events import RunCompleted, RunEvent, ToolFinished, ToolStarted
from chat_agents.agent.step_budget import STEP_BUDGETS
from chat_agents.llm.message import TextBlock
from chat_agents.tools.registry import TOOL_SPECS
from jsonschema import Draft202012Validator

from .dataset import EvalCase

_URL_RE = re.compile(r"https?://[^\s<>()\[\]{}\"']+")
_NETWORK_TOOLS = frozenset({"web_search", "web_reader"})


@dataclass(frozen=True, slots=True)
class MetricScore:
    score: float
    details: dict[str, Any]

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("评测分数必须位于 [0, 1]")


@dataclass(frozen=True, slots=True)
class EvalTrace:
    case: EvalCase
    final_answer: str
    tool_calls: tuple[ToolStarted, ...]
    observations: tuple[str, ...]
    iteration_count: int
    tool_schemas: Mapping[str, dict[str, Any]]

    @classmethod
    def from_events(
        cls,
        case: EvalCase,
        events: Sequence[RunEvent],
        *,
        tool_schemas: Mapping[str, dict[str, Any]] | None = None,
    ) -> EvalTrace:
        completed = [event for event in events if isinstance(event, RunCompleted)]
        if not completed:
            raise ValueError(f"场景 {case.scenario_id} 没有 RunCompleted，无法评分")
        final_message = completed[-1].message
        final_answer = "".join(
            block.text for block in final_message.content if isinstance(block, TextBlock)
        )
        tool_calls = tuple(event for event in events if isinstance(event, ToolStarted))
        observations = tuple(event.result for event in events if isinstance(event, ToolFinished))
        iteration_count = max((event.iteration for event in events), default=0)
        return cls(
            case=case,
            final_answer=final_answer,
            tool_calls=tool_calls,
            observations=observations,
            iteration_count=iteration_count,
            tool_schemas=(
                dict(tool_schemas)
                if tool_schemas is not None
                else {name: spec.parameters for name, spec in TOOL_SPECS.items()}
            ),
        )

    @property
    def observation_text(self) -> str:
        return "\n\n".join(self.observations)


def deterministic_scores(trace: EvalTrace) -> dict[str, MetricScore]:
    """计算五个不调用判官的常驻指标。"""

    return {
        "argument_compliance": argument_compliance(trace),
        "system_constraint_adherence": system_constraint_adherence(trace),
        "tool_trigger_rate": tool_trigger_rate(trace),
        "trajectory_efficiency": trajectory_efficiency(trace),
        "citation_faithfulness": citation_faithfulness(trace),
    }


def argument_compliance(trace: EvalTrace) -> MetricScore:
    if not trace.tool_calls:
        return MetricScore(score=1.0, details={"valid_calls": 0, "total_calls": 0})
    valid = 0
    for call in trace.tool_calls:
        schema = trace.tool_schemas.get(call.name)
        if schema is not None and Draft202012Validator(schema).is_valid(call.arguments):
            valid += 1
    total = len(trace.tool_calls)
    return MetricScore(
        score=valid / total,
        details={"valid_calls": valid, "total_calls": total},
    )


def system_constraint_adherence(trace: EvalTrace) -> MetricScore:
    soft_budget = STEP_BUDGETS[trace.case.effort].soft
    actual = trace.iteration_count
    score = 1.0 if actual <= soft_budget else soft_budget / actual
    return MetricScore(
        score=score,
        details={"soft_budget": soft_budget, "actual_iterations": actual},
    )


def tool_trigger_rate(trace: EvalTrace) -> MetricScore:
    used_network_tool = any(call.name in _NETWORK_TOOLS for call in trace.tool_calls)
    correct = used_network_tool == trace.case.should_use_tools
    return MetricScore(
        score=float(correct),
        details={
            "should_use_tools": trace.case.should_use_tools,
            "used_network_tool": used_network_tool,
        },
    )


def trajectory_efficiency(trace: EvalTrace) -> MetricScore:
    hard_cap = STEP_BUDGETS[trace.case.effort].hard_cap
    hard_cap_reached = trace.iteration_count >= hard_cap

    reader_urls = [
        str(call.arguments.get("url", "")) for call in trace.tool_calls if call.name == "web_reader"
    ]
    repeated_reader_url_count = sum(count - 1 for count in Counter(reader_urls).values())

    last_search = max(
        (index for index, call in enumerate(trace.tool_calls) if call.name == "web_search"),
        default=-1,
    )
    last_reader = max(
        (index for index, call in enumerate(trace.tool_calls) if call.name == "web_reader"),
        default=-1,
    )
    search_without_followup_read = last_search >= 0 and last_reader < last_search

    hard_cap_score = 0.0 if hard_cap_reached else 1.0
    repeated_read_score = 1.0 / (1 + repeated_reader_url_count)
    search_read_score = 0.0 if search_without_followup_read else 1.0
    score = (hard_cap_score + repeated_read_score + search_read_score) / 3
    return MetricScore(
        score=score,
        details={
            "hard_cap_reached": hard_cap_reached,
            "repeated_reader_url_count": repeated_reader_url_count,
            "search_without_followup_read": search_without_followup_read,
        },
    )


def citation_faithfulness(trace: EvalTrace) -> MetricScore:
    answer_urls = _urls(trace.final_answer)
    observed_urls = _urls(trace.observation_text)
    supported = answer_urls & observed_urls
    score = len(supported) / len(answer_urls) if answer_urls else 1.0
    return MetricScore(
        score=score,
        details={
            "answer_citations": sorted(answer_urls),
            "observed_urls": sorted(observed_urls),
            "supported_citations": sorted(supported),
        },
    )


def _urls(text: str) -> set[str]:
    return {match.group(0).rstrip(".,;:!?，。；：！？") for match in _URL_RE.finditer(text)}
