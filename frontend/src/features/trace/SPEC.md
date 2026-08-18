# Trace 合并规则（骨架约束）

本票只提供 trace 区域的 UI 接缝，不实现 stream parser 或跨度树合并。后续实现必须和本文件同 PR 修改，并遵守以下规则：

1. `STEP_*` 事件切分一次 agent iteration。
2. `chatagents.span` 创建模型 span。
3. `TOOL_CALL_START` 创建工具 span，`TOOL_CALL_END` 关闭工具 span。
4. `chatagents.tool_result` 填充工具卡片的结构化数据。
5. `TOOL_CALL_RESULT` 只提供渲染文本，不覆盖结构化结果。
6. 同一 iteration 内按事件到达顺序排序，不按时间戳重排。
7. AG-UI envelope 使用 camelCase；自有 payload 使用 snake_case。
8. 无效或缺少配对事件时保留可见的未完成 span，不静默丢弃。
