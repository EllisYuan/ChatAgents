"""Document table/column intent with COMMENT ON (no structural change)."""

from alembic import op

revision = "0006_schema_comments"
down_revision = "0005_version_uniqueness"
branch_labels = None
depends_on = None

_TABLE_COMMENTS: dict[str, str] = {
    "app.session": "会话——消息的容器，随第一条用户消息诞生（ADR-0013）。",
    "app.message": (
        "消息——对话记忆的唯一事实来源，存完整模型视角序列（ADR-0001）。"
        "无 run_id 列：消息属于哪次运行反过来从 obs.run 圈定（ADR-0002）。"
    ),
    "app.prompt_versions": (
        "系统提示词的不可变版本表（ADR-0011）。不由业务逻辑写入，只增不改不删。"
    ),
    "app.tool_schema_versions": (
        "某一努力档位下全部工具定义的不可变版本表（ADR-0011）。粒度按工具集，不按单个工具。"
    ),
    "app.discovered_model": "模型清单——向端点档案实时发现而来，不由业务逻辑写入（ADR-0016）。",
    "app.discovered_model_refresh": (
        "模型清单成功刷新元数据。单独存批次时刻是为了表达"
        "“成功返回空清单”——此时没有 discovered_model 行可供 MAX(discovered_at) 推导。"
    ),
    "obs.run": (
        "运行——一次智能体循环。消息区间靠 trigger_message_id/last_message_seq 圈定"
        "（ADR-0002：外键不能反过来在 app.message 上加 run_id）。"
    ),
    "obs.span": (
        "跨度——通用形状对齐 Arize Phoenix：attributes 承载 OpenInference 键全量快照，"
        "六个自命名物化真列承载高频查询字段（ADR-0003/0006/0012）。"
        "真列是权威来源，attributes 只是补充快照。无成本字段：成本是纯查询层推算结果。"
    ),
}

_COLUMN_COMMENTS: dict[str, dict[str, str]] = {
    "app.session": {
        "id": "前端生成（建议 UUIDv7）作为路由标识，后端不生成会话标识（ADR-0013）。",
        "deleted_at": (
            "软删除标记。硬删会打断 obs -> app 的外键，观测数据不能指向一个"
            "凭空消失的业务行（ADR-0002/0013）。查询默认过滤非 NULL 行。"
        ),
        "pruned_run_count": "削减计数：ADR-0019 第 2 层压缩每丢弃一块已完成运行就递增一次。",
    },
    "app.message": {
        "id": (
            "主键由应用层 uuid5(运行标识, 迭代序号[, 工具序号]) 派生，禁止数据库自增——"
            "评测 L2 回放可断言性的前提（ADR-0009）。"
        ),
        "seq": (
            "会话内显式排序，不靠时间戳——一次运行产出的多条消息时刻可能相同（ADR-0001）。"
            "落库时由服务层分配，与 id 的外部派生是两件独立的事。"
        ),
        "content": "完整内容块序列（文本/工具调用/工具结果），协议无关表示的落库形态（ADR-0007）。",
        "round_trip_payload": (
            "往返载荷——原生推理里回传给模型自己的那一半，按协议原样存放的不透明附件"
            "（ADR-0017）。只在产出它的那次运行内有效，运行终态收尾时清空为 NULL（ADR-0018）。"
        ),
    },
    "app.prompt_versions": {
        "version_id": '= f"{name}@{created_at}-{content_hash}"，内容的纯函数（ADR-0011）。',
    },
    "app.discovered_model": {
        "model_id": "原始模型标识，不做美化——它就是要粘进请求里的那个字符串（ADR-0016）。",
    },
    "obs.run": {
        "trigger_message_id": "触发本次运行的那条用户消息（ADR-0002）。",
        "last_message_seq": (
            "本次运行产出消息的 seq 上界——运行内消息在会话中总是连续的，因此"
            "[trigger 消息.seq, last_message_seq] 就是完整消息区间。"
            "运行开始时未知，落在 running 态时为 NULL。"
        ),
        "retention_window": (
            "保留窗口——ADR-0023 把它和提示词/工具版本号、运行终态并列为运行级字段。"
        ),
        "attributes": "记录本次运行模型输入中被掩蔽的观测标识列表（ADR-0019 观测掩蔽）。",
    },
    "obs.span": {
        "kind": "跨度种类（如 LLM/TOOL/CHAIN），对齐 Phoenix 通用跨度表形态（ADR-0003）。",
        "status": "跨度是否记为失败——外部失败（如工具报错）仍要落一条错误跨度，不能吞掉（ADR-0006）。",
        "role": "模型角色：main/auxiliary，判据是输出去向，不是调用层级（ADR-0012）。",
        "usage_status": "用量三态：缺失一律 NULL，不以 0 表示（CONTEXT.md 用量三态）。",
        "reasoning_tokens": (
            "推理 token——ADR-0003 把用量与调试细节的分界线定在这里，"
            "因此单独给真列而不是塞进 attributes；缺失同样记 NULL，不是 0。"
        ),
        "attributes": "OpenInference 语义约定键的全量快照（ADR-0003）。",
    },
}


def upgrade() -> None:
    for table, comment in _TABLE_COMMENTS.items():
        op.execute(f"COMMENT ON TABLE {table} IS {_quote(comment)}")
    for table, columns in _COLUMN_COMMENTS.items():
        for column, comment in columns.items():
            op.execute(f"COMMENT ON COLUMN {table}.{column} IS {_quote(comment)}")


def downgrade() -> None:
    for table in _TABLE_COMMENTS:
        op.execute(f"COMMENT ON TABLE {table} IS NULL")
    for table, columns in _COLUMN_COMMENTS.items():
        for column in columns:
            op.execute(f"COMMENT ON COLUMN {table}.{column} IS NULL")


def _quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"
