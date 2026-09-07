"""模型输入配置的模板、规范化快照与不可变版本同步（issue #54）。

系统提示词和工具集 schema 是运行配置，不是对话消息。此模块只负责构建、渲染
以及把构建时看到的内容写入版本表；运行服务读取版本表后再把解析后的配置传给
纯 ``AgentRunner``。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from string import Template
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.app import PromptVersion, ToolSchemaVersion
from ..llm.effort import EFFORT_TIERS, EffortTier
from ..tools.registry import tool_definitions

SYSTEM_PROMPT_NAME = "system"
TITLE_PROMPT_NAME = "title"
TOOL_SCHEMA_NAME = "tools"

SYSTEM_PROMPT_TEMPLATE = """你是一个友好、简洁、准确且有研究能力的对话式 AI 助手。
你的回答应建立在可信的信息基础上；需要外部信息时使用可用工具，并在回答中提供来源。

今天的日期：$date

执行指南：
- 使用 Markdown 清晰地组织回答。
- 根据任务需要决定检索范围，遵守当前运行的步数预算：$step_budget。
- 保持自然、专业、友好的语气。
- 跟随用户消息使用的语言回答；不要因为本模板的语言而改变用户的语言偏好。
- 直接回答用户的问题；如果缺少完成任务所需的信息，再提出简短的澄清问题。

现在请处理用户消息。
"""

TITLE_PROMPT_TEMPLATE = """根据用户的首条消息生成一个简洁、准确的会话标题。
只根据首条用户消息判断标题，不参考任何回答、工具结果或后续消息。
标题应使用用户消息的语言，不要添加引号、Markdown 或解释。
"""


@dataclass(frozen=True, slots=True)
class PromptVersionRecord:
    name: str
    content: str
    variables: list[str]
    content_hash: str
    version_id: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ToolSchemaVersionRecord:
    name: str
    content: str
    effort_tier: EffortTier
    content_hash: str
    version_id: str
    created_at: datetime


def content_hash(content: str) -> str:
    """返回逐字内容的 SHA-256 前 12 位。"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


def _utc_created_at(created_at: datetime | None = None) -> datetime:
    value = created_at if created_at is not None else datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def version_id(name: str, created_at: datetime, content: str) -> str:
    """按约定构建 ``名字@创建时间-内容哈希`` 标识。"""
    created = _utc_created_at(created_at)
    timestamp = created.strftime("%Y%m%dT%H%M%S.%fZ")
    return f"{name}@{timestamp}-{content_hash(content)}"


def _prompt_record(
    name: str, content: str, variables: Sequence[str], created_at: datetime
) -> PromptVersionRecord:
    normalized_variables = list(variables)
    return PromptVersionRecord(
        name=name,
        content=content,
        variables=normalized_variables,
        content_hash=content_hash(content),
        version_id=version_id(name, created_at, content),
        created_at=created_at,
    )


def build_prompt_versions(*, created_at: datetime | None = None) -> list[PromptVersionRecord]:
    """构建基础提示词和标题提示词的版本载荷。"""
    created = _utc_created_at(created_at)
    return [
        _prompt_record(
            SYSTEM_PROMPT_NAME,
            SYSTEM_PROMPT_TEMPLATE,
            ("date", "step_budget"),
            created,
        ),
        _prompt_record(TITLE_PROMPT_NAME, TITLE_PROMPT_TEMPLATE, (), created),
    ]


def render_system_prompt(*, date: str, step_budget: int) -> str:
    """用本次运行的日期和软步数预算解析系统提示词。"""
    return Template(SYSTEM_PROMPT_TEMPLATE).substitute(date=date, step_budget=step_budget)


def prompt_reference(version_id_value: str) -> str:
    """返回观测层使用的提示词占位符，不展开版本全文。"""
    return f"{{system_prompt@{version_id_value}}}"


def tool_schema_reference(version_id_value: str) -> str:
    """返回观测层使用的工具集占位符，不展开 schema 全文。"""
    return f"{{tool_schema@{version_id_value}}}"


def prompt_observation_attributes(version_id_value: str) -> dict[str, Any]:
    """构建 OpenInference 提示词属性，全文只保留版本指代。"""
    return {
        "input.value": prompt_reference(version_id_value),
        "llm.prompt_template.version": version_id_value,
        "llm.prompt_template.variables": ["date", "step_budget"],
    }


def canonical_tool_schema() -> str:
    """返回按工具名和 JSON key 稳定排序的工具集 schema 快照。"""
    definitions = sorted(tool_definitions(), key=lambda item: str(item["name"]))
    return json.dumps(definitions, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_tool_schema_versions(
    *, created_at: datetime | None = None
) -> list[ToolSchemaVersionRecord]:
    """为每个努力档位构建一份稳定的工具集快照。"""
    created = _utc_created_at(created_at)
    content = canonical_tool_schema()
    digest = content_hash(content)
    return [
        ToolSchemaVersionRecord(
            name=f"{TOOL_SCHEMA_NAME}-{effort}",
            content=content,
            effort_tier=effort,
            content_hash=digest,
            version_id=version_id(f"{TOOL_SCHEMA_NAME}-{effort}", created, content),
            created_at=created,
        )
        for effort in EFFORT_TIERS
    ]


async def _find_prompt(session: AsyncSession, record: PromptVersionRecord) -> PromptVersion | None:
    result = await session.execute(
        select(PromptVersion).where(
            PromptVersion.name == record.name,
            PromptVersion.content_hash == record.content_hash,
            PromptVersion.content == record.content,
        )
    )
    return cast(PromptVersion | None, result.scalar_one_or_none())


async def _find_tool_schema(
    session: AsyncSession, record: ToolSchemaVersionRecord
) -> ToolSchemaVersion | None:
    result = await session.execute(
        select(ToolSchemaVersion).where(
            ToolSchemaVersion.name == record.name,
            ToolSchemaVersion.effort_tier == record.effort_tier,
            ToolSchemaVersion.content_hash == record.content_hash,
            ToolSchemaVersion.content == record.content,
        )
    )
    return cast(ToolSchemaVersion | None, result.scalar_one_or_none())


async def sync_prompt_versions(
    session: AsyncSession, *, created_at: datetime | None = None
) -> list[PromptVersion]:
    """同步提示词版本，内容相同则复用已有行。"""
    rows: list[PromptVersion] = []
    for record in build_prompt_versions(created_at=created_at):
        await session.execute(
            insert(PromptVersion)
            .values(
                version_id=record.version_id,
                name=record.name,
                content=record.content,
                content_hash=record.content_hash,
                variables=record.variables,
                created_at=record.created_at,
            )
            .on_conflict_do_nothing(index_elements=["name", "content_hash"])
        )
        row = await _find_prompt(session, record)
        if row is None:
            raise RuntimeError(f"提示词版本同步失败: {record.name}")
        rows.append(row)
    await session.flush()
    return rows


async def sync_tool_schema_versions(
    session: AsyncSession, *, created_at: datetime | None = None
) -> list[ToolSchemaVersion]:
    """同步各努力档位的工具集版本，内容相同则复用已有行。"""
    rows: list[ToolSchemaVersion] = []
    for record in build_tool_schema_versions(created_at=created_at):
        await session.execute(
            insert(ToolSchemaVersion)
            .values(
                version_id=record.version_id,
                name=record.name,
                content=record.content,
                content_hash=record.content_hash,
                effort_tier=record.effort_tier,
                created_at=record.created_at,
            )
            .on_conflict_do_nothing(index_elements=["name", "effort_tier", "content_hash"])
        )
        row = await _find_tool_schema(session, record)
        if row is None:
            raise RuntimeError(f"工具集版本同步失败: {record.name}")
        rows.append(row)
    await session.flush()
    return rows


async def sync_model_input_versions(
    session: AsyncSession, *, created_at: datetime | None = None
) -> tuple[list[PromptVersion], list[ToolSchemaVersion]]:
    """同步两类版本，内容相同则复用已有行，不产生重复版本。"""
    prompt_rows = await sync_prompt_versions(session, created_at=created_at)
    tool_rows = await sync_tool_schema_versions(session, created_at=created_at)
    return prompt_rows, tool_rows


@asynccontextmanager
async def model_input_version_lifespan(
    session_factory: Callable[[], AbstractAsyncContextManager[AsyncSession]],
) -> AsyncIterator[tuple[list[PromptVersion], list[ToolSchemaVersion]]]:
    """应用启动时在单个事务内同步版本，并将已同步行交给应用状态。"""
    async with session_factory() as session:
        async with session.begin():
            versions = await sync_model_input_versions(session)
        yield versions


__all__ = [
    "SYSTEM_PROMPT_NAME",
    "SYSTEM_PROMPT_TEMPLATE",
    "TITLE_PROMPT_NAME",
    "TITLE_PROMPT_TEMPLATE",
    "TOOL_SCHEMA_NAME",
    "PromptVersionRecord",
    "ToolSchemaVersionRecord",
    "build_prompt_versions",
    "build_tool_schema_versions",
    "canonical_tool_schema",
    "content_hash",
    "model_input_version_lifespan",
    "prompt_observation_attributes",
    "prompt_reference",
    "render_system_prompt",
    "sync_model_input_versions",
    "sync_prompt_versions",
    "sync_tool_schema_versions",
    "tool_schema_reference",
    "version_id",
]
