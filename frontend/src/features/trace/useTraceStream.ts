import { useCallback, useRef, useState } from "react";

import type { RunEnvelope } from "../session/agui-stream";
import { emptyMergeState, mergeTraceEvent, projectMergeState, type MergeState } from "./live-merge";
import { emptyTraceTree, type TraceTree } from "./types";

/**
 * 按 assistant 消息 id 维护直播 trace 状态（issue #69）——同 `useAgentRun`
 * 里摘要行按消息 id 分开存放的理由：同一会话连续问几轮，每一轮的跨度树
 * 各自留一份，不会被下一轮覆盖。
 *
 * 合并状态（`MergeState`，含计时用的中间字段）存在 ref 里，不进 React state
 * ——每个事件都会触发一次合并，没必要为中间态触发额外渲染；只有投影出的
 * `TraceTree` 进 state 驱动渲染。
 */
export function useTraceStream() {
  const [trees, setTrees] = useState<Record<string, TraceTree>>({});
  const mergeStates = useRef<Record<string, MergeState>>({});

  const startTrace = useCallback((messageId: string) => {
    mergeStates.current[messageId] = emptyMergeState();
    setTrees((prev) => ({ ...prev, [messageId]: emptyTraceTree() }));
  }, []);

  const handleTraceEvent = useCallback((messageId: string, envelope: RunEnvelope) => {
    const current = mergeStates.current[messageId] ?? emptyMergeState();
    const next = mergeTraceEvent(current, envelope, performance.now());
    mergeStates.current[messageId] = next;
    setTrees((prev) => ({ ...prev, [messageId]: projectMergeState(next) }));
  }, []);

  return { trees, startTrace, handleTraceEvent };
}
