"""评测 CI 的确定性触发与配额规则。"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TypeAlias, TypeVar

from chat_agents.agent.versioning import build_prompt_versions, build_tool_schema_versions
from chat_agents.db.app import PromptVersion, ToolSchemaVersion
from chat_agents.llm.effort import EffortTier
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

CI_CASES_PER_EFFORT = 8
CI_EFFORTS: tuple[EffortTier, ...] = ("low", "medium", "high", "xhigh")
RELEASE_RETENTION_WINDOWS: tuple[int, ...] = (1, 2, 3, 5, 8)

InputHashKey: TypeAlias = tuple[str, str]
CaseT = TypeVar("CaseT")


@dataclass(frozen=True, slots=True)
class ModelInputHashes:
    """某一版本源代码中可被评测触发的模型输入 hash。"""

    prompts: Mapping[str, str]
    tool_schemas: Mapping[InputHashKey, str]


@dataclass(frozen=True, slots=True)
class ModelInputChange:
    """一条模型输入 hash 与基线不一致的记录。"""

    kind: str
    name: str
    current_hash: str | None
    baseline_hash: str | None
    effort: EffortTier | None = None

    @property
    def label(self) -> str:
        if self.kind == "prompt":
            return f"prompt:{self.name}"
        if self.effort is None:
            raise RuntimeError("工具集变更必须带努力档位")
        return f"tool_schema:{self.name}:{self.effort}"


async def latest_model_input_hashes(session: AsyncSession) -> ModelInputHashes:
    """读取数据库中每个模型输入名称的最新 hash，不写入任何版本行。"""

    prompt_rows = await session.scalars(
        select(PromptVersion).order_by(
            PromptVersion.name,
            PromptVersion.created_at.desc(),
            PromptVersion.version_id.desc(),
        )
    )
    prompts: dict[str, str] = {}
    for row in prompt_rows:
        prompts.setdefault(row.name, row.content_hash)

    tool_rows = await session.scalars(
        select(ToolSchemaVersion).order_by(
            ToolSchemaVersion.name,
            ToolSchemaVersion.effort_tier,
            ToolSchemaVersion.created_at.desc(),
            ToolSchemaVersion.version_id.desc(),
        )
    )
    tool_schemas: dict[InputHashKey, str] = {}
    for row in tool_rows:
        tool_schemas.setdefault((row.name, row.effort_tier), row.content_hash)

    return ModelInputHashes(prompts=prompts, tool_schemas=tool_schemas)


def current_model_input_hashes() -> ModelInputHashes:
    """从当前 checkout 的模型输入构建器计算 hash。"""

    return ModelInputHashes(
        prompts={record.name: record.content_hash for record in build_prompt_versions()},
        tool_schemas={
            (record.name, record.effort_tier): record.content_hash
            for record in build_tool_schema_versions()
        },
    )


def model_input_changes(
    current: ModelInputHashes, baseline: ModelInputHashes
) -> tuple[ModelInputChange, ...]:
    """返回当前 checkout 相对基线发生变化的提示词和工具集。"""

    changes: list[ModelInputChange] = []
    for name in sorted(set(current.prompts) | set(baseline.prompts)):
        current_hash = current.prompts.get(name)
        baseline_hash = baseline.prompts.get(name)
        if current_hash != baseline_hash:
            changes.append(
                ModelInputChange(
                    kind="prompt",
                    name=name,
                    current_hash=current_hash,
                    baseline_hash=baseline_hash,
                )
            )

    for name, effort in sorted(set(current.tool_schemas) | set(baseline.tool_schemas)):
        current_hash = current.tool_schemas.get((name, effort))
        baseline_hash = baseline.tool_schemas.get((name, effort))
        if current_hash != baseline_hash:
            changes.append(
                ModelInputChange(
                    kind="tool_schema",
                    name=name,
                    effort=effort,
                    current_hash=current_hash,
                    baseline_hash=baseline_hash,
                )
            )

    return tuple(changes)


def validate_ci_cases(cases: Sequence[CaseT], *, effort_of: Callable[[CaseT], str]) -> None:
    """验证 CI 批次恰好为每档 8 条；``effort_of`` 是取档位的 callable。"""

    if not callable(effort_of):
        raise TypeError("effort_of 必须是可调用对象")
    counts = {effort: 0 for effort in CI_EFFORTS}
    for case in cases:
        effort = effort_of(case)
        if effort not in counts:
            raise ValueError(f"CI 批次包含未知努力档位: {effort}")
        counts[effort] += 1
    if any(count != CI_CASES_PER_EFFORT for count in counts.values()):
        formatted = ", ".join(f"{effort}={counts[effort]}" for effort in CI_EFFORTS)
        raise ValueError(f"CI 评测必须每档 {CI_CASES_PER_EFFORT} 条，实际为 {formatted}")


def validate_ci_configuration(
    *, cases_per_effort: int, total_cases: int, retention_window: int | None = None
) -> None:
    """验证 workflow 注入的评测额度与 release 网格参数。"""

    expected_total = CI_CASES_PER_EFFORT * len(CI_EFFORTS)
    if cases_per_effort != CI_CASES_PER_EFFORT or total_cases != expected_total:
        raise ValueError(
            f"CI 评测额度必须是 {CI_CASES_PER_EFFORT}×{len(CI_EFFORTS)}={expected_total}"
        )
    if retention_window is not None and retention_window not in RELEASE_RETENTION_WINDOWS:
        raise ValueError(f"未知保留窗口: {retention_window}")


def release_retention_windows() -> tuple[int, ...]:
    """返回 release 档位常驻网格扫描的保留窗口集合。"""

    return RELEASE_RETENTION_WINDOWS


__all__ = [
    "CI_CASES_PER_EFFORT",
    "CI_EFFORTS",
    "RELEASE_RETENTION_WINDOWS",
    "InputHashKey",
    "ModelInputChange",
    "ModelInputHashes",
    "current_model_input_hashes",
    "latest_model_input_hashes",
    "model_input_changes",
    "release_retention_windows",
    "validate_ci_cases",
    "validate_ci_configuration",
]
