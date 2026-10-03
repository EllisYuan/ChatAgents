# Conversation 会话与消息

## 职责

`conversation/` 管理会话、消息和模型输入投影。消息表是对话记忆的唯一事实来源；历史观察的压缩只发生在模型输入投影上，不改写原始消息。

## 入口与边界

- `service.py::ConversationService`：会话规则、消息序列重建与事务编排；标题生成的一次性认领、终态记录与条件应用（`short_transaction_*`，模型调用期间不持有事务）。
- `repository.py::ConversationRepository`：只做 `app` schema 数据访问，不开事务、不承载业务规则。
- `streaming.py::persist`：消费 `RunEvent`，以短事务增量落消息。
- `masking.py::mask_tool_observations`：历史工具观察的非破坏性投影。
- `router.py`：HTTP 与领域类型的边界。
- `models.py`：会话/消息 DTO 与标题生成请求/响应类型（`TitleGenerationRequest` / `TitleGenerationResponse`）。

## 依赖方向

允许依赖 `agent/` 的领域事件、`llm/` 的消息类型、`db/` 和共享叶子。不得依赖 `observability/`；观测层可读取业务事实，业务层不能反向认识观测实现。

## 不变量

1. 持久化消息是恢复源，Agent 状态快照不是。
2. 掩蔽只改投影，不改消息表；工具调用与参数始终保留。
3. 流式运行使用短事务，不在整个 SSE 生命周期占用请求级 session。
4. repository 默认过滤软删除，不提供泛化 `find(**filters)`。
5. 新会话随首条用户消息建立 fallback 和持久化自动生成资格；原子认领只成功一次，历史行默认不合格。人工改名（包括改为相同文字或清空）持久关闭应用资格；生成结果只在仍未人工改名且未软删除时提交，消息表不存辅助输出。
6. 标题生成是会话级独立调用，不属主运行生命周期。一次唯一尝试在 `app.session.title_generation_outcome` 记录终态（`applied` / `fallback` / `manual_not_applied`），`NULL` 表示已认领未终态；响应状态 `generating` / `processed` 由列值派生，不落库。素材只取服务端 `seq` 最小的用户消息；失败、超时、取消与未应用都不重开资格，业务响应不携带原始错误载荷。

## 决策来源

[ADR-0001](../../../../docs/adr/0001-messages-are-the-single-source-of-truth.md) · [ADR-0002](../../../../docs/adr/0002-business-and-observability-share-a-database.md) · [ADR-0019](../../../../docs/adr/0019-old-observations-are-masked-not-summarized.md) · [ADR-0022](../../../../docs/adr/0022-one-handler-touches-one-schema.md) · [ADR-0037](../../../../docs/adr/0037-session-title-attempt-is-once.md) · [ADR-0036](../../../../docs/adr/0036-title-generation-is-an-independent-session-call.md)
