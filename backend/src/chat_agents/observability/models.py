"""观测查询契约（issue #58，ADR-0022/0023）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, PrivateAttr

from ..llm.events import UsageState


class RunSummary(BaseModel):
    """会话运行列表的最小骨架，供客户端与消息序列合并。"""

    id: UUID
    trigger_message_id: UUID
    last_message_seq: int | None


class UsageAggregate(BaseModel):
    """一次运行内按模型、角色和时间窗汇总的完整用量。"""

    model: str
    role: str
    input_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    started_at: datetime
    ended_at: datetime | None


class DisplaySummary(BaseModel):
    """跨度显示摘要；老化后保留状态而不伪装成从未产生。"""

    text: str | None
    status: Literal["available", "aged_out"]


class ToolResultView(BaseModel):
    """工具跨度的结果，供历史视图重建工具结果卡片（issue #69）。

    只在 ``kind == "tool"`` 的跨度上出现——结构性不存在的字段根本不出现
    （ADR-0023），不用 ``None`` 冒充「这条工具调用没有结果」。
    """

    result: str
    structured: dict[str, Any] | None


class SpanView(BaseModel):
    """跨度节点及其递归子节点。"""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    parent_span_id: UUID | None
    name: str
    kind: str
    status: str
    role: str | None
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    usage_status: UsageState | None
    reasoning_tokens: int | None = None
    display_summary: DisplaySummary | None = None
    arguments: dict[str, Any] | None = None
    tool_result: ToolResultView | None = None
    started_at: datetime
    ended_at: datetime | None
    children: list[SpanView]

    _protocol: str | None = PrivateAttr(default=None)


class TitleGenerationSpan(BaseModel):
    """一次标题生成的观测事实（ADR-0035）。

    只暴露白名单字段：真列用量、实际模型、时间、状态，以及从 ``attributes``
    摘出的 ``effort`` / ``application_result`` / ``failure_reason``。不暴露
    ``key_source`` 或完整 ``attributes``——密钥来源与原始属性不进公开载荷。
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    model: str | None
    effort: str | None
    status: str
    usage_status: UsageState | None
    input_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    started_at: datetime
    ended_at: datetime | None
    duration_ms: int | None
    application_result: Literal["applied", "manual_not_applied", "deleted_not_applied"] | None = (
        None
    )
    failure_reason: (
        Literal["upstream", "empty_output", "missing_terminal", "timeout", "cancelled"] | None
    ) = None


class TitleGenerationObservation(BaseModel):
    """``GET /api/sessions/{session_id}/title-generation`` 的只读载荷。

    合并直属 ``session_id`` 的独立标题跨度与经 ``obs.run.session_id`` 找到的
    历史运行标题跨度；没有跨度时返回空列表，不读业务 ``title`` 反推。
    """

    session_id: UUID
    spans: list[TitleGenerationSpan]


class RunDetail(BaseModel):
    """单次运行的运行级配置、用量汇总与完整跨度树。"""

    id: UUID
    session_id: UUID
    trigger_message_id: UUID
    last_message_seq: int | None
    status: str
    started_at: datetime
    ended_at: datetime | None
    prompt_version_id: str | None
    tool_schema_version_id: str | None
    retention_window: int | None
    effort: str | None
    pruned_run_count: int
    usage: list[UsageAggregate]
    spans: list[SpanView]


def _span_payload(span: SpanView) -> dict[str, Any]:
    """编码跨度并按协议删除结构性不存在的字段。"""

    payload: dict[str, Any] = span.model_dump(mode="json")
    payload["children"] = [_span_payload(child) for child in span.children]
    if span._protocol == "openai_chat_completions":
        # Chat Completions 从不采集 reasoning；字段缺席本身就是契约信息。
        payload.pop("reasoning_tokens", None)
    if span.display_summary is None:
        payload.pop("display_summary", None)
    if span.arguments is None:
        payload.pop("arguments", None)
    if span.tool_result is None:
        payload.pop("tool_result", None)
    return payload


def run_detail_payload(detail: RunDetail) -> dict[str, Any]:
    """返回可直接交给 JSONResponse 的详情载荷。"""

    payload: dict[str, Any] = detail.model_dump(mode="json", exclude={"spans"})
    payload["spans"] = [_span_payload(span) for span in detail.spans]
    return payload
