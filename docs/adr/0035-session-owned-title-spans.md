# 会话标题跨度可独立归属会话

> **展示范围调整（2026-10-03）**：保留本 ADR 的标题跨度写入、归属和只读查询接口；会话列表不提供标题详情按钮，也不请求标题观测。其他页面的展示入口后续另行设计。

Issue #92 是 [#90](https://github.com/EllisYuan/ChatAgents/issues/90) 的观测切片：当前标题仍由主运行生成，历史跨度继续归原 `obs.run`。本次只扩展未来独立标题调用所需的归属，以及历史标题观测的只读入口；**没有拆分标题生命周期，也没有改写历史运行统计或 `ended_at`**。

**决定：`obs.span` 有且只有一个归属：`run_id` 或 `session_id`。** 运行跨度沿用 `run_id`；独立会话跨度通过 `session_id` 外键指向 `app.session`，且 `parent_span_id IS NULL`。数据库 CHECK 防止无归属、双归属以及会话跨度悬挂在运行跨度下。独立标题调用无需伪造 `obs.run`，但本切片不触发新的标题模型调用。写入入口沿用独立短事务及 best-effort 故障隔离，模型调用成功与标题是否应用是不同事实，后者只有在显式记录时才展示。

这先修订 [ADR-0012](./0012-the-auxiliary-model-never-writes-to-the-message-table.md) 中「标题跨度必须挂在运行上」的*数据模型前提*；[ADR-0036](./0036-title-generation-is-an-independent-session-call.md) 随后拆分生成生命周期，`auxiliary` 的输出去向与旧运行生命周期保持不变。[ADR-0003](./0003-span-table-follows-phoenix.md) 的六个用量真列、按 `started_at` 老化 `attributes` 的既定保留口径继续适用于两种归属（当前尚未实现老化作业）；现有运行查询只按 `run_id` 取跨度，因此独立会话跨度不会进入运行树或统计，旧标题跨度仍在原运行中。

`GET /api/sessions/{session_id}/title-generation` 仅查 `obs`：直属 `session_id` 跨度及经 `obs.run.session_id` 找到的旧 `name="title_generation"`、`role="auxiliary"` 跨度。返回真实 `model`、时间、状态与物化用量；缺失的 `effort` 保持 `null`，未记录错误原因与应用结果时根本不暴露这些字段，没有跨度则返回空列表，不通过当前业务 `title` 推断成功。公开载荷只用明确白名单，不展示 `key_source` 或完整 `attributes`。会话列表仍只读业务事实（ADR-0013），不提供标题观测入口；查询接口与标题业务独立（ADR-0022）。

迁移新增可空 `session_id`、外键和索引，放宽 `run_id NOT NULL` 并添加归属 CHECK；没有删除旧列、改写旧行或更改旧外键。它超出了 [ADR-0031](./0031-migrations-are-additive-only.md) 所举的单纯「加列」例子，但旧代码总写非空 `run_id` 且不写 `session_id`，因此其写入继续满足 CHECK，回滚旧镜像对新 schema 仍可工作。旧代码不会看到新独立跨度（按 `run_id` 查询），也不会更改它们。`downgrade` 不参与部署。会话软删除保留外键指向的业务行；当前观测保留策略按 `started_at` 而非通过 `run_id` 遍历，后续新增保留任务必须同时覆盖 `run_id IS NULL` 的会话跨度。
