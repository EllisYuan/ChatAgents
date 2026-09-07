"""站点评测展示面数据源的读取行为（issue #66）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from chat_agents.eval_summary.store import EvalSummaryStore


def _write(directory: Path, name: str, payload: dict[str, Any]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_missing_reports_dir_degrades_to_all_four_numbers_absent(tmp_path: Path) -> None:
    store = EvalSummaryStore(tmp_path / "does-not-exist")

    summary = store.read()

    assert summary.citation_faithfulness is None
    assert summary.tool_trigger_rate is None
    assert summary.trajectory_efficiency is None
    assert summary.compression_cost_curve is None


def test_reads_the_first_three_numbers_from_the_summary_report(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "site-summary.json",
        {
            "generated_at": "2026-08-19T00:00:00+00:00",
            "case_results": [{"scenario_id": "a"}, {"scenario_id": "b"}],
            "aggregate_scores": {
                "citation_faithfulness": 0.86,
                "tool_trigger_rate": 0.93,
                "trajectory_efficiency": 0.78,
                "argument_compliance": 0.99,
                "factual_hallucination_rate": 0.1,
            },
        },
    )

    summary = EvalSummaryStore(tmp_path).read()

    assert summary.citation_faithfulness is not None
    assert summary.citation_faithfulness.score == 0.86
    assert summary.citation_faithfulness.sample_size == 2
    assert summary.tool_trigger_rate is not None
    assert summary.tool_trigger_rate.score == 0.93
    assert summary.trajectory_efficiency is not None
    assert summary.trajectory_efficiency.score == 0.78
    assert summary.compression_cost_curve is None


def test_malformed_summary_report_degrades_instead_of_raising(tmp_path: Path) -> None:
    _write(tmp_path, "site-summary.json", {"generated_at": "not-a-date", "aggregate_scores": {}})

    summary = EvalSummaryStore(tmp_path).read()

    assert summary.citation_faithfulness is None
    assert summary.tool_trigger_rate is None
    assert summary.trajectory_efficiency is None


def test_incomplete_retention_grid_degrades_the_fourth_number(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "compression-cost-curve.json",
        {
            "generated_at": "2026-08-19T00:00:00+00:00",
            "points": [
                {"retention_window": 1, "citation_faithfulness": 0.7, "cost_tokens": 4000},
                {"retention_window": 2, "citation_faithfulness": 0.75, "cost_tokens": 4500},
            ],
        },
    )

    summary = EvalSummaryStore(tmp_path).read()

    assert summary.compression_cost_curve is None


def test_complete_retention_grid_produces_the_fourth_number_sorted_by_window(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "compression-cost-curve.json",
        {
            "generated_at": "2026-08-19T00:00:00+00:00",
            "points": [
                {"retention_window": 8, "citation_faithfulness": 0.95, "cost_tokens": 9000},
                {"retention_window": 1, "citation_faithfulness": 0.7, "cost_tokens": 4000},
                {"retention_window": 2, "citation_faithfulness": 0.75, "cost_tokens": 4500},
                {"retention_window": 3, "citation_faithfulness": 0.8, "cost_tokens": 5200},
                {"retention_window": 5, "citation_faithfulness": 0.88, "cost_tokens": 6800},
            ],
        },
    )

    summary = EvalSummaryStore(tmp_path).read()

    curve = summary.compression_cost_curve
    assert curve is not None
    assert [point.retention_window for point in curve.points] == [1, 2, 3, 5, 8]
    assert curve.points[0].citation_faithfulness == 0.7
    assert curve.points[0].cost_tokens == 4000


def test_malformed_curve_report_degrades_instead_of_raising(tmp_path: Path) -> None:
    _write(tmp_path, "compression-cost-curve.json", {"generated_at": "2026-08-19T00:00:00+00:00"})

    summary = EvalSummaryStore(tmp_path).read()

    assert summary.compression_cost_curve is None
