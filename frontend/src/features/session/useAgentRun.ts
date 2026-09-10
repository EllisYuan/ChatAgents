import { useCallback, useEffect, useRef, useState } from "react";

import { getSessionDetail, getSessionRuns } from "../../api/client";
import {
  CUSTOM_PROFILE,
  buildModelOverride,
  buildSessionModelConfig,
  persistSessionModelConfig,
  restoreSessionModelConfig,
  useModelOptionsStore,
} from "../../stores/model-options-store";
import { useSessionListStore } from "../../stores/session-list-store";
import { useTraceStream } from "../trace/useTraceStream";
import { streamRun } from "./agui-stream";
import type { ChatMessage, RunSummary } from "./chat-types";
import type { EffortTier } from "./EffortSwitcher";
import { historyToMessages } from "./history";

type RunPhase = "idle" | "streaming";
type RunIdBySeq = Record<number, string>;
type ConfigChoice = "system" | "custom";

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
  const hasSessionConfigRef = useRef(false);
  const { trees: traces, startTrace, handleTraceEvent } = useTraceStream();
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let cancelled = false;
    abortRef.current?.abort();
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

  useEffect(() => () => abortRef.current?.abort(), []);

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
              tokens += (payload.input_tokens ?? 0) + (payload.output_tokens ?? 0) + (payload.reasoning_tokens ?? 0);
            },
            onTitleGenerated(titleSessionId, title) { useSessionListStore.getState().applyTitle(titleSessionId, title); },
            onRunFinished() { finished = true; },
            onRunError(message) { failed = true; setErrors((prev) => ({ ...prev, [assistantId]: message })); },
            onTraceEvent(envelope) { handleTraceEvent(assistantId, envelope); },
          },
          controller.signal,
        );
      } catch (error) {
        if (controller.signal.aborted) return;
        failed = true;
        setErrors((prev) => ({ ...prev, [assistantId]: error instanceof Error ? error.message : "连接中断，请重试" }));
      }
      if (controller.signal.aborted) return;
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
    [handleTraceEvent, sessionId, startTrace],
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

  const confirmConfigChoice = useCallback(async (choice: ConfigChoice) => {
    const pending = pendingConfigConfirmation;
    if (!pending) return;
    setPendingConfigConfirmation(null);
    setConfigChoiceResolved(true);
    if (choice === "system") {
      useModelOptionsStore.getState().setSystemDefault();
      await executeSend(pending.text, pending.effort, true);
    } else {
      useModelOptionsStore.getState().setProfileChoice(CUSTOM_PROFILE);
    }
  }, [executeSend, pendingConfigConfirmation]);

  return {
    messages, historyLoaded, sessionExists, phase, streamingId, summaries, errors, activeTool,
    traces, runIdBySeq, effort, setEffort, sendMessage, pendingConfigConfirmation,
    confirmConfigChoice, persistenceWarning,
  };
}

function omit<K extends string, V>(record: Record<K, V>, key: K): Record<K, V> {
  const rest = { ...record };
  delete rest[key];
  return rest;
}
