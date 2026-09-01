# Agent 运行时

## 职责

`agent/` 是纯异步 ReAct 运行时：接收模型消息、端点档案和运行配置，通过 `ModelPort` 与 `ToolExecutor` 完成「模型决策 → 工具执行 → 观察回注 → 终止判定」，只产出 `RunEvent`。

## 入口与边界

- `runner.py::AgentRunner.run`：运行循环入口；不碰数据库、HTTP/SSE 或观测存储。
- `events.py::RunEvent`：一次运行对外的领域事件，区别于单次模型调用的 `llm.events.ModelEvent`。
- `tool_executor.py::ToolExecutor`：执行工具的唯一入口，集中超时、重试与错误分类。
- `step_budget.py::STEP_BUDGETS`：执行档位的软预算和硬上限。
- `versioning.py`：系统提示词与工具 schema 的规范化快照和版本同步。

## 依赖方向

允许依赖 `llm/`、`tools/`、`db/` 和共享叶子。不得依赖 `conversation/`、`observability/` 或 `transport/`；落消息、落跨度和线格式由外层包装完成。

## 不变量

1. Runner 只经 `ModelPort` 和 `ToolExecutor` 触碰 I/O。
2. 工具调用只能从 `ToolExecutor` 发出，不能在 Runner 或工具实现外另开旁路。
3. 系统提示词是运行配置，不进入消息表。
4. `RunEvent` 不携带 SSE 帧或供应商协议格式。

## 决策来源

[ADR-0006](../../../../docs/adr/0006-tool-failures-split-into-external-and-programmatic.md) · [ADR-0008](../../../../docs/adr/0008-a-run-emits-domain-events-not-wire-frames.md) · [ADR-0010](../../../../docs/adr/0010-the-system-prompt-is-run-configuration-not-conversation-memory.md) · [ADR-0011](../../../../docs/adr/0011-model-input-configuration-is-versioned-and-persisted.md) · [ADR-0025](../../../../docs/adr/0025-replay-happens-at-the-model-port-not-the-http-transport.md)
