export type ChatRole = "user" | "assistant";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  text: string;
  /** 持久化历史消息的序号；直播中新产出的消息还没有 seq，为 `null`（issue #69：trace 面板按它匹配运行）。 */
  seq: number | null;
}

/**
 * `complete` —— 全部 `chatagents.usage` 都是 `complete` 状态。
 * `incomplete` —— 运行正常收尾，但某次模型调用的用量是 `partial`/`unavailable`。
 * `disconnected` —— 流在 `RUN_FINISHED`/`RUN_ERROR` 之前就结束了（见 issue #65）。
 */
export type UsageStatus = "complete" | "incomplete" | "disconnected";

export interface RunSummary {
  steps: number;
  tokens: number | null;
  usageStatus: UsageStatus;
  durationMs: number;
}
