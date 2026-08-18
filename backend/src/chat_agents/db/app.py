"""``app`` schema：业务数据（issue #48，ADR-0001/0002/0011/0016/0018）。

外键只能 ``obs -> app`` 单向（ADR-0002）——本模块任何模型都不得引用 ``obs``。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import ClassVar

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import APP_SCHEMA, Base


class Session(Base):
    """会话——消息的容器，随第一条用户消息诞生（ADR-0013）。"""

    __tablename__ = "session"
    __table_args__: ClassVar[dict] = {"schema": APP_SCHEMA}

    # 前端生成（建议 UUIDv7）作为路由标识，后端不生成会话标识（ADR-0013）。
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    title: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    # 软删除：硬删会打断 obs -> app 的外键，观测数据不能指向一个凭空消失的业务行
    # （ADR-0002/0013）。查询默认过滤 deleted_at IS NOT NULL 的行。
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 削减计数：ADR-0019 第 2 层压缩每丢弃一块已完成运行就递增一次。
    # 这是 issue #25 交办给本票的唯一 schema 增量，不代表软删除或消息计数。
    pruned_run_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class Message(Base):
    """消息——对话记忆的唯一事实来源，存完整模型视角序列（ADR-0001）。

    没有 ``run_id`` 列，这是刻意的：ADR-0002 定了外键只能 ``obs -> app`` 单向，
    "这条消息属于哪次运行"只能反过来从 ``obs.run`` 圈定
    （``trigger_message_id`` + ``last_message_seq``）。
    """

    __tablename__ = "message"
    __table_args__ = (
        UniqueConstraint("session_id", "seq", name="uq_message_session_seq"),
        {"schema": APP_SCHEMA},
    )

    # 主键由应用层 uuid5(运行标识, 迭代序号[, 工具序号]) 派生，禁止数据库自增——
    # 这是评测 L2 回放"同输入产出逐字节相同事件流"可断言性的前提（ADR-0009）。
    # 本表因此不声明 autoincrement，插入时必须显式提供 id。
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, autoincrement=False)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{APP_SCHEMA}.session.id"), nullable=False, index=True
    )
    # 会话内显式排序，不靠时间戳——一次运行产出的多条消息时刻可能相同（ADR-0001）。
    # 仍由落库时的服务层分配（非数据库自增），与 id 的外部派生是两件独立的事。
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    # 完整内容块序列（文本 / 工具调用 / 工具结果），协议无关表示的落库形态（ADR-0007）。
    content: Mapped[list] = mapped_column(JSONB, nullable=False)
    # 往返载荷——原生推理里回传给模型自己的那一半，按协议原样存放的不透明附件
    # （ADR-0017）。
    #
    # 这是消息表第一个"会被就地置空"的字段（ADR-0018）：它只在产出它的那一次运行内
    # 有效，运行终态（成功、失败、客户端断连一律）收尾时清空。判据是"读者消失"，
    # 不是"时间到了"——它不进 ADR-0003 的分级老化（那套按起始时刻判断，且是给
    # "有价值但会过时"的调试细节准备的），也不需要后台任务。
    #
    # 它既不是软删除（行还在，其余字段语义不变），也不是老化：清空后此列为 NULL
    # 是设计的一部分，不是数据丢失，不需要"修复"。
    round_trip_payload: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PromptVersion(Base):
    """系统提示词的不可变版本表（ADR-0011）。

    不由业务逻辑写入——数据来自构建产物（提示词模板同步任务）。本模块及其余业务
    代码不得为它添加更新/删除接口；只增不改不删。
    """

    __tablename__ = "prompt_versions"
    __table_args__: ClassVar[dict] = {"schema": APP_SCHEMA}

    # version_id = f"{name}@{created_at}-{content_hash}"，内容的纯函数（ADR-0011）。
    version_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(12), nullable=False)
    variables: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ToolSchemaVersion(Base):
    """某一努力档位下全部工具定义的不可变版本表（ADR-0011）。

    不由业务逻辑写入——数据来自启动时的工具集同步。粒度按工具集，不按单个工具：
    一个档位下全部工具定义的规范化有序 JSON 数组算作一个版本。
    """

    __tablename__ = "tool_schema_versions"
    __table_args__: ClassVar[dict] = {"schema": APP_SCHEMA}

    version_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(12), nullable=False)
    effort_tier: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DiscoveredModel(Base):
    """模型清单——向端点档案实时发现而来，不由业务逻辑写入（ADR-0016）。

    只落库服务端预设那一层（24 小时自动刷新）；用户自定义端点的清单按 ADR-0016
    的决定不落库，只活在前端。写入方是发现任务，不是任何业务 handler。
    """

    __tablename__ = "discovered_model"
    __table_args__ = (
        UniqueConstraint("endpoint_profile", "model_id", name="uq_discovered_model_profile_model"),
        {"schema": APP_SCHEMA},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    endpoint_profile: Mapped[str] = mapped_column(String, nullable=False)
    # 原始模型标识，不做美化——它就是要粘进请求里的那个字符串（ADR-0016）。
    model_id: Mapped[str] = mapped_column(String, nullable=False)
    owned_by: Mapped[str] = mapped_column(String, nullable=False)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DiscoveredModelRefresh(Base):
    """模型清单成功刷新元数据，由发现任务写入，不由业务逻辑写入。

    单独保存批次时刻是为了表达“成功返回空清单”——此时没有
    ``discovered_model`` 行可供 ``MAX(discovered_at)`` 推导。
    """

    __tablename__ = "discovered_model_refresh"
    __table_args__: ClassVar[dict] = {"schema": APP_SCHEMA}

    endpoint_profile: Mapped[str] = mapped_column(String, primary_key=True)
    last_success_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
