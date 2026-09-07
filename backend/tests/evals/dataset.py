"""评测数据集及三轴分组。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from chat_agents.llm.effort import EffortTier


@dataclass(frozen=True, slots=True)
class EvalGroupKey:
    """评测结果唯一允许的分组轴；查询文本刻意不在这里。"""

    prompt_version_id: str
    tool_schema_version_id: str
    effort: EffortTier


@dataclass(frozen=True, slots=True)
class EvalCase:
    """一条数据集场景及其运行配置。"""

    scenario_id: str
    query: str
    prompt_version_id: str
    tool_schema_version_id: str
    effort: EffortTier
    should_use_tools: bool
    expected_answer: str | None = None

    @property
    def group_key(self) -> EvalGroupKey:
        return EvalGroupKey(
            prompt_version_id=self.prompt_version_id,
            tool_schema_version_id=self.tool_schema_version_id,
            effort=self.effort,
        )


class EvalDataset:
    """可从 JSON 加载并按提示词版本 × 工具集版本 × 努力档位切片。"""

    def __init__(self, cases: list[EvalCase]) -> None:
        identities = [(case.scenario_id, case.group_key) for case in cases]
        if len(identities) != len(set(identities)):
            raise ValueError("同一三轴分组内的场景 ID 必须唯一")
        self.cases = tuple(cases)

    @classmethod
    def from_file(cls, path: Path) -> EvalDataset:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("cases"), list):
            raise ValueError("评测数据集必须包含 cases 数组")
        return cls([_case_from_dict(item) for item in raw["cases"]])

    def grouped(self) -> dict[EvalGroupKey, tuple[EvalCase, ...]]:
        groups: dict[EvalGroupKey, list[EvalCase]] = {}
        for case in self.cases:
            groups.setdefault(case.group_key, []).append(case)
        return {key: tuple(cases) for key, cases in groups.items()}


def _required_string(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} 必须是非空字符串")
    return value


def _case_from_dict(raw: Any) -> EvalCase:
    if not isinstance(raw, dict):
        raise ValueError("cases 中的每一项都必须是对象")
    effort = _required_string(raw, "effort")
    if effort not in {"low", "medium", "high", "xhigh"}:
        raise ValueError(f"未知努力档位: {effort}")
    should_use_tools = raw.get("should_use_tools")
    if not isinstance(should_use_tools, bool):
        raise ValueError("should_use_tools 必须是布尔值")
    expected_answer = raw.get("expected_answer")
    if expected_answer is not None and not isinstance(expected_answer, str):
        raise ValueError("expected_answer 必须是字符串或省略")
    return EvalCase(
        scenario_id=_required_string(raw, "scenario_id"),
        query=_required_string(raw, "query"),
        prompt_version_id=_required_string(raw, "prompt_version_id"),
        tool_schema_version_id=_required_string(raw, "tool_schema_version_id"),
        effort=cast(EffortTier, effort),
        should_use_tools=should_use_tools,
        expected_answer=expected_answer,
    )
