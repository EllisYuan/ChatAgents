import { useState } from "react";

import { SummaryLine } from "../session/SummaryLine";
import type { RunSummary } from "../session/chat-types";
import { ReasoningLine } from "./ReasoningLine";
import { RunConfigTable } from "./RunConfigTable";
import { SpanTimeline } from "./SpanTimeline";
import type { TraceTree } from "./types";
import { useRunDetail } from "./useRunDetail";

interface TracePanelProps {
  pending: boolean;
  summary?: RunSummary;
  /** 本次会话里直播拼出的树；只有这条消息在当前会话中被直播过才非空。 */
  liveTree: TraceTree | null;
  /** 历史消息按 `seq` 匹配出的运行 id；直播树存在时不需要它。 */
  runId: string | null;
}

/**
 * 挂在每条 assistant 消息下方的运行详情手风琴（ADR-0028：聊天界面是唯一的
 * 控制台，运行详情就地长在回答下方，不开抽屉不设侧栏）。
 *
 * Layer 0（摘要行 + 推理收起行）永远可见；点摘要行展开 Layer 1（跨度时间
 * 轴 + 运行配置表）。数据来源两条路径：当前会话直播过的消息用 `liveTree`
 * （已经在客户端拼好），历史消息按 `runId` 懒加载 `GET /api/runs/{run_id}`。
 */
export function TracePanel({ pending, summary, liveTree, runId }: TracePanelProps) {
  const [expanded, setExpanded] = useState(false);
  const historical = useRunDetail(liveTree === null ? runId : null);
  const tree = liveTree ?? historical.tree;

  const hasLiveData = liveTree !== null && (liveTree.iterations.length > 0 || liveTree.auxiliary !== null);
  const canExpand = hasLiveData || runId !== null;

  const handleToggle = () => {
    if (!canExpand) {
      return;
    }
    if (!expanded && liveTree === null) {
      historical.load();
    }
    setExpanded((prev) => !prev);
  };

  const lastReasoning =
    tree !== null && tree.iterations.length > 0
      ? tree.iterations[tree.iterations.length - 1].modelSpan.reasoning
      : null;

  return (
    <div className="trace-panel">
      {canExpand ? (
        <button className="run-summary-trigger" type="button" onClick={handleToggle} aria-expanded={expanded}>
          <SummaryLine pending={pending} summary={summary} />
        </button>
      ) : (
        <SummaryLine pending={pending} summary={summary} />
      )}
      <ReasoningLine reasoning={lastReasoning} />
      {expanded && (
        <div className="trace-detail">
          {historical.status === "loading" && <p className="trace-loading">加载运行详情…</p>}
          {historical.status === "error" && (
            <p className="trace-error" role="alert">
              {historical.error}
            </p>
          )}
          {tree !== null && <SpanTimeline tree={tree} />}
          {tree?.runConfig && <RunConfigTable runConfig={tree.runConfig} />}
        </div>
      )}
    </div>
  );
}
