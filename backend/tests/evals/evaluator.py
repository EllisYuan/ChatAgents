"""批量评测编排与可持久化产出。"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import fmean
from typing import Any

from chat_agents.agent.events import RunEvent

from .dataset import EvalCase, EvalGroupKey
from .judge import JudgePort, JudgeRequest
from .metrics import EvalTrace, MetricScore, deterministic_scores


@dataclass(frozen=True, slots=True)
class EvalSample:
    case: EvalCase
    events: Sequence[RunEvent]
    tool_schemas: Mapping[str, dict[str, Any]] | None = None


@dataclass(frozen=True, slots=True)
class EvalCaseResult:
    scenario_id: str
    group: EvalGroupKey
    scores: dict[str, MetricScore]
    judge_snapshot: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "group": _group_dict(self.group),
            "scores": {
                name: {"score": metric.score, "details": metric.details}
                for name, metric in self.scores.items()
            },
            "judge_snapshot": self.judge_snapshot,
        }


@dataclass(frozen=True, slots=True)
class EvalGroupResult:
    group: EvalGroupKey
    case_count: int
    aggregate_scores: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "group": _group_dict(self.group),
            "case_count": self.case_count,
            "aggregate_scores": self.aggregate_scores,
        }


@dataclass(frozen=True, slots=True)
class EvalReport:
    case_results: tuple[EvalCaseResult, ...]
    group_results: tuple[EvalGroupResult, ...]
    aggregate_scores: dict[str, float]
    judge_snapshots: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_results": [result.to_dict() for result in self.case_results],
            "group_results": [result.to_dict() for result in self.group_results],
            "aggregate_scores": self.aggregate_scores,
            "judge_snapshots": list(self.judge_snapshots),
        }


async def evaluate_batch(samples: Sequence[EvalSample], *, judge: JudgePort) -> EvalReport:
    """对一批运行事件计算七个指标，并在每条结果上记录实际判官快照。"""

    if not samples:
        raise ValueError("评测批次不能为空")

    case_results: list[EvalCaseResult] = []
    for sample in samples:
        trace = EvalTrace.from_events(
            sample.case,
            sample.events,
            tool_schemas=sample.tool_schemas,
        )
        scores = deterministic_scores(trace)
        judged = await judge.evaluate(
            JudgeRequest(
                scenario_id=sample.case.scenario_id,
                query=sample.case.query,
                answer=trace.final_answer,
                observations=trace.observation_text,
                expected_answer=sample.case.expected_answer,
            )
        )
        scores["factual_hallucination_rate"] = MetricScore(
            score=judged.factual_hallucination_rate,
            details={},
        )
        scores["task_completion"] = MetricScore(
            score=judged.task_completion,
            details={},
        )
        case_results.append(
            EvalCaseResult(
                scenario_id=sample.case.scenario_id,
                group=sample.case.group_key,
                scores=scores,
                judge_snapshot=judged.snapshot_id,
            )
        )

    frozen_results = tuple(case_results)
    return EvalReport(
        case_results=frozen_results,
        group_results=_group_results(frozen_results),
        aggregate_scores=_aggregate(frozen_results),
        judge_snapshots=tuple(sorted({result.judge_snapshot for result in frozen_results})),
    )


def _aggregate(results: Sequence[EvalCaseResult]) -> dict[str, float]:
    metric_names = tuple(results[0].scores)
    return {name: fmean(result.scores[name].score for result in results) for name in metric_names}


def _group_results(results: Sequence[EvalCaseResult]) -> tuple[EvalGroupResult, ...]:
    grouped: dict[EvalGroupKey, list[EvalCaseResult]] = {}
    for result in results:
        grouped.setdefault(result.group, []).append(result)
    return tuple(
        EvalGroupResult(
            group=group,
            case_count=len(group_cases),
            aggregate_scores=_aggregate(group_cases),
        )
        for group, group_cases in grouped.items()
    )


def _group_dict(group: EvalGroupKey) -> dict[str, str]:
    return {
        "prompt_version_id": group.prompt_version_id,
        "tool_schema_version_id": group.tool_schema_version_id,
        "effort": group.effort,
    }
