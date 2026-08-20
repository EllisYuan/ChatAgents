import type { SessionDetail } from "../../api/client";
import type { ChatMessage } from "./chat-types";

function textFromBlocks(content: Record<string, unknown>[]): string {
  return content
    .filter((block) => block.type === "text" && typeof block.text === "string")
    .map((block) => block.text as string)
    .join("");
}

/**
 * 把持久化历史压成聊天气泡：只取 user/assistant 的文本块。
 *
 * 工具调用与工具结果块不在这里渲染——那是跨度树，走 `features/trace/`，
 * 这里只负责「正文仍在」这条验收标准；`seq` 透传给 trace 面板用来匹配
 * `GET /api/sessions/{id}/runs` 里的 `last_message_seq`（issue #69）。
 */
export function historyToMessages(detail: SessionDetail): ChatMessage[] {
  return (detail.messages ?? [])
    .filter((message) => message.role === "user" || message.role === "assistant")
    .map((message) => ({
      id: message.id,
      role: message.role as "user" | "assistant",
      text: textFromBlocks(message.content),
      seq: message.seq,
    }));
}
