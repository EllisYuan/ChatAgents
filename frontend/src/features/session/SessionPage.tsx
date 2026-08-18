import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { getModels } from "../../api/client";
import { TraceSkeleton } from "../trace/TraceSkeleton";
import { useUiStore } from "../../stores/ui-store";

export function SessionPage() {
  const { sessionId = "unknown" } = useParams<{ sessionId: string }>();
  const inspectorOpen = useUiStore((state) => state.inspectorOpen);
  const toggleInspector = useUiStore((state) => state.toggleInspector);
  const modelsQuery = useQuery({
    queryKey: ["models"],
    queryFn: getModels,
    enabled: false,
  });

  return (
    <section className="session-page" aria-labelledby="session-title">
      <div className="session-heading">
        <div>
          <p className="eyebrow">SESSION / LIVE SURFACE</p>
          <h1 id="session-title">A quiet place for a running thought.</h1>
        </div>
        <button className="text-button" type="button" onClick={toggleInspector}>
          {inspectorOpen ? "隐藏 inspector" : "显示 inspector"}
        </button>
      </div>

      <div className={`session-grid${inspectorOpen ? "" : " session-grid--focus"}`}>
        <article className="conversation-card">
          <div className="card-meta">
            <span className="signal-chip">SESSION READY</span>
            <span className="mono">{sessionId}</span>
          </div>
          <div className="empty-conversation">
            <span className="empty-index">00</span>
            <div>
              <h2>从一个问题开始</h2>
              <p>消息、工具与模型轨迹会在这里汇合。</p>
            </div>
          </div>
          <div className="composer-placeholder" aria-label="消息输入区占位">
            <span>Ask the agent something precise…</span>
            <span className="composer-key">⌘ ↵</span>
          </div>
          <TraceSkeleton />
        </article>

        {inspectorOpen && (
          <aside className="inspector-card" aria-label="运行 inspector">
            <div className="card-meta">
              <span className="eyebrow">INSPECTOR</span>
              <span className="live-label">● IDLE</span>
            </div>
            <div className="inspector-body">
              <div className="metric-row">
                <span>MODEL</span>
                <strong>等待选择</strong>
              </div>
              <div className="metric-row">
                <span>TRACE NODES</span>
                <strong>—</strong>
              </div>
              <div className="metric-row">
                <span>TOKEN BUDGET</span>
                <strong>—</strong>
              </div>
            </div>
            <button
              className="inspector-link"
              type="button"
              onClick={() => void modelsQuery.refetch()}
              disabled={modelsQuery.isFetching}
            >
              {modelsQuery.isFetching ? "同步中…" : "检查模型清单"}
              <span aria-hidden="true">↗</span>
            </button>
          </aside>
        )}
      </div>
    </section>
  );
}
