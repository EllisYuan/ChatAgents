# Observability 运行观测

## 职责

`observability/` 把 `RunEvent` 投影为 run/span 树，写入 `obs` schema，并提供 Trace 与用量查询。观测失败只能降低可见性，不能改变业务结果。

## 入口与边界

- `streaming.py::observe`：包裹事件流并维护 run/span 生命周期。
- `writer.py::RunWriter`：独立短事务增量写入；异常就地记录并吞掉。
- `repository.py::ObservabilityRepository`：只查询 `obs` schema。
- `models.py`：观测查询契约。
- `reasoning.py`：原生 reasoning 显示摘要到跨度属性的纯投影。

## 依赖方向

允许依赖 `agent/` 的运行事件、`llm/` 的用量状态和 `db/` 的观测表。反向依赖被禁止：`agent/`、`conversation/`、`llm/`、`tools/` 均不得 import `observability/`。

## 不变量

1. 业务写入与观测写入使用不同短事务，物理上不能同事务提交。
2. 观测写失败只记日志，不让线上运行失败。
3. 断连时未闭合跨度标记 `partial`、运行标记 `aborted`，不伪造完成。
4. 一个 handler 只碰一个 schema；跨 schema 关联在应用层完成。
5. `partial` 用量不进入确定性总量，不可用值不以 0 代替。

## 决策来源

[ADR-0002](../../../../docs/adr/0002-business-and-observability-share-a-database.md) · [ADR-0017](../../../../docs/adr/0017-native-reasoning-is-two-things.md) · [ADR-0020](../../../../docs/adr/0020-there-is-one-token-yardstick.md) · [ADR-0022](../../../../docs/adr/0022-one-handler-touches-one-schema.md) · [ADR-0023](../../../../docs/adr/0023-absent-fields-say-why.md)
