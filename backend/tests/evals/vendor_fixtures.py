"""冻结在 Tavily/Jina 供应商边界的评测夹具（ADR-0033）。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from chat_agents.tools.types import ToolSpec
from chat_agents.tools.web_reader import make_spec as make_reader_spec
from chat_agents.tools.web_search import make_spec as make_search_spec
from chat_agents.tools.web_search.orchestration import SearchHit


@dataclass(frozen=True, slots=True)
class FrozenVendorFixture:
    scenario_id: str
    tavily_results: tuple[SearchHit, ...]
    jina_responses: dict[str, str]


class _FrozenVendorSession:
    """一个场景的一次运行；查询文本只留痕，不参与夹具寻址。"""

    def __init__(self, fixture: FrozenVendorFixture) -> None:
        self._fixture = fixture
        self.search_queries: list[str] = []
        self.read_urls: list[str] = []

    async def search(self, query: str, *, max_results: int) -> list[SearchHit]:
        self.search_queries.append(query)
        return list(self._fixture.tavily_results[:max_results])

    async def fetch(self, url: str) -> str:
        self.read_urls.append(url)
        try:
            return self._fixture.jina_responses[url]
        except KeyError as exc:
            raise RuntimeError(
                f"场景 {self._fixture.scenario_id} 没有为 URL 录制 Jina 夹具: {url}"
            ) from exc


class FrozenVendorFixtureStore:
    """按数据集场景 ID 打开冻结供应商会话。"""

    def __init__(self, fixtures: dict[str, FrozenVendorFixture]) -> None:
        self._fixtures = fixtures
        self.opened_scenario_ids: list[str] = []

    @classmethod
    def from_file(cls, path: Path) -> FrozenVendorFixtureStore:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("scenarios"), dict):
            raise ValueError("供应商夹具必须包含 scenarios 对象")
        fixtures = {
            scenario_id: _fixture_from_dict(scenario_id, payload)
            for scenario_id, payload in raw["scenarios"].items()
        }
        return cls(fixtures)

    def open(self, scenario_id: str) -> _FrozenVendorSession:
        try:
            fixture = self._fixtures[scenario_id]
        except KeyError as exc:
            raise KeyError(f"未知评测场景 ID: {scenario_id}") from exc
        self.opened_scenario_ids.append(scenario_id)
        return _FrozenVendorSession(fixture)

    def tool_specs(self, scenario_id: str) -> dict[str, ToolSpec]:
        """为一个场景构造工具集；模型仍是活的，只有 Tavily/Jina 被替换。"""

        session = self.open(scenario_id)
        return {
            "web_search": make_search_spec(lambda _ctx: session),
            "web_reader": make_reader_spec(lambda _ctx: session),
        }


def _fixture_from_dict(scenario_id: Any, raw: Any) -> FrozenVendorFixture:
    if not isinstance(scenario_id, str) or not scenario_id:
        raise ValueError("场景 ID 必须是非空字符串")
    if not isinstance(raw, dict):
        raise ValueError(f"场景 {scenario_id} 的夹具必须是对象")

    raw_results = raw.get("tavily_results")
    if not isinstance(raw_results, list):
        raise ValueError(f"场景 {scenario_id} 必须包含 tavily_results 数组")
    results = tuple(_search_hit(scenario_id, item) for item in raw_results)

    raw_pages = raw.get("jina_responses")
    if not isinstance(raw_pages, dict) or not all(
        isinstance(url, str) and isinstance(markdown, str) for url, markdown in raw_pages.items()
    ):
        raise ValueError(f"场景 {scenario_id} 的 jina_responses 必须是字符串映射")

    return FrozenVendorFixture(
        scenario_id=scenario_id,
        tavily_results=results,
        jina_responses=dict(raw_pages),
    )


def _search_hit(scenario_id: str, raw: Any) -> SearchHit:
    if not isinstance(raw, dict):
        raise ValueError(f"场景 {scenario_id} 的 Tavily 结果必须是对象")
    title = raw.get("title")
    url = raw.get("url")
    content = raw.get("content")
    score = raw.get("score")
    if not isinstance(title, str) or not isinstance(url, str) or not isinstance(content, str):
        raise ValueError(f"场景 {scenario_id} 的 Tavily 结果缺少字符串字段")
    if score is not None and not isinstance(score, int | float):
        raise ValueError(f"场景 {scenario_id} 的 Tavily score 必须是数字或 null")
    return SearchHit(
        title=title,
        url=url,
        content=content,
        score=float(score) if score is not None else None,
    )
