import { useCallback, useState } from "react";

import { getRunDetail } from "../../api/client";
import { traceTreeFromRunDetail } from "./from-run-detail";
import type { TraceTree } from "./types";

interface RunDetailState {
  status: "idle" | "loading" | "loaded" | "error";
  tree: TraceTree | null;
  error: string | null;
}

/**
 * 历史消息的运行详情懒加载（issue #69）——点开摘要行才 fetch，会话一长
 * 也不会把所有历史运行的详情都拉下来。
 */
export function useRunDetail(runId: string | null) {
  const [state, setState] = useState<RunDetailState>({ status: "idle", tree: null, error: null });

  const load = useCallback(() => {
    if (runId === null || state.status === "loading" || state.status === "loaded") {
      return;
    }
    setState({ status: "loading", tree: null, error: null });
    void getRunDetail(runId)
      .then((detail) => {
        setState({ status: "loaded", tree: traceTreeFromRunDetail(detail), error: null });
      })
      .catch((error: unknown) => {
        setState({
          status: "error",
          tree: null,
          error: error instanceof Error ? error.message : "加载运行详情失败",
        });
      });
  }, [runId, state.status]);

  return { ...state, load };
}
