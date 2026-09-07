import { EventSourceParserStream } from "eventsource-parser/stream";

import type { components } from "../../generated/api";

type RunRequest = components["schemas"]["RunRequest"];
type ProblemDetails = components["schemas"]["ProblemDetails"];
type UsagePayload = components["schemas"]["ChatAgentsUsagePayload"];
type TitlePayload = components["schemas"]["ChatAgentsTitlePayload"];

interface RunStreamHandlers {
  onTextDelta(delta: string): void;
  onStepStarted(): void;
  onToolStarted(toolCallId: string, name: string): void;
  onToolEnded(toolCallId: string): void;
  onUsage(payload: UsagePayload): void;
  onTitleGenerated(sessionId: string, title: string): void;
  onRunFinished(): void;
  onRunError(message: string): void;
  /**
   * trace 面板专用的原始信封转发（issue #69）——`features/trace/live-merge.ts`
   * 按 `envelope.type` 自己 pattern-match，这里不代它翻译语义，只转发这份合并
   * 逻辑用得到的事件类型：`RUN_STARTED`、`STEP_STARTED/FINISHED`、
   * `REASONING_*`、`TOOL_CALL_START/ARGS/END`、`CUSTOM chatagents.span` 与
   * `chatagents.tool_result`。
   */
  onTraceEvent?(envelope: RunEnvelope): void;
}

export interface RunEnvelope {
  type: string;
  delta?: string;
  toolCallId?: string;
  toolCallName?: string;
  message?: string;
  name?: string;
  value?: unknown;
  runId?: string;
  stepName?: string;
  messageId?: string;
}

const TRACE_EVENT_TYPES = new Set([
  "RUN_STARTED",
  "STEP_STARTED",
  "STEP_FINISHED",
  "REASONING_START",
  "REASONING_MESSAGE_START",
  "REASONING_MESSAGE_CONTENT",
  "REASONING_MESSAGE_END",
  "REASONING_END",
  "TOOL_CALL_START",
  "TOOL_CALL_ARGS",
  "TOOL_CALL_END",
  "CUSTOM",
]);

/**
 * 从失败响应里取一句可读的错误。
 *
 * 后端的失败带 RFC 9457 的 `ProblemDetails` 正文，但**不是每个 500 都来自后端**：
 * dev 代理连不上后端、网关超时时正文是空的，无条件 `response.json()` 会抛
 * 「Unexpected end of JSON input」，把真正的状态码盖掉——排查会被引向错误方向。
 * 拿不到结构化正文时回落到状态码本身。
 */
async function problemMessage(response: Response): Promise<string> {
  try {
    const problem = (await response.json()) as ProblemDetails;
    const detail = problem.detail || problem.title;
    if (detail) {
      return detail;
    }
  } catch {
    // 正文不是 JSON——落到下面的状态码
  }
  return `请求失败：HTTP ${response.status}`;
}

/**
 * 发起一次运行并消费 AG-UI over SSE 的事件流（issue #65）。
 *
 * 自写而非 `eventsource` 包——后者含自动重连，断连会闷声重开一次运行、重复
 * 烧钱，这是产品决策不是偏好。这里用 `fetch` + `eventsource-parser` 手写单次
 * 消费：流结束（无论正常收尾还是断连）就地停下，从不重试。
 */
export async function streamRun(
  request: RunRequest,
  handlers: RunStreamHandlers,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch("/api/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(request),
    signal,
  });

  if (!response.ok) {
    throw new Error(await problemMessage(response));
  }
  if (!response.body) {
    throw new Error("响应没有可读的流");
  }

  const stream = response.body
    .pipeThrough(new TextDecoderStream())
    .pipeThrough(new EventSourceParserStream());

  for await (const event of stream) {
    if (!event.data) {
      continue;
    }
    dispatch(JSON.parse(event.data) as RunEnvelope, handlers);
  }
}

function dispatch(envelope: RunEnvelope, handlers: RunStreamHandlers): void {
  if (TRACE_EVENT_TYPES.has(envelope.type)) {
    handlers.onTraceEvent?.(envelope);
  }
  switch (envelope.type) {
    case "TEXT_MESSAGE_CONTENT":
      handlers.onTextDelta(envelope.delta ?? "");
      break;
    case "STEP_STARTED":
      handlers.onStepStarted();
      break;
    case "TOOL_CALL_START":
      handlers.onToolStarted(envelope.toolCallId ?? "", envelope.toolCallName ?? "");
      break;
    case "TOOL_CALL_END":
      handlers.onToolEnded(envelope.toolCallId ?? "");
      break;
    case "CUSTOM":
      if (envelope.name === "chatagents.usage") {
        handlers.onUsage(envelope.value as UsagePayload);
      } else if (envelope.name === "chatagents.title") {
        const payload = envelope.value as TitlePayload;
        handlers.onTitleGenerated(payload.session_id, payload.title);
      }
      break;
    case "RUN_FINISHED":
      handlers.onRunFinished();
      break;
    case "RUN_ERROR":
      handlers.onRunError(envelope.message ?? "运行失败");
      break;
    default:
      break;
  }
}
