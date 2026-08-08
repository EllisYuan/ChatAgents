# 跨度表对齐 Phoenix：通用表加物化用量真列

跨度表要同时满足两件看似冲突的事：承载 OpenTelemetry / OpenInference 的标准语义（字段标准），以及支撑 token 面板的聚合查询（自建表供前端直查）。而这两套语义约定**都还没稳定**——截至 2026 年 8 月，OTel GenAI 语义约定全部字段仍是 Development 状态且无 1.0（v1.42.0 起还被移出主仓库到独立 repo），OpenInference 停在 0.1.31。

**决定：照抄 Arize Phoenix 的形态。** 通用跨度表（`kind` / `parent_span_id` / 时刻 / 状态）+ `attributes` JSONB 承载 OpenInference 全量语义 + 少数**物化真列**：[模型角色](../../CONTEXT.md)、模型名、输入 token、输出 token、[用量三态](../../CONTEXT.md)。非模型调用的跨度这几列留空。

这不是折中，就是行业规范本身。两个主流开源实现没有一个是纯 JSONB：Phoenix 的 `spans` 表有 `llm_token_count_prompt` / `llm_token_count_completion` 等真列，Langfuse 的 `observations` 表有 `provided_model_name` 真列与带类型的 `Map(String, Float64)` 用量。更有说服力的是 Phoenix 这几列的来历——它们是**后来由一个迁移加上去、从 `attributes` JSONB 回填的**，也就是说 Phoenix 当初正是纯 JSONB，撞上聚合的墙之后才迁成今天这样。这条路已经有人替我们走过了。

**OTel 规定的是传输协议与语义约定，从不规定存储 schema。** 「符合 OTel 规范」由 `attributes` 里承载标准 key 名满足；真列是实现层的物化投影，不破坏任何一致性——Phoenix 与 Langfuse 都是完全一致的，同时都有真列。

## 真列用自有命名

真列的名字不跟随任何上游。它们的语义来自本项目自己的决策（[用量三态](../../CONTEXT.md)、main/tool 分账），这些概念不随 OpenInference 或 OTel 的版本变动。上游 0.x 的漂移被关在 JSONB 里，碰不到聚合查询。Phoenix 同样如此——它的列叫 `llm_token_count_prompt`，是 Phoenix 自己的名字，不是 OpenInference 的 key。

**方向写死：真列是权威，JSONB 是附带快照。** 一个写入口同时填两边，读的时候只信真列。

`attributes` 里写 OpenInference 而非 `gen_ai.*`，是为了让导出到自托管 Phoenix 的深度调试链路零摩擦——既然表形态已经对齐 Phoenix，语义也随之对齐更连贯。

## 成本不落库

物理层只存原始 token 数与模型名。成本是[推算](../../CONTEXT.md)而非[观测事实](../../CONTEXT.md)，落库即固化——中转站调价或用户自带密钥会让存下的数字永久错下去，而 token 是物理事实永远不会错。价格矩阵一律在查询/导出层实时套用。

当前阶段只统计 token，不做价格换算。数据模型保留了随时补算的全部事实（token、模型名、模型角色、时刻），补算是纯查询层工作，**零 schema 变更**。

## 后果

观测数据分级老化：真列（用量与分账维度）永久保留，`attributes` JSONB（原始 payload，体积大头）过期后清空。成本与用量的历史统计因此永不失真，占空间的调试细节会老化。判断依据是跨度起始时刻，无需额外列。
