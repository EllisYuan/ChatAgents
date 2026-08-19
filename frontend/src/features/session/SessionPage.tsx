import { type FormEvent, useState } from "react";
import { useParams } from "react-router-dom";

import { TraceSkeleton } from "../trace/TraceSkeleton";
import { useUiStore } from "../../stores/ui-store";
import { SummaryLine } from "./SummaryLine";
import { useAgentRun } from "./useAgentRun";

export function SessionPage() {
  const { sessionId = "" } = useParams<{ sessionId: string }>();
  const inspectorOpen = useUiStore((state) => state.inspectorOpen);
  const toggleInspector = useUiStore((state) => state.toggleInspector);
  const { messages, historyLoaded, phase, streamingId, summaries, errors, activeTool, sendMessage } =
    useAgentRun(sessionId);
  const [draft, setDraft] = useState("");

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!draft.trim() || phase === "streaming") {
      return;
    }
    void sendMessage(draft);
    setDraft("");
  };

  const isEmpty = historyLoaded && messages.length === 0;

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
            <span className="signal-chip">{phase === "streaming" ? "RUN LIVE" : "SESSION READY"}</span>
            <span className="mono">{sessionId}</span>
          </div>

          {isEmpty ? (
            <div className="empty-conversation">
              <span className="empty-index">00</span>
              <div>
                <h2>从一个问题开始</h2>
                <p>消息、工具与模型轨迹会在这里汇合。</p>
              </div>
            </div>
          ) : (
            <ol className="chat-thread">
              {messages.map((message) => (
                <li key={message.id} className={`chat-turn chat-turn--${message.role}`}>
                  <span className="chat-turn-role">{message.role === "user" ? "YOU" : "AGENT"}</span>
                  <p className="chat-turn-text">
                    {message.text || (message.id === streamingId ? "…" : "")}
                  </p>
                  {message.role === "assistant" && message.id === streamingId && activeTool && (
                    <p className="chat-tool-note">▸ 使用工具 {activeTool}</p>
                  )}
                  {message.role === "assistant" && errors[message.id] && (
                    <p className="chat-error" role="alert">
                      运行出错：{errors[message.id]}
                    </p>
                  )}
                  {message.role === "assistant" && (
                    <SummaryLine
                      pending={message.id === streamingId}
                      summary={summaries[message.id]}
                    />
                  )}
                </li>
              ))}
            </ol>
          )}

          <form className="composer" onSubmit={handleSubmit} aria-label="发送消息">
            <textarea
              className="composer-input"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  handleSubmit(event as unknown as FormEvent<HTMLFormElement>);
                }
              }}
              placeholder="Ask the agent something precise…"
              maxLength={32_000}
              rows={2}
              disabled={phase === "streaming"}
            />
            <button
              className="composer-submit"
              type="submit"
              disabled={phase === "streaming" || !draft.trim()}
            >
              {phase === "streaming" ? "运行中…" : "发送"}
              <span className="composer-key" aria-hidden="true">
                ⌘ ↵
              </span>
            </button>
          </form>
          <TraceSkeleton />
        </article>

        {inspectorOpen && (
          <aside className="inspector-card" aria-label="运行 inspector">
            <div className="card-meta">
              <span className="eyebrow">INSPECTOR</span>
              <span className="live-label">{phase === "streaming" ? "● LIVE" : "● IDLE"}</span>
            </div>
            <div className="inspector-body">
              <div className="metric-row">
                <span>MESSAGES</span>
                <strong>{messages.length}</strong>
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
          </aside>
        )}
      </div>
    </section>
  );
}
