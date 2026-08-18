"""观测查询契约（issue #58，ADR-0022/0023）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, PrivateAttr, model_serializer

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
    started_at: datetime
    ended_at: datetime | None
    children: list[SpanView]

    _protocol: str | None = PrivateAttr(default=None)

    @model_serializer(mode="wrap")
    def _serialize(self, handler: Any) -> dict[str, Any]:
        data = handler(self)
        if self._protocol == "openai_chat_completions":
            # Chat Completions 从不采集 reasoning；字段缺席本身就是契约信息。
            data.pop("reasoning_tokens", None)
        if self.display_summary is None:
            data.pop("display_summary", None)
        return data


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
