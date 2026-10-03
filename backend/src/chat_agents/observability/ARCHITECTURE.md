# Observability 运行观测

## 职责

`observability/` 把主 `RunEvent` 投影为 run/span 树，也记录独立的会话标题跨度，写入 `obs` schema，并提供 Trace 与用量查询。观测失败只能降低可见性，不能改变业务结果。

## 入口与边界

- `streaming.py::observe`：包裹事件流并维护 run/span 生命周期。
- `writer.py::RunWriter`：独立短事务增量写入；异常就地记录并吞掉。
- `repository.py::ObservabilityRepository`：只查询 `obs` schema；`GET /api/sessions/{session_id}/title-generation` 读取直属跨度与历史运行标题跨度，不读取业务 `title`。当前会话列表不提供该接口的展示入口。
- `models.py`：观测查询契约。
- `reasoning.py`：原生 reasoning 显示摘要到跨度属性的纯投影。

## 依赖方向

允许依赖 `agent/` 的运行事件、`llm/` 的用量状态和 `db/` 的观测表。反向依赖被禁止：`agent/`、`conversation/`、`llm/`、`tools/` 均不得 import `observability/`。

## 不变量

1. 业务写入与观测写入使用不同短事务，物理上不能同事务提交。
2. 观测写失败只记异常类型，不记录原始错误载荷、密钥或完整配置；失败不改变标题业务提交或主运行结果。
3. 断连时未闭合跨度标记 `partial`、运行标记 `aborted`，不伪造完成。
4. 一个 handler 只碰一个 schema；跨 schema 关联在应用层完成。
5. `partial` 用量不进入确定性总量，不可用值不以 0 代替。
6. 主运行跨度的模型列取自运行事件；独立标题跨度由 HTTP 装配层按本次实际辅助模型显式写入，不能从历史运行推断。
7. 跨度恰有一种归属：原运行 `run_id` 或独立会话 `session_id`。后者是根跨度，独立短事务写入，不创建伪运行；运行详情和统计只查询其原有 `run_id`，历史标题跨度仍归原运行。
8. 标题观测无记录时返回空集合，旧字段缺失保持未知；查询不暴露 `key_source` 或完整属性，观测查询失败不影响会话业务。

## 决策来源

[ADR-0002](../../../../docs/adr/0002-business-and-observability-share-a-database.md) · [ADR-0036](../../../../docs/adr/0036-title-generation-is-an-independent-session-call.md) · [ADR-0035](../../../../docs/adr/0035-session-owned-title-spans.md) · [ADR-0017](../../../../docs/adr/0017-native-reasoning-is-two-things.md) · [ADR-0020](../../../../docs/adr/0020-there-is-one-token-yardstick.md) · [ADR-0022](../../../../docs/adr/0022-one-handler-touches-one-schema.md) · [ADR-0023](../../../../docs/adr/0023-absent-fields-say-why.md)
