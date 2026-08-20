# Trace 合并规则

跨度树由两处不对称拼出：AG-UI 的 `TOOL_CALL_START/END`（camelCase 信封）与
自有的 `chatagents.span` / `chatagents.tool_result`（snake_case payload，走
`CUSTOM` 信封）。服务端不合并（ADR-0022），这是唯一的合并点。前端弱测试
（无 Vitest/RTL/Playwright，issue #17）之下这段逻辑零自动化覆盖，一份说得死
的规格是仅剩的防线——本文件必须与 `live-merge.ts` 的实现同 PR 修改。

## 直播事件序列（读自 `backend/src/chat_agents/transport/sse.py`）

```
RUN_STARTED(runId)
每次迭代：
  STEP_STARTED(stepName="iteration-N")
  [REASONING_START, REASONING_MESSAGE_START, REASONING_MESSAGE_CONTENT(delta)*,
   REASONING_MESSAGE_END, REASONING_END]              — 可选，有推理才有
  TEXT_MESSAGE_START, TEXT_MESSAGE_CONTENT(delta)*, TEXT_MESSAGE_END
  [TOOL_CALL_START(toolCallId,toolCallName)
   / TOOL_CALL_ARGS(toolCallId,delta)
   → TOOL_CALL_END(toolCallId)
   / TOOL_CALL_RESULT(渲染文本)
   / CUSTOM chatagents.tool_result(tool_call_id,result,duration_ms,structured)]*
                                                        — 0~N 个，并发的按到达顺序交错出现
  STEP_FINISHED(stepName)
  CUSTOM chatagents.usage(role="main", model, usage_status,
                           input_tokens, output_tokens, reasoning_tokens)
  CUSTOM chatagents.span(span_id, parent_span_id=null, kind="llm", duration_ms)
[任意时机可能插入，不在任何 STEP 内]：
  CUSTOM chatagents.title / chatagents.usage(role="auxiliary") / chatagents.span（标题跨度）
RUN_FINISHED | RUN_ERROR
```

## 合并规则（`live-merge.ts` 的 `mergeTraceEvent` 实现）

1. `STEP_STARTED` 起一个新的迭代分组，此后到达的 `TOOL_CALL_START`/推理/工具
   事件都归入「最后一个迭代分组」，直到下一个 `STEP_STARTED`。
2. `chatagents.usage` 的 `role` 字段决定路由：`main` → 挂到当前迭代分组的
   模型跨度；`auxiliary` → 挂到独立的「标题」兄弟槽位，不进任何迭代分组。
   **紧跟着到达的 `chatagents.span`（它本身不带 role）复用上一条 usage 的
   路由目标**——这是两条 `CUSTOM` 事件的到达顺序保证，不是猜测。
3. `TOOL_CALL_START` 在当前迭代分组内按到达顺序追加一个工具跨度占位；
   `TOOL_CALL_END` 标记结束时刻；`chatagents.tool_result` 按 `tool_call_id`
   回填卡片字段（`structured`、`result`、`duration_ms`）；`TOOL_CALL_RESULT`
   只提供渲染文本，不覆盖结构化数据。
4. 同一迭代分组内的模型跨度与工具跨度**按事件到达顺序排列，不按时间
   戳**——并发工具调用因此天然保持兄弟关系不被重排打乱。
5. 推理耗时用 `REASONING_MESSAGE_START`→`REASONING_END` 到达的墙钟差客户端
   计时（wire 协议不单独发耗时）；`mergeTraceEvent` 接收 `now` 作为显式参数，
   不读 `performance.now()`，保持纯函数、可单测。
6. 缺配对事件（如断连截断在 `TOOL_CALL_START` 之后）时保留可见的未完成
   节点（`status: "pending"`），不静默丢弃。
7. AG-UI envelope 使用 camelCase；自有 payload（`chatagents.*` 的 `value`）
   使用 snake_case——两者不做统一改名，字段名直接照抄各自来源。
8. 工具跨度的 `status` 由 `structured !== null` 判定：只有真正跑通的工具
   调用才会产出结构化结果，耗尽重试的外部失败恒为 `null`。这不是猜测，是
   后端 `ToolFinished.structured` 的结构性事实（见下方「已知缺口」之前的
   后端改动）。

## 历史视图（`from-run-detail.ts`）

`GET /api/runs/{run_id}` 返回的 `RunDetail.spans` 已经由后端按
`parent_span_id` 落好树，不需要重新按事件到达顺序拼：`kind:"llm",
role:"main"` 的顶层跨度各自是一个迭代分组，其下 `kind:"tool"` 的子跨度是
该迭代内的工具调用；`role:"auxiliary"` 的顶层跨度是独立的标题兄弟跨度。

历史视图**没有独立的思考耗时字段**——持久化只有 `display_summary.text/status`，
模型跨度的总耗时含生成时间，不是思考耗时，因此历史视图的推理行不显示秒数，
只显示「▸ 思考」。

## 已知缺口（本票不实现，已开 follow-up issue）

- **工具重试不可见**（[#76](https://github.com/EllisYuan/ChatAgents/issues/76)）：
  `ToolExecutor.execute()` 内部的重试循环对 `agent/events` 完全不可见——
  `ToolStarted`/`ToolFinished` 每个 `tool_call_id` 各一次，没有中间尝试
  事件。把每次尝试从 `asyncio.gather` 并发协程里有序穿出来需要新的领域
  事件类型与并发下的顺序保证，是独立的一次架构改动。直播与历史视图都看
  不到重试过程，只看到最终结果。
- **观察掩蔽无数据源**（[#77](https://github.com/EllisYuan/ChatAgents/issues/77)）：
  ADR-0019/0028 提到掩蔽状态该记在跨度 `attributes` 里、前端只读，但目前
  没有任何代码写这个字段（`pruned_run_count` 那条「整轮削减」已经打通，
  是另一回事）。工具卡片旁「模型现在只看到标题与 URL」那行标注在后端补
  上这个字段之前不会出现。
