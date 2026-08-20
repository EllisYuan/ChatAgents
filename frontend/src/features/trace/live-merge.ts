import type { components } from "../../generated/api";
import type { RunEnvelope } from "../session/agui-stream";
import type {
  IterationGroup,
  ReasoningState,
  SpanStatus,
  ToolCardData,
  TraceSpanNode,
  TraceTree,
  UsageStatus,
} from "./types";

type UsagePayload = components["schemas"]["ChatAgentsUsagePayload"];
type SpanPayload = components["schemas"]["ChatAgentsSpanPayload"];
type ToolResultPayload = components["schemas"]["ChatAgentsToolResultPayload"];

/**
 * 直播跨度树的客户端合并（issue #69，规则见 `features/trace/SPEC.md`）。
 *
 * 跨度树由两处不对称拼出：AG-UI 的 `TOOL_CALL_START/END`（camelCase 信封）
 * 与自有的 `chatagents.span`/`chatagents.tool_result`（snake_case payload，
 * 走 `CUSTOM` 信封）。服务端不合并（ADR-0022），这里是唯一的合并点。
 *
 * `now` 由调用方传入（不读 `performance.now()`）——保持纯函数、可单测。
 */

interface PendingModelSpan {
  usage: UsagePayload | null;
  span: SpanPayload | null;
  reasoningText: string;
  reasoningOpen: boolean;
  reasoningStartedAt: number | null;
  reasoningDurationMs: number | null;
}

interface PendingToolSpan {
  toolCallId: string;
  name: string;
  argumentsRaw: string;
  startedAt: number;
  endedAt: number | null;
  result: ToolResultPayload | null;
}

interface IterationState {
  key: string;
  model: PendingModelSpan;
  tools: PendingToolSpan[];
}

export interface MergeState {
  runId: string | null;
  iterations: IterationState[];
  auxiliary: PendingModelSpan | null;
  /** `chatagents.usage` 的 `role` 决定紧随其后的 `chatagents.span` 该挂去哪——
   * 两条 CUSTOM 事件的到达顺序保证，不是猜测（SPEC 规则 2）。 */
  lastUsageRole: "main" | "auxiliary" | null;
}

export function emptyMergeState(): MergeState {
  return { runId: null, iterations: [], auxiliary: null, lastUsageRole: null };
}

function emptyModelSpan(): PendingModelSpan {
  return {
    usage: null,
    span: null,
    reasoningText: "",
    reasoningOpen: false,
    reasoningStartedAt: null,
    reasoningDurationMs: null,
  };
}

function currentIteration(state: MergeState): IterationState | null {
  return state.iterations.length > 0 ? state.iterations[state.iterations.length - 1] : null;
}

function findToolSpan(iteration: IterationState | null, toolCallId: string): PendingToolSpan | null {
  if (iteration === null) {
    return null;
  }
  return iteration.tools.find((tool) => tool.toolCallId === toolCallId) ?? null;
}

/** 纯函数：`(state, envelope, now) => state`，不读任何全局时钟（issue #69）。 */
export function mergeTraceEvent(state: MergeState, envelope: RunEnvelope, now: number): MergeState {
  const next: MergeState = {
    runId: state.runId,
    iterations: state.iterations,
    auxiliary: state.auxiliary,
    lastUsageRole: state.lastUsageRole,
  };

  switch (envelope.type) {
    case "RUN_STARTED": {
      next.runId = envelope.runId ?? null;
      return next;
    }

    case "STEP_STARTED": {
      next.iterations = [
        ...state.iterations,
        { key: `iteration-${state.iterations.length + 1}`, model: emptyModelSpan(), tools: [] },
      ];
      return next;
    }

    case "REASONING_MESSAGE_START": {
      const iteration = currentIteration(state);
      if (iteration === null) {
        return next;
      }
      next.iterations = replaceLastIteration(state, {
        ...iteration,
        model: {
          ...iteration.model,
          reasoningOpen: true,
          reasoningStartedAt: now,
        },
      });
      return next;
    }

    case "REASONING_MESSAGE_CONTENT": {
      const iteration = currentIteration(state);
      if (iteration === null) {
        return next;
      }
      next.iterations = replaceLastIteration(state, {
        ...iteration,
        model: {
          ...iteration.model,
          reasoningText: iteration.model.reasoningText + (envelope.delta ?? ""),
        },
      });
      return next;
    }

    case "REASONING_END": {
      const iteration = currentIteration(state);
      if (iteration === null || !iteration.model.reasoningOpen) {
        return next;
      }
      const startedAt = iteration.model.reasoningStartedAt;
      next.iterations = replaceLastIteration(state, {
        ...iteration,
        model: {
          ...iteration.model,
          reasoningOpen: false,
          reasoningDurationMs: startedAt !== null ? now - startedAt : null,
        },
      });
      return next;
    }

    case "TOOL_CALL_START": {
      const iteration = currentIteration(state);
      if (iteration === null) {
        return next;
      }
      const tool: PendingToolSpan = {
        toolCallId: envelope.toolCallId ?? "",
        name: envelope.toolCallName ?? "",
        argumentsRaw: "",
        startedAt: now,
        endedAt: null,
        result: null,
      };
      next.iterations = replaceLastIteration(state, {
        ...iteration,
        tools: [...iteration.tools, tool],
      });
      return next;
    }

    case "TOOL_CALL_ARGS": {
      const iteration = currentIteration(state);
      const tool = findToolSpan(iteration, envelope.toolCallId ?? "");
      if (iteration === null || tool === null) {
        return next;
      }
      next.iterations = replaceLastIteration(state, {
        ...iteration,
        tools: iteration.tools.map((entry) =>
          entry.toolCallId === tool.toolCallId
            ? { ...entry, argumentsRaw: entry.argumentsRaw + (envelope.delta ?? "") }
            : entry,
        ),
      });
      return next;
    }

    case "TOOL_CALL_END": {
      const iteration = currentIteration(state);
      const tool = findToolSpan(iteration, envelope.toolCallId ?? "");
      if (iteration === null || tool === null) {
        return next;
      }
      next.iterations = replaceLastIteration(state, {
        ...iteration,
        tools: iteration.tools.map((entry) =>
          entry.toolCallId === tool.toolCallId ? { ...entry, endedAt: now } : entry,
        ),
      });
      return next;
    }

    case "CUSTOM": {
      if (envelope.name === "chatagents.usage") {
        const payload = envelope.value as UsagePayload;
        next.lastUsageRole = payload.role;
        if (payload.role === "main") {
          const iteration = currentIteration(state);
          if (iteration === null) {
            return next;
          }
          next.iterations = replaceLastIteration(state, {
            ...iteration,
            model: { ...iteration.model, usage: payload },
          });
        } else {
          next.auxiliary = { ...(state.auxiliary ?? emptyModelSpan()), usage: payload };
        }
        return next;
      }

      if (envelope.name === "chatagents.span") {
        const payload = envelope.value as SpanPayload;
        if (state.lastUsageRole === "auxiliary") {
          next.auxiliary = { ...(state.auxiliary ?? emptyModelSpan()), span: payload };
        } else {
          const iteration = currentIteration(state);
          if (iteration === null) {
            return next;
          }
          next.iterations = replaceLastIteration(state, {
            ...iteration,
            model: { ...iteration.model, span: payload },
          });
        }
        return next;
      }

      if (envelope.name === "chatagents.tool_result") {
        const payload = envelope.value as ToolResultPayload;
        const iteration = currentIteration(state);
        const tool = findToolSpan(iteration, payload.tool_call_id);
        if (iteration === null || tool === null) {
          return next;
        }
        next.iterations = replaceLastIteration(state, {
          ...iteration,
          tools: iteration.tools.map((entry) =>
            entry.toolCallId === tool.toolCallId ? { ...entry, result: payload } : entry,
          ),
        });
        return next;
      }

      return next;
    }

    default:
      return next;
  }
}

function replaceLastIteration(state: MergeState, updated: IterationState): IterationState[] {
  if (state.iterations.length === 0) {
    return state.iterations;
  }
  return [...state.iterations.slice(0, -1), updated];
}

function usageStatusOf(usage: UsagePayload | null): UsageStatus | null {
  return usage?.usage_status ?? null;
}

function toolStatusOf(tool: PendingToolSpan): SpanStatus {
  if (tool.result === null) {
    return "pending";
  }
  return tool.result.structured !== null ? "ok" : "error";
}

function toolCardOf(tool: PendingToolSpan): ToolCardData {
  return {
    argumentsRaw: tool.argumentsRaw || null,
    result: tool.result?.result ?? null,
    structured: (tool.result?.structured as Record<string, unknown> | null | undefined) ?? null,
    durationMs: tool.result?.duration_ms ?? null,
  };
}

function toolSpanNode(tool: PendingToolSpan): TraceSpanNode {
  return {
    id: tool.toolCallId,
    kind: "tool",
    name: tool.name,
    status: toolStatusOf(tool),
    role: null,
    model: null,
    inputTokens: null,
    outputTokens: null,
    reasoningTokens: null,
    usageStatus: null,
    durationMs: tool.endedAt !== null ? tool.endedAt - tool.startedAt : null,
    reasoning: null,
    toolCard: toolCardOf(tool),
  };
}

function reasoningOf(model: PendingModelSpan): ReasoningState | null {
  if (!model.reasoningText && model.reasoningDurationMs === null) {
    return null;
  }
  return {
    text: model.reasoningText,
    durationMs: model.reasoningDurationMs,
    status: "available",
  };
}

function modelSpanNode(
  id: string,
  name: string,
  role: "main" | "auxiliary",
  model: PendingModelSpan,
): TraceSpanNode {
  return {
    id,
    kind: "llm",
    name,
    status: model.span !== null ? "ok" : "pending",
    role,
    model: model.usage?.model ?? null,
    inputTokens: model.usage?.input_tokens ?? null,
    outputTokens: model.usage?.output_tokens ?? null,
    reasoningTokens: model.usage?.reasoning_tokens ?? null,
    usageStatus: usageStatusOf(model.usage),
    durationMs: model.span?.duration_ms ?? null,
    reasoning: reasoningOf(model),
    toolCard: null,
  };
}

/** 把合并状态投影成 `TracePanel` 消费的渲染模型——纯投影，不含业务判断。 */
export function projectMergeState(state: MergeState): TraceTree {
  const iterations: IterationGroup[] = state.iterations.map((iteration) => ({
    key: iteration.key,
    modelSpan: modelSpanNode(`${iteration.key}:model`, "model_call", "main", iteration.model),
    toolSpans: iteration.tools.map(toolSpanNode),
  }));

  return {
    runId: state.runId,
    iterations,
    auxiliary:
      state.auxiliary !== null
        ? modelSpanNode("auxiliary:title", "title_generation", "auxiliary", state.auxiliary)
        : null,
    runConfig: null,
  };
}
