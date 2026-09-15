# span表对齐 Phoenix：通用表+attributes全量语义+物化用量真列

[跨度（span）](../../CONTEXT.md#观测)表要同时满足两件看似冲突的事：承载 OpenInference 的标准语义（字段标准），以及支撑 token 面板的聚合查询（自建表供前端直查）。

**决定：照抄 Arize Phoenix 的形态。** 通用跨度表（`id` / `run_id` / `parent_span_id` / `name` / `kind` / `status` / `started_at` / `ended_at`）+ `attributes` JSONB 承载 OpenInference 全量语义 + 六个**物化真列**：`role`（[模型角色](../../CONTEXT.md#模型接入)）、`model`、`input_tokens`、`output_tokens`、`usage_status`（[用量三态](../../CONTEXT.md#观测)）、`reasoning_tokens`（[推理 token](../../CONTEXT.md#原生推理)）。非模型调用的跨度这六列留空。

## 真列用自有命名

真列的名字不跟随任何上游。它们的语义来自本项目自己的决策（[用量三态](../../CONTEXT.md#观测)、main/tool 分账），这些概念不随 OpenInference 或 OTel 的版本变动。

**方向写死：真列是权威，JSONB 是附带快照。** 一个写入口同时填两边，读的时候只信真列。

## 后果

观测数据分级老化：真列（[用量](../../CONTEXT.md#观测)与分账维度）永久保留，`attributes` JSONB（原始 payload，体积大头）过期后清空。成本与用量的历史统计因此永不失真，占空间的调试细节会老化。判断依据是跨度起始时刻，无需额外列。
