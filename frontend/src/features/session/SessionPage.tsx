import { type FormEvent, useState } from "react";
import { useParams } from "react-router-dom";

import { TracePanel } from "../trace/TracePanel";
import { useUiStore } from "../../stores/ui-store";
import { AdvancedOptions } from "./AdvancedOptions";
import { EffortSwitcher } from "./EffortSwitcher";
import { MessageMarkdown } from "./MessageMarkdown";
import { useAgentRun } from "./useAgentRun";

export function SessionPage() {
  const { sessionId = "" } = useParams<{ sessionId: string }>();
  const inspectorOpen = useUiStore((state) => state.inspectorOpen);
  const toggleInspector = useUiStore((state) => state.toggleInspector);
  const {
    messages,
    historyLoaded,
    phase,
    streamingId,
    summaries,
    errors,
    activeTool,
    traces,
    runIdBySeq,
    effort,
    setEffort,
    sendMessage,
    pendingConfigConfirmation,
    confirmConfigChoice,
    persistenceWarning,
  } = useAgentRun(sessionId);
  const [draft, setDraft] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!draft.trim() || phase === "streaming") {
      return;
    }
    void sendMessage(draft, effort).then((accepted) => {
      if (accepted) setDraft("");
    });
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
                  {/*
                    用户输入按原文保形（.chat-turn-text 的 pre-wrap），Agent 回答走
                    Markdown 渲染——正文里的标题、列表、代码块与链接都是模型按
                    Markdown 写出来的，直接当纯文本摆出来就是把 `##` 和 `**` 摊在脸上。
                  */}
                  {message.role === "assistant" ? (
                    message.text ? (
                      <MessageMarkdown text={message.text} />
                    ) : (
                      <p className="chat-turn-text">{message.id === streamingId ? "…" : ""}</p>
                    )
                  ) : (
                    <p className="chat-turn-text">{message.text}</p>
                  )}
                  {message.role === "assistant" && message.id === streamingId && activeTool && (
                    <p className="chat-tool-note">▸ 使用工具 {activeTool}</p>
                  )}
                  {message.role === "assistant" && errors[message.id] && (
                    <p className="chat-error" role="alert">
                      运行出错：{errors[message.id]}
                    </p>
                  )}
                  {message.role === "assistant" && (
                    <TracePanel
                      pending={message.id === streamingId}
                      summary={summaries[message.id]}
                      liveTree={traces[message.id] ?? null}
                      runId={message.seq !== null ? (runIdBySeq[message.seq] ?? null) : null}
                    />
                  )}
                </li>
              ))}
            </ol>
          )}

          <div className="composer-toolbar">
            <EffortSwitcher value={effort} onChange={setEffort} disabled={phase === "streaming"} />
            <button
              className="text-button"
              type="button"
              onClick={() => setAdvancedOpen((open) => !open)}
            >
              {advancedOpen ? "收起高级选项" : "高级选项"}
            </button>
          </div>
          {advancedOpen && <AdvancedOptions disabled={phase === "streaming"} />}
          {persistenceWarning && <p className="advanced-hint advanced-hint--error" role="alert">{persistenceWarning}</p>}
          {pendingConfigConfirmation && (
            <div className="config-confirmation" role="alertdialog" aria-label="确认模型配置">
              <p>这是已有会话，但浏览器没有保存过它的模型配置。请选择本次发送使用哪一套配置。</p>
              <div className="config-confirmation-actions">
                <button
                  type="button"
                  className="text-button"
                  onClick={() => {
                    setDraft("");
                    void confirmConfigChoice("system");
                  }}
                >
                  使用系统默认
                </button>
                <button
                  type="button"
                  className="primary-action"
                  onClick={() => {
                    setAdvancedOpen(true);
                    void confirmConfigChoice("custom");
                  }}
                >
                  填写并使用自定义配置
                </button>
              </div>
            </div>
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
              data-busy={phase === "streaming"}
            >
              {phase === "streaming" ? "运行中…" : "发送"}
              <span className="composer-key" aria-hidden="true">
                ⌘ ↵
              </span>
            </button>
          </form>
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
