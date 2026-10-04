import { useCallback, useEffect, useRef, useState } from "react";

import {
  generateSessionTitle,
  getSessionDetail,
  getSessionRuns,
  type TitleGenerationRequest,
} from "../../api/client";
import {
  CUSTOM_PROFILE,
  buildModelOverride,
  buildSessionModelConfig,
  persistSessionModelConfig,
  restoreSessionModelConfig,
  useModelOptionsStore,
  type ModelOverrideDecision,
} from "../../stores/model-options-store";
import { useSessionListStore } from "../../stores/session-list-store";
import { useTraceStream } from "../trace/useTraceStream";
import { streamRun } from "./agui-stream";
import type { ChatMessage, RunSummary } from "./chat-types";
import type { EffortTier } from "./EffortSwitcher";
import { historyToMessages } from "./history";

type RunPhase = "idle" | "streaming";
type RunIdBySeq = Record<number, string>;
type ConfigChoice = "system" | "custom" | "current";

interface PendingConfigConfirmation {
  text: string;
  effort: EffortTier;
}

export function useAgentRun(sessionId: string) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [sessionExists, setSessionExists] = useState<boolean | null>(null);
  const [phase, setPhase] = useState<RunPhase>("idle");
  const [streamingId, setStreamingId] = useState<string | null>(null);
  const [summaries, setSummaries] = useState<Record<string, RunSummary>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [activeTool, setActiveTool] = useState<string | null>(null);
  const [runIdBySeq, setRunIdBySeq] = useState<RunIdBySeq>({});
  const [effort, setEffort] = useState<EffortTier>("medium");
  const [pendingConfigConfirmation, setPendingConfigConfirmation] = useState<PendingConfigConfirmation | null>(null);
  const [configChoiceResolved, setConfigChoiceResolved] = useState(false);
  const [persistenceWarning, setPersistenceWarning] = useState<string | null>(null);
  const [interruptedIds, setInterruptedIds] = useState<Record<string, true>>({});
  const hasSessionConfigRef = useRef(false);
  const { trees: traces, startTrace, handleTraceEvent } = useTraceStream();
  const abortRef = useRef<AbortController | null>(null);
  const stoppedRef = useRef(false);
  const titleAbortRef = useRef<AbortController | null>(null);
  const titleEligibleRef = useRef(false);
  const titleAttemptedRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    abortRef.current?.abort();
    titleAbortRef.current?.abort();
    titleAbortRef.current = null;
    titleEligibleRef.current = false;
    titleAttemptedRef.current = false;
    setHistoryLoaded(false);
    setSessionExists(null);
    setPhase("idle");
    setStreamingId(null);
    setRunIdBySeq({});
    setPendingConfigConfirmation(null);
    setConfigChoiceResolved(false);
    setPersistenceWarning(null);
    hasSessionConfigRef.current = false;
    setEffort("medium");
    void getSessionDetail(sessionId).then((detail) => {
      if (cancelled) return;
      const exists = detail !== null;
      setSessionExists(exists);
      // 只有新会话才有「首次自动生成标题」资格；已有会话（含仅刷新、重新进入）
      // 一律不补发，资格由服务端原子认领兜底（issue #93）。
      titleEligibleRef.current = !exists;
      const restored = restoreSessionModelConfig(sessionId, exists);
      hasSessionConfigRef.current = restored !== null;
      if (restored) setEffort(restored.effort);
      setMessages(detail ? historyToMessages(detail) : []);
      setHistoryLoaded(true);
    });
    void getSessionRuns(sessionId).then((runs) => {
      if (cancelled) return;
      const bySeq: RunIdBySeq = {};
      for (const run of runs) if (run.last_message_seq !== null) bySeq[run.last_message_seq] = run.id;
      setRunIdBySeq(bySeq);
    }, () => undefined);
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  useEffect(
    () => () => {
      abortRef.current?.abort();
      titleAbortRef.current?.abort();
    },
    [],
  );

  /**
   * 首次 `RUN_STARTED` 后尽早发起独立标题调用（issue #93）。快照来自发送时的
   * `executeSend` 闭包，不在异步触发时重读界面配置；主运行的停止/失败/收尾都不
   * 取消它。best-effort：失败、超时或取消都保留 fallback，不回落到主回答错误区。
   */
  const startTitleGeneration = useCallback(
    (targetSessionId: string, override: ModelOverrideDecision) => {
      if (!titleEligibleRef.current || titleAttemptedRef.current) return;
      titleAttemptedRef.current = true;
      const controller = new AbortController();
      titleAbortRef.current = controller;
      const request: TitleGenerationRequest =
        override.kind === "override" ? { model_override: override.override } : {};
      void generateSessionTitle(targetSessionId, request, controller.signal)
        .then((response) => {
          if (controller.signal.aborted) return;
          // 只应用服务端返回的「实际生效」标题；store 另有人工改名保护，迟到的
          // 结果不会覆盖本地改名，删除后也不会复活（issue #93）。
          if (response.title) {
            useSessionListStore.getState().applyTitle(response.session_id, response.title);
          }
        })
        .catch(() => {
          // 标题是 metadata best-effort：失败/取消/超时都保留 fallback，不提示。
        });
    },
    [],
  );

  const executeSend = useCallback(
    async (text: string, selectedEffort: EffortTier, forceSystemDefault = false) => {
      const trimmed = text.trim();
      const state = useModelOptionsStore.getState();
      const decision = forceSystemDefault ? { kind: "none" as const } : buildModelOverride(state);
      const assistantId = crypto.randomUUID();
      if (decision.kind === "incomplete") {
        setMessages((prev) => [
          ...prev,
          { id: crypto.randomUUID(), role: "user", text: trimmed, seq: null },
          { id: assistantId, role: "assistant", text: "", seq: null },
        ]);
        setErrors((prev) => ({ ...prev, [assistantId]: `自定义端点还差：${decision.missing}` }));
        return;
      }

      const config = buildSessionModelConfig(state, selectedEffort);
      if (decision.kind === "none") {
        config.profileChoice = null;
        config.mainModel = "";
        config.auxiliaryModel = "";
        config.auxiliaryFollowsMain = true;
        config.mainModelTouched = false;
      }
      hasSessionConfigRef.current = true;
      if (!persistSessionModelConfig(sessionId, config)) {
        setPersistenceWarning("浏览器未能保存本次配置；刷新后可能需要重新填写。运行仍会继续。");
      } else {
        setPersistenceWarning(null);
      }

      setMessages((prev) => [
        ...prev,
        { id: crypto.randomUUID(), role: "user", text: trimmed, seq: null },
        { id: assistantId, role: "assistant", text: "", seq: null },
      ]);
      setActiveTool(null);
      setErrors((prev) => omit(prev, assistantId));
      setPhase("streaming");
      setStreamingId(assistantId);
      startTrace(assistantId);
      useSessionListStore.getState().touchDraft(sessionId);

      const controller = new AbortController();
      abortRef.current = controller;
      stoppedRef.current = false;
      let steps = 0;
      let tokens = 0;
      let usageIncomplete = false;
      let finished = false;
      let failed = false;
      const startedAt = performance.now();
      try {
        await streamRun(
          {
            session_id: sessionId,
            message: trimmed,
            effort: selectedEffort,
            ...(decision.kind === "override" ? { model_override: decision.override } : {}),
          },
          {
            onTextDelta(delta) {
              setMessages((prev) => prev.map((message) => message.id === assistantId ? { ...message, text: message.text + delta } : message));
            },
            onStepStarted() { steps += 1; },
            onToolStarted(_toolCallId, name) { setActiveTool(name); },
            onToolEnded() { setActiveTool(null); },
            onUsage(payload) {
              if (payload.usage_status !== "complete") { usageIncomplete = true; return; }
              // 主运行摘要只统计主处理的输入+输出；`reasoning_tokens` 是
              // `output_tokens` 的子集，重复累加会把它算两次（issue #93）。
              tokens += (payload.input_tokens ?? 0) + (payload.output_tokens ?? 0);
            },
            onRunStarted() { startTitleGeneration(sessionId, decision); },
            onRunFinished() { finished = true; },
            onRunError(message) { failed = true; setErrors((prev) => ({ ...prev, [assistantId]: message })); },
            onTraceEvent(envelope) { handleTraceEvent(assistantId, envelope); },
          },
          controller.signal,
        );
      } catch (error) {
        if (controller.signal.aborted) {
          if (!stoppedRef.current) return;
        } else {
          failed = true;
          setErrors((prev) => ({ ...prev, [assistantId]: error instanceof Error ? error.message : "连接中断，请重试" }));
        }
      }
      if (controller.signal.aborted && !stoppedRef.current) return;
      setActiveTool(null);
      setPhase("idle");
      setStreamingId(null);
      void useSessionListStore.getState().refreshSession(sessionId);
      const disconnected = !finished && !failed;
      setSummaries((prev) => ({ ...prev, [assistantId]: {
        steps,
        durationMs: performance.now() - startedAt,
        usageStatus: disconnected ? "disconnected" : usageIncomplete ? "incomplete" : "complete",
        tokens: disconnected || usageIncomplete ? null : tokens,
      } }));
    },
    [handleTraceEvent, sessionId, startTitleGeneration, startTrace],
  );

  const sendMessage = useCallback(async (text: string, selectedEffort: EffortTier = effort): Promise<boolean> => {
    const trimmed = text.trim();
    if (!trimmed || phase === "streaming") return false;
    if (sessionExists === null) return false;
    if (sessionExists && !configChoiceResolved && !hasSessionConfigRef.current) {
      setPendingConfigConfirmation({ text: trimmed, effort: selectedEffort });
      return false;
    }
    const accepted = buildModelOverride(useModelOptionsStore.getState()).kind !== "incomplete";
    void executeSend(trimmed, selectedEffort);
    if (accepted) setConfigChoiceResolved(true);
    return accepted;
  }, [configChoiceResolved, effort, executeSend, phase, sessionExists]);

  const stopStreaming = useCallback(() => {
    if (phase !== "streaming" || !streamingId) return;
    stoppedRef.current = true;
    setInterruptedIds((prev) => ({ ...prev, [streamingId]: true }));
    abortRef.current?.abort();
  }, [phase, streamingId]);

  const retryTurn = useCallback((messageId: string) => {
    if (phase === "streaming") return;
    const idx = messages.findIndex((message) => message.id === messageId);
    if (idx === -1) return;
    const target = messages[idx];
    const userMessage = target.role === "user" ? target : messages[idx - 1];
    const assistantMessage = target.role === "assistant" ? target : messages[idx + 1];
    if (!userMessage || userMessage.role !== "user") return;
    const text = userMessage.text;
    setMessages((prev) => prev.filter((message) => message.id !== userMessage.id && message.id !== assistantMessage?.id));
    if (assistantMessage) {
      setErrors((prev) => omit(prev, assistantMessage.id));
      setSummaries((prev) => omit(prev, assistantMessage.id));
      setInterruptedIds((prev) => omit(prev, assistantMessage.id));
    }
    void executeSend(text, effort);
  }, [effort, executeSend, messages, phase]);

  const editMessage = useCallback((userId: string, newText: string) => {
    if (phase === "streaming") return;
    const trimmed = newText.trim();
    if (!trimmed) return;
    const idx = messages.findIndex((message) => message.id === userId);
    if (idx === -1 || messages[idx].role !== "user") return;
    const assistantMessage = messages[idx + 1]?.role === "assistant" ? messages[idx + 1] : undefined;
    setMessages((prev) => prev.filter((message) => message.id !== userId && message.id !== assistantMessage?.id));
    if (assistantMessage) {
      setErrors((prev) => omit(prev, assistantMessage.id));
      setSummaries((prev) => omit(prev, assistantMessage.id));
      setInterruptedIds((prev) => omit(prev, assistantMessage.id));
    }
    void executeSend(trimmed, effort);
  }, [effort, executeSend, messages, phase]);

  const confirmConfigChoice = useCallback(async (choice: ConfigChoice) => {
    const pending = pendingConfigConfirmation;
    if (!pending) return;
    setPendingConfigConfirmation(null);
    setConfigChoiceResolved(true);
    if (choice === "system") {
      useModelOptionsStore.getState().setSystemDefault();
      await executeSend(pending.text, pending.effort, true);
    } else if (choice === "current") {
      await executeSend(pending.text, pending.effort);
    } else {
      useModelOptionsStore.getState().setProfileChoice(CUSTOM_PROFILE);
    }
  }, [executeSend, pendingConfigConfirmation]);

  return {
    messages, historyLoaded, sessionExists, phase, streamingId, summaries, errors, activeTool,
    traces, runIdBySeq, effort, setEffort, sendMessage, pendingConfigConfirmation,
    confirmConfigChoice, persistenceWarning, retryTurn, editMessage, stopStreaming, interruptedIds,
  };
}

function omit<K extends string, V>(record: Record<K, V>, key: K): Record<K, V> {
  const rest = { ...record };
  delete rest[key];
  return rest;
}
