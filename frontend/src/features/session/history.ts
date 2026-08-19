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
 * 工具调用与工具结果块不在这里渲染——按 `features/trace/SPEC.md`，跨度树与
 * 工具卡片是 trace 面板（#69）的范围，这里只负责「正文仍在」这条验收标准。
 */
export function historyToMessages(detail: SessionDetail): ChatMessage[] {
  return (detail.messages ?? [])
    .filter((message) => message.role === "user" || message.role === "assistant")
    .map((message) => ({
      id: message.id,
      role: message.role as "user" | "assistant",
      text: textFromBlocks(message.content),
    }));
}
