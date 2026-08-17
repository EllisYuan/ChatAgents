"""``obs`` schema：观测数据（issue #48，ADR-0002/0003/0006/0012/0019/0023）。

外键只能 ``obs -> app`` 单向（ADR-0002）：本模块可以引用 ``app``，反过来不行。
无成本字段——成本是可推算量，不是观测事实，见 ``Span`` 说明。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import ClassVar

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import APP_SCHEMA, OBSERVABILITY_SCHEMA, Base


class Run(Base):
    """运行——一次智能体循环，消息区间靠 ``trigger_message_id``/``last_message_seq``
    圈定（ADR-0002：外键不能反过来在 ``app.message`` 上加 ``run_id``）。
    """

    __tablename__ = "run"
    __table_args__: ClassVar[dict] = {"schema": OBSERVABILITY_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{APP_SCHEMA}.session.id"), nullable=False, index=True
    )
    # 触发本次运行的那条用户消息（ADR-0002）。
    trigger_message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{APP_SCHEMA}.message.id"), nullable=False
    )
    # 本次运行产出消息的 seq 上界——运行内的消息在会话中总是连续的，因此
    # [trigger 消息.seq, last_message_seq] 就是这次运行的完整消息区间。
    # 运行开始时未知，落在 running 态时为 NULL。
    last_message_seq: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="running")
    effort: Mapped[str | None] = mapped_column(String(16))
    prompt_version_id: Mapped[str | None] = mapped_column(
        ForeignKey(f"{APP_SCHEMA}.prompt_versions.version_id")
    )
    tool_schema_version_id: Mapped[str | None] = mapped_column(
        ForeignKey(f"{APP_SCHEMA}.tool_schema_versions.version_id")
    )
    # 保留窗口——ADR-0023 把它和提示词/工具版本号、运行终态并列为"运行级"字段，
    # 比 ADR-0019「记在跨度上」的表述更具体也更晚近；建模成本低廉的整数列，
    # 不违背 ADR-0019「不建版本表」的本意（那里从未提议为它单独建表）。
    retention_window: Mapped[int | None] = mapped_column(Integer)
    # attributes 额外记录本次运行模型输入中被掩蔽的观测标识列表（ADR-0019 观测掩蔽）。
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Span(Base):
    """跨度——通用形状对齐 Arize Phoenix：``attributes``（OpenInference 键）承载
    全量快照，六个自命名物化真列承载高频查询字段（ADR-0003/0006/0012）。

    真列是权威来源，``attributes`` 只是补充快照——两者不一致时以真列为准。
    没有任何成本字段：成本随定价配置变化，是纯查询层的推算结果（ADR-0003），
    重新计算不应触发 schema 变更。
    """

    __tablename__ = "span"
    __table_args__: ClassVar[dict] = {"schema": OBSERVABILITY_SCHEMA}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{OBSERVABILITY_SCHEMA}.run.id"), nullable=False, index=True
    )
    parent_span_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{OBSERVABILITY_SCHEMA}.span.id")
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    # 跨度种类（如 LLM/TOOL/CHAIN）——通用表的一部分，对齐 Phoenix 形态（ADR-0003：
    # 「通用跨度表（kind / parent_span_id / 时刻 / 状态）+ attributes JSONB」）。
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    # 跨度是否记为失败——外部失败（如工具报错）仍要落一条错误跨度，不能吞掉（ADR-0006）。
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="ok")

    # --- 六个自命名（非上游字段名）物化真列 ---
    # 模型角色：main/auxiliary，判据是输出去向，不是调用层级（ADR-0012）。
    role: Mapped[str | None] = mapped_column(String(16))
    model: Mapped[str | None] = mapped_column(String)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    # 用量三态：缺失一律 NULL，不以 0 表示（CONTEXT.md 用量三态）。
    usage_status: Mapped[str | None] = mapped_column(String(16))
    # 推理 token——ADR-0003 把「用量 vs 调试细节」作为分界线，推理 token 属于用量，
    # 因此单独给一个真列而不是塞进 attributes；缺失同样记 NULL，不是 0。
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer)

    # OpenInference 语义约定键的全量快照（ADR-0003）。
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
