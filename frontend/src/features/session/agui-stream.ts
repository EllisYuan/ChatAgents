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
}

interface RunEnvelope {
  type: string;
  delta?: string;
  toolCallId?: string;
  toolCallName?: string;
  message?: string;
  name?: string;
  value?: unknown;
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
    const problem = (await response.json()) as ProblemDetails;
    throw new Error(problem.detail || problem.title);
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
