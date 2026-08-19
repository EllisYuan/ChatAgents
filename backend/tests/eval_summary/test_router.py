"""站点评测展示面路由的契约测试（issue #66）。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from chat_agents import main as main_module
from chat_agents.eval_summary.router import get_eval_summary_store
from chat_agents.eval_summary.store import EvalSummaryStore


def _override_store(store: EvalSummaryStore):
    async def dependency() -> AsyncIterator[EvalSummaryStore]:
        yield store

    return dependency


def test_endpoint_returns_exactly_four_top_level_numbers(tmp_path: Path) -> None:
    async def scenario() -> None:
        main_module.app.dependency_overrides[get_eval_summary_store] = _override_store(
            EvalSummaryStore(tmp_path)
        )
        try:
            transport = httpx.ASGITransport(app=main_module.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/evals/summary")
        finally:
            main_module.app.dependency_overrides.pop(get_eval_summary_store, None)

        assert response.status_code == 200
        body = response.json()
        assert set(body) == {
            "citation_faithfulness",
            "tool_trigger_rate",
            "trajectory_efficiency",
            "compression_cost_curve",
        }

    asyncio.run(scenario())


def test_endpoint_degrades_the_fourth_number_when_the_grid_scan_has_not_landed(
    tmp_path: Path,
) -> None:
    (tmp_path / "site-summary.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-08-19T00:00:00+00:00",
                "case_results": [{"scenario_id": "a"}],
                "aggregate_scores": {
                    "citation_faithfulness": 0.86,
                    "tool_trigger_rate": 0.93,
                    "trajectory_efficiency": 0.78,
                },
            }
        ),
        encoding="utf-8",
    )

    async def scenario() -> None:
        main_module.app.dependency_overrides[get_eval_summary_store] = _override_store(
            EvalSummaryStore(tmp_path)
        )
        try:
            transport = httpx.ASGITransport(app=main_module.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get("/api/evals/summary")
        finally:
            main_module.app.dependency_overrides.pop(get_eval_summary_store, None)

        body = response.json()
        assert body["citation_faithfulness"]["score"] == 0.86
        assert body["tool_trigger_rate"]["score"] == 0.93
        assert body["trajectory_efficiency"]["score"] == 0.78
        assert body["compression_cost_curve"] is None

    asyncio.run(scenario())


def test_endpoint_is_a_standalone_read_only_route_not_part_of_the_chat_transport() -> None:
    schema = main_module.app.openapi()
    paths = schema["paths"]

    assert "/api/evals/summary" in paths
    operation = paths["/api/evals/summary"]["get"]
    assert operation["tags"] == ["evals"]
    assert set(paths["/api/evals/summary"]) == {"get"}
