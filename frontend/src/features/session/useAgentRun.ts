import { useCallback, useEffect, useRef, useState } from "react";

import { getSessionDetail } from "../../api/client";
import { streamRun } from "./agui-stream";
import type { ChatMessage, RunSummary } from "./chat-types";
import { historyToMessages } from "./history";

type RunPhase = "idle" | "streaming";

/**
 * 一个会话的消息状态与运行流消费（issue #65：前端的 tracer bullet）。
 *
 * 摘要行按消息 id 分开存放（而不是单个 `summary` 值）——同一会话里连续问几轮，
 * 每一轮回答都各自留一行摘要，不会被下一轮覆盖。
 */
export function useAgentRun(sessionId: string) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [phase, setPhase] = useState<RunPhase>("idle");
  const [streamingId, setStreamingId] = useState<string | null>(null);
  const [summaries, setSummaries] = useState<Record<string, RunSummary>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [activeTool, setActiveTool] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let cancelled = false;
    abortRef.current?.abort();
    setHistoryLoaded(false);
    setPhase("idle");
    setStreamingId(null);
    void getSessionDetail(sessionId).then((detail) => {
      if (cancelled) return;
      setMessages(detail ? historyToMessages(detail) : []);
      setHistoryLoaded(true);
    });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  useEffect(() => () => abortRef.current?.abort(), []);

  const sendMessage = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || phase === "streaming") {
        return;
      }

      const assistantId = crypto.randomUUID();
      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: "user", text: trimmed },
        { id: assistantId, role: "assistant", text: "" },
      ]);
      setPhase("streaming");
      setStreamingId(assistantId);
      setActiveTool(null);
      setErrors((prev) => omit(prev, assistantId));

      const controller = new AbortController();
      abortRef.current = controller;

      let steps = 0;
      let tokens = 0;
      let usageIncomplete = false;
      let finished = false;
      let failed = false;
      const startedAt = performance.now();

      try {
        await streamRun(
          { session_id: sessionId, message: trimmed, effort: "medium" },
          {
            onTextDelta(delta) {
              setMessages((prev) =>
                prev.map((message) =>
                  message.id === assistantId ? { ...message, text: message.text + delta } : message,
                ),
              );
            },
            onStepStarted() {
              steps += 1;
            },
            onToolStarted(_toolCallId, name) {
              setActiveTool(name);
            },
            onToolEnded() {
              setActiveTool(null);
            },
            onUsage(payload) {
              if (payload.usage_status !== "complete") {
                usageIncomplete = true;
                return;
              }
              tokens +=
                (payload.input_tokens ?? 0) +
                (payload.output_tokens ?? 0) +
                (payload.reasoning_tokens ?? 0);
            },
            onRunFinished() {
              finished = true;
            },
            onRunError(message) {
              failed = true;
              setErrors((prev) => ({ ...prev, [assistantId]: message }));
            },
          },
          controller.signal,
        );
      } catch (error) {
        if (controller.signal.aborted) {
          return;
        }
        failed = true;
        setErrors((prev) => ({
          ...prev,
          [assistantId]: error instanceof Error ? error.message : "连接中断，请重试",
        }));
      }

      if (controller.signal.aborted) {
        return;
      }

      setActiveTool(null);
      setPhase("idle");
      setStreamingId(null);
      const disconnected = !finished && !failed;
      setSummaries((prev) => ({
        ...prev,
        [assistantId]: {
          steps,
          durationMs: performance.now() - startedAt,
          usageStatus: disconnected ? "disconnected" : usageIncomplete ? "incomplete" : "complete",
          tokens: disconnected || usageIncomplete ? null : tokens,
        },
      }));
    },
    [phase, sessionId],
  );

  return { messages, historyLoaded, phase, streamingId, summaries, errors, activeTool, sendMessage };
}

function omit<K extends string, V>(record: Record<K, V>, key: K): Record<K, V> {
  const rest = { ...record };
  delete rest[key];
  return rest;
}
