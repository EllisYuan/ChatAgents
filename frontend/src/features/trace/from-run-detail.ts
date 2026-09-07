import type { components } from "../../generated/api";
import type { IterationGroup, ReasoningState, RunConfig, SpanStatus, TraceSpanNode, TraceTree } from "./types";

type RunDetail = components["schemas"]["RunDetail"];
type SpanView = components["schemas"]["SpanView"];

/**
 * 把持久化的 `RunDetail`（`GET /api/runs/{run_id}`）映射成 trace 面板的统一
 * 渲染模型（issue #69）——历史视图专用，不走 `live-merge.ts` 的事件合并。
 *
 * 持久化的跨度树没有显式的「迭代」分组节点：`kind:"llm", role:"main"` 的
 * 顶层跨度各自就是一个迭代（`parent_span_id` 已经把该迭代内的工具跨度挂在
 * 它下面），`role:"auxiliary"` 的顶层跨度是独立的标题兄弟跨度，不进任何
 * 迭代分组——这跟直播合并规则 2 的路由结果是同一棵树，只是持久化时已经
 * 由后端按 `parent_span_id` 落好了，不需要重新按事件到达顺序拼。
 */
export function traceTreeFromRunDetail(detail: RunDetail): TraceTree {
  const mainSpans = detail.spans.filter((span) => span.kind === "llm" && span.role === "main");
  const auxiliarySpan = detail.spans.find((span) => span.kind === "llm" && span.role === "auxiliary");

  const iterations: IterationGroup[] = mainSpans.map((span, index) => ({
    key: `iteration-${index + 1}`,
    modelSpan: spanNode(span),
    toolSpans: span.children.filter((child) => child.kind === "tool").map(spanNode),
  }));

  return {
    runId: detail.id,
    iterations,
    auxiliary: auxiliarySpan ? spanNode(auxiliarySpan) : null,
    runConfig: runConfigFrom(detail),
  };
}

function runConfigFrom(detail: RunDetail): RunConfig {
  return {
    promptVersionId: detail.prompt_version_id,
    toolSchemaVersionId: detail.tool_schema_version_id,
    effort: detail.effort,
    retentionWindow: detail.retention_window,
    prunedRunCount: detail.pruned_run_count,
  };
}

function durationMsOf(span: SpanView): number | null {
  if (span.ended_at === null) {
    return null;
  }
  return new Date(span.ended_at).getTime() - new Date(span.started_at).getTime();
}

function statusOf(span: SpanView): SpanStatus {
  if (span.status === "ok") {
    return "ok";
  }
  if (span.status === "error") {
    return "error";
  }
  return "pending";
}

function reasoningOf(span: SpanView): ReasoningState | null {
  if (!span.display_summary) {
    return null;
  }
  // 历史视图没有独立的思考耗时字段——模型跨度总耗时含生成时间，不是思考
  // 耗时，如实留空不冒充（issue #69 计划）。
  return { text: span.display_summary.text, durationMs: null, status: span.display_summary.status };
}

function spanNode(span: SpanView): TraceSpanNode {
  const isTool = span.kind === "tool";
  return {
    id: span.id,
    kind: isTool ? "tool" : "llm",
    name: span.name,
    status: statusOf(span),
    role: (span.role as "main" | "auxiliary" | null) ?? null,
    model: span.model,
    inputTokens: span.input_tokens,
    outputTokens: span.output_tokens,
    reasoningTokens: span.reasoning_tokens ?? null,
    usageStatus: span.usage_status,
    durationMs: durationMsOf(span),
    reasoning: isTool ? null : reasoningOf(span),
    toolCard: isTool
      ? {
          argumentsRaw: span.arguments ? JSON.stringify(span.arguments) : null,
          result: span.tool_result?.result ?? null,
          structured: (span.tool_result?.structured as Record<string, unknown> | null | undefined) ?? null,
          durationMs: durationMsOf(span),
        }
      : null,
  };
}
