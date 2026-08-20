/**
 * trace 面板的统一渲染模型（issue #69）。
 *
 * 直播（`live-merge.ts`）与历史（`from-run-detail.ts`）两条数据路径最终都
 * 产出这一套形状，`TracePanel` 及其子组件只认识这一套，不关心数据来自哪条
 * 路径——两条路径的差异（比如历史视图没有推理耗时）体现在字段是否为
 * `null`，不体现在组件分支上。
 */

export type UsageStatus = "complete" | "partial" | "unavailable";

export interface ToolCardData {
  /** 累积的入参 JSON 文本；直播时来自 `TOOL_CALL_ARGS` 增量，历史视图来自持久化的 `arguments`。 */
  argumentsRaw: string | null;
  /** 渲染给模型的文本，同 `chatagents.tool_result.result` / `SpanView.tool_result.result`。 */
  result: string | null;
  /** 结构化结果——只有真正跑通的工具调用才有，`null` 是「耗尽重试的外部失败」这条结构性事实。 */
  structured: Record<string, unknown> | null;
  durationMs: number | null;
}

export interface ReasoningState {
  text: string | null;
  /** 历史视图没有独立的思考耗时字段，如实留空，不用模型跨度总耗时冒充。 */
  durationMs: number | null;
  status: "available" | "aged_out";
}

export type SpanStatus = "pending" | "ok" | "error";

export interface TraceSpanNode {
  id: string;
  kind: "llm" | "tool";
  /** 工具名，或 `model_call` / `title_generation`。 */
  name: string;
  status: SpanStatus;
  role: "main" | "auxiliary" | null;
  model: string | null;
  inputTokens: number | null;
  outputTokens: number | null;
  reasoningTokens: number | null;
  usageStatus: UsageStatus | null;
  durationMs: number | null;
  reasoning: ReasoningState | null;
  toolCard: ToolCardData | null;
}

export interface IterationGroup {
  key: string;
  modelSpan: TraceSpanNode;
  toolSpans: TraceSpanNode[];
}

export interface RunConfig {
  promptVersionId: string | null;
  toolSchemaVersionId: string | null;
  effort: string | null;
  retentionWindow: number | null;
  prunedRunCount: number | null;
}

export interface TraceTree {
  runId: string | null;
  iterations: IterationGroup[];
  auxiliary: TraceSpanNode | null;
  runConfig: RunConfig | null;
}

export function emptyTraceTree(): TraceTree {
  return { runId: null, iterations: [], auxiliary: null, runConfig: null };
}
