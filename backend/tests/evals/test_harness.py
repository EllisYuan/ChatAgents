"""评测骨架的公共行为（issue #60）。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from chat_agents.agent.events import (
    IterationStarted,
    ReasoningDelta,
    RunCompleted,
    ToolFinished,
    ToolStarted,
)
from chat_agents.agent.step_budget import STEP_BUDGETS
from chat_agents.agent.tool_execution import RunToolContext
from chat_agents.llm.events import ModelCallCompleted, ModelEvent, Usage
from chat_agents.llm.message import ModelMessage, TextBlock
from chat_agents.llm.profile import EndpointProfile
from pydantic import SecretStr

from .dataset import EvalCase, EvalDataset, EvalGroupKey
from .evaluator import EvalSample, evaluate_batch
from .judge import (
    DEFAULT_JUDGE_SNAPSHOT,
    JudgeRequest,
    JudgeScores,
    ModelPortJudge,
    judge_snapshot_from_env,
)
from .vendor_fixtures import FrozenVendorFixtureStore

pytestmark = pytest.mark.eval


class FakeJudge:
    def __init__(self) -> None:
        self.requests: list[JudgeRequest] = []

    async def evaluate(self, request: JudgeRequest) -> JudgeScores:
        self.requests.append(request)
        return JudgeScores(
            factual_hallucination_rate=0.25,
            task_completion=0.9,
            snapshot_id="judge-snapshot-2026-08-18",
        )


def _answer(text: str) -> ModelMessage:
    return ModelMessage(role="assistant", content=(TextBlock(text=text),))


def test_dataset_groups_only_by_three_version_axes() -> None:
    cases = [
        EvalCase(
            scenario_id="fresh-news",
            query="第一种问法",
            prompt_version_id="prompt-a",
            tool_schema_version_id="tools-a",
            effort="low",
            should_use_tools=True,
        ),
        EvalCase(
            scenario_id="fresh-news-reworded",
            query="完全不同的查询文本",
            prompt_version_id="prompt-a",
            tool_schema_version_id="tools-a",
            effort="low",
            should_use_tools=True,
        ),
        EvalCase(
            scenario_id="fresh-news-high",
            query="第一种问法",
            prompt_version_id="prompt-a",
            tool_schema_version_id="tools-a",
            effort="high",
            should_use_tools=True,
        ),
    ]

    groups = EvalDataset(cases).grouped()

    low = EvalGroupKey("prompt-a", "tools-a", "low")
    high = EvalGroupKey("prompt-a", "tools-a", "high")
    assert set(groups) == {low, high}
    assert [case.scenario_id for case in groups[low]] == [
        "fresh-news",
        "fresh-news-reworded",
    ]


def test_vendor_fixtures_freeze_tavily_and_jina_by_scenario_id(tmp_path: Path) -> None:
    fixture_path = tmp_path / "vendors.json"
    fixture_path.write_text(
        json.dumps(
            {
                "scenarios": {
                    "fresh-news": {
                        "tavily_responses": [
                            [
                                {
                                    "title": "来源 A",
                                    "url": "https://example.test/a",
                                    "content": "搜索摘要",
                                    "score": 0.9,
                                }
                            ]
                        ],
                        "jina_responses": {"https://example.test/a": "# 来源 A\n\n冻结的正文"},
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = FrozenVendorFixtureStore.from_file(fixture_path)
    specs = store.tool_specs("fresh-news")
    ctx = RunToolContext(run_id="eval-run", http_client=object())

    search_result = asyncio.run(
        specs["web_search"].handler({"query": "模型每次都可能生成不同查询", "max_results": 5}, ctx)
    )
    reader_result = asyncio.run(specs["web_reader"].handler({"url": "https://example.test/a"}, ctx))

    assert "https://example.test/a" in search_result.model_text
    assert reader_result.model_text == "# 来源 A\n\n冻结的正文"
    assert store.opened_scenario_ids == ["fresh-news"]


def test_batch_evaluation_produces_exactly_seven_metrics_and_snapshot() -> None:
    researched = EvalCase(
        scenario_id="researched",
        query="查证事实",
        prompt_version_id="prompt-v1",
        tool_schema_version_id="tools-v1",
        effort="medium",
        should_use_tools=True,
    )
    direct = EvalCase(
        scenario_id="direct",
        query="把 1 加 1",
        prompt_version_id="prompt-v1",
        tool_schema_version_id="tools-v1",
        effort="medium",
        should_use_tools=False,
    )
    researched_events = [
        IterationStarted(run_id="run-a", iteration=1),
        ToolStarted(
            run_id="run-a",
            iteration=1,
            tool_call_id="search-1",
            name="web_search",
            arguments={"query": "事实", "max_results": 3},
        ),
        ToolFinished(
            run_id="run-a",
            iteration=1,
            tool_call_id="search-1",
            name="web_search",
            result="来源：https://example.test/a",
        ),
        ToolStarted(
            run_id="run-a",
            iteration=1,
            tool_call_id="read-1",
            name="web_reader",
            arguments={"url": "https://example.test/a"},
        ),
        ToolFinished(
            run_id="run-a",
            iteration=1,
            tool_call_id="read-1",
            name="web_reader",
            result="https://example.test/a 的正文：事实成立",
        ),
        ReasoningDelta(
            run_id="run-a",
            iteration=1,
            text="显示摘要里的 https://summary.test/ 不应参与打分",
        ),
        IterationStarted(run_id="run-a", iteration=2),
        RunCompleted(
            run_id="run-a",
            iteration=2,
            message=_answer("事实成立。[来源](https://example.test/a)"),
        ),
    ]
    direct_events = [
        IterationStarted(run_id="run-b", iteration=1),
        RunCompleted(run_id="run-b", iteration=1, message=_answer("2")),
    ]
    judge = FakeJudge()

    report = asyncio.run(
        evaluate_batch(
            [
                EvalSample(case=researched, events=researched_events),
                EvalSample(case=direct, events=direct_events),
            ],
            judge=judge,
        )
    )

    expected_names = {
        "argument_compliance",
        "system_constraint_adherence",
        "tool_trigger_rate",
        "trajectory_efficiency",
        "citation_faithfulness",
        "factual_hallucination_rate",
        "task_completion",
    }
    assert set(report.aggregate_scores) == expected_names
    assert len(report.case_results) == 2
    assert len(judge.requests) == 2
    assert report.judge_snapshots == ("judge-snapshot-2026-08-18",)
    assert all(
        result.judge_snapshot == "judge-snapshot-2026-08-18" for result in report.case_results
    )
    assert "tool_misselection_rate" not in report.to_dict()["aggregate_scores"]

    first = report.case_results[0]
    assert first.scores["argument_compliance"].score == 1.0
    assert first.scores["system_constraint_adherence"].score == 1.0
    assert first.scores["tool_trigger_rate"].score == 1.0
    assert first.scores["trajectory_efficiency"].score == 1.0
    assert first.scores["citation_faithfulness"].score == 1.0
    assert first.scores["factual_hallucination_rate"].score == 0.25
    assert first.scores["task_completion"].score == 0.9
    assert judge.requests[0].answer == "事实成立。[来源](https://example.test/a)"
    assert "summary.test" not in judge.requests[0].observations


def test_deterministic_metrics_respond_to_violations() -> None:
    case = EvalCase(
        scenario_id="violations",
        query="不需要联网的问题",
        prompt_version_id="prompt-v1",
        tool_schema_version_id="tools-v1",
        effort="low",
        should_use_tools=False,
    )
    events: list[Any] = [
        IterationStarted(run_id="run", iteration=iteration) for iteration in range(1, 5)
    ]
    events.extend(
        [
            ToolStarted(
                run_id="run",
                iteration=1,
                tool_call_id="search",
                name="web_search",
                arguments={"query": "多余搜索", "max_results": 99},
            ),
            ToolFinished(
                run_id="run",
                iteration=1,
                tool_call_id="search",
                name="web_search",
                result="只观察到 https://example.test/a",
            ),
            RunCompleted(
                run_id="run",
                iteration=4,
                message=_answer(
                    "[已观察](https://example.test/a) [未观察](https://example.test/b)"
                ),
            ),
        ]
    )

    report = asyncio.run(evaluate_batch([EvalSample(case=case, events=events)], judge=FakeJudge()))
    scores = report.case_results[0].scores

    assert scores["argument_compliance"].score == 0.0
    assert scores["system_constraint_adherence"].score == 0.75
    assert scores["tool_trigger_rate"].score == 0.0
    assert scores["trajectory_efficiency"].score == pytest.approx(1 / 3)
    assert scores["citation_faithfulness"].score == 0.5


def test_argument_compliance_uses_the_schema_for_that_version() -> None:
    case = EvalCase(
        scenario_id="old-schema",
        query="搜索",
        prompt_version_id="prompt-v1",
        tool_schema_version_id="tools-old",
        effort="low",
        should_use_tools=True,
    )
    events = [
        IterationStarted(run_id="run", iteration=1),
        ToolStarted(
            run_id="run",
            iteration=1,
            tool_call_id="search",
            name="web_search",
            arguments={"query": "查询", "max_results": 99},
        ),
        RunCompleted(run_id="run", iteration=1, message=_answer("完成")),
    ]
    old_schema = {
        "web_search": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": ["query"],
            "additionalProperties": False,
        }
    }

    report = asyncio.run(
        evaluate_batch(
            [EvalSample(case=case, events=events, tool_schemas=old_schema)],
            judge=FakeJudge(),
        )
    )

    assert report.case_results[0].scores["argument_compliance"].score == 1.0


def test_trajectory_efficiency_exposes_all_three_subsignals() -> None:
    case = EvalCase(
        scenario_id="inefficient",
        query="查一下",
        prompt_version_id="prompt-v1",
        tool_schema_version_id="tools-v1",
        effort="low",
        should_use_tools=True,
    )
    hard_cap = STEP_BUDGETS["low"].hard_cap
    events: list[Any] = [
        IterationStarted(run_id="run", iteration=iteration) for iteration in range(1, hard_cap + 1)
    ]
    events.extend(
        [
            ToolStarted(
                run_id="run",
                iteration=1,
                tool_call_id="read-1",
                name="web_reader",
                arguments={"url": "https://example.test/a"},
            ),
            ToolStarted(
                run_id="run",
                iteration=2,
                tool_call_id="read-2",
                name="web_reader",
                arguments={"url": "https://example.test/a"},
            ),
            ToolStarted(
                run_id="run",
                iteration=hard_cap,
                tool_call_id="search-last",
                name="web_search",
                arguments={"query": "最后又搜一次"},
            ),
            RunCompleted(
                run_id="run",
                iteration=hard_cap,
                message=_answer("没有引用"),
            ),
        ]
    )

    report = asyncio.run(evaluate_batch([EvalSample(case=case, events=events)], judge=FakeJudge()))
    metric = report.case_results[0].scores["trajectory_efficiency"]

    assert metric.details == {
        "hard_cap_reached": True,
        "repeated_reader_url_count": 1,
        "search_without_followup_read": True,
    }
    assert metric.score == pytest.approx(1 / 6)


class FakeJudgeModelPort:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def stream(self, **kwargs: Any) -> AsyncIterator[ModelEvent]:
        self.calls.append(kwargs)
        yield ModelCallCompleted(
            message=_answer('{"factual_hallucination_rate": 0.125, "task_completion": 0.875}'),
            usage=Usage(
                state="complete",
                input_tokens=10,
                output_tokens=5,
                reasoning_tokens=None,
            ),
            stop_reason="end_turn",
        )


def test_model_port_judge_uses_live_model_boundary_and_returns_two_scores() -> None:
    profile = EndpointProfile(
        name="judge",
        protocol="openai_responses",
        base_url="https://example.test",
        auth_field="Authorization",
        api_key=SecretStr("test-key"),
    )
    port = FakeJudgeModelPort()
    judge = ModelPortJudge(
        profile=profile,
        snapshot_id="judge-exact-2026-08-18",
        model_port_factory=lambda _profile: port,
    )

    scores = asyncio.run(
        judge.evaluate(
            JudgeRequest(
                scenario_id="scenario",
                query="问题",
                answer="回答",
                observations="工具观察",
                expected_answer="参考答案",
            )
        )
    )

    assert scores == JudgeScores(
        factual_hallucination_rate=0.125,
        task_completion=0.875,
        snapshot_id="judge-exact-2026-08-18",
    )
    assert port.calls[0]["model"] == "judge-exact-2026-08-18"
    assert port.calls[0]["tools"] == []
    assert port.calls[0]["effort"] == "low"


def test_judge_default_snapshot_comes_from_environment_with_documented_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("EVAL_JUDGE_MODEL", raising=False)
    assert judge_snapshot_from_env() == DEFAULT_JUDGE_SNAPSHOT

    monkeypatch.setenv("EVAL_JUDGE_MODEL", "custom-snapshot-2026-08-18")
    assert judge_snapshot_from_env() == "custom-snapshot-2026-08-18"
