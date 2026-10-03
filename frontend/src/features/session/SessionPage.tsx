import { type FormEvent, useState } from "react";
import { useParams } from "react-router-dom";

import { TracePanel } from "../trace/TracePanel";
import { useUiStore } from "../../stores/ui-store";
import { AdvancedOptions } from "./AdvancedOptions";
import { EffortSwitcher } from "./EffortSwitcher";
import { CheckIcon, CloseIcon, CopyIcon, EditIcon, RetryIcon, StopIcon } from "./icons";
import { MessageMarkdown } from "./MessageMarkdown";
import { ThinkingDots } from "./ThinkingDots";
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
    retryTurn,
    editMessage,
    stopStreaming,
    interruptedIds,
  } = useAgentRun(sessionId);
  const [draft, setDraft] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState("");

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!draft.trim() || phase === "streaming") {
      return;
    }
    void sendMessage(draft, effort).then((accepted) => {
      if (accepted) {
        setDraft("");
        setAdvancedOpen(false);
      }
    });
  };

  const handleCopy = (id: string, text: string) => {
    void navigator.clipboard.writeText(text).then(() => {
      setCopiedId(id);
      setTimeout(() => setCopiedId((current) => (current === id ? null : current)), 1500);
    });
  };

  const startEdit = (id: string, text: string) => {
    setEditingId(id);
    setEditDraft(text);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditDraft("");
  };

  const submitEdit = (id: string) => {
    if (!editDraft.trim()) return;
    editMessage(id, editDraft);
    setEditingId(null);
    setEditDraft("");
  };

  const lastIndex = messages.length - 1;
  const lastTurnUserIndex = messages[lastIndex]?.role === "assistant" ? lastIndex - 1 : lastIndex;

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
              {messages.map((message, index) => {
                const isLastAssistant = message.role === "assistant" && index === messages.length - 1;
                const isLastUser = message.role === "user" && index === lastTurnUserIndex;
                const isSettledAssistant = isLastAssistant && message.id !== streamingId && phase !== "streaming";
                const isEditableUser = isLastUser && phase !== "streaming";
                const isEditing = editingId === message.id;
                return (
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
                      <p className="chat-turn-text">{message.id === streamingId ? <ThinkingDots /> : ""}</p>
                    )
                  ) : isEditing ? (
                    <div className="chat-edit">
                      <textarea
                        className="chat-edit-input"
                        value={editDraft}
                        onChange={(event) => setEditDraft(event.target.value)}
                        rows={3}
                        autoFocus
                      />
                      <div className="chat-edit-actions">
                        <button type="button" className="icon-button" title="取消" aria-label="取消" onClick={cancelEdit}>
                          <CloseIcon size={13} />
                        </button>
                        <button
                          type="button"
                          className="icon-button icon-button--confirm"
                          title="保存并重新发送"
                          aria-label="保存并重新发送"
                          onClick={() => submitEdit(message.id)}
                        >
                          <CheckIcon size={13} />
                        </button>
                      </div>
                    </div>
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
                  {message.role === "assistant" && message.id !== streamingId && interruptedIds[message.id] && (
                    <p className="chat-tool-note">▸ 已停止生成</p>
                  )}
                  {isSettledAssistant && message.text && (
                    <div className="chat-turn-actions">
                      <button
                        type="button"
                        className={`icon-button${copiedId === message.id ? " icon-button--confirm" : ""}`}
                        title={copiedId === message.id ? "已复制" : "复制"}
                        aria-label={copiedId === message.id ? "已复制" : "复制"}
                        onClick={() => handleCopy(message.id, message.text)}
                      >
                        {copiedId === message.id ? <CheckIcon size={13} /> : <CopyIcon size={13} />}
                      </button>
                      <button
                        type="button"
                        className="icon-button"
                        title="重试"
                        aria-label="重试"
                        onClick={() => retryTurn(message.id)}
                      >
                        <RetryIcon size={13} />
                      </button>
                    </div>
                  )}
                  {isEditableUser && !isEditing && (
                    <div className="chat-turn-actions chat-turn-actions--hover-only">
                      <button
                        type="button"
                        className={`icon-button${copiedId === message.id ? " icon-button--confirm" : ""}`}
                        title={copiedId === message.id ? "已复制" : "复制"}
                        aria-label={copiedId === message.id ? "已复制" : "复制"}
                        onClick={() => handleCopy(message.id, message.text)}
                      >
                        {copiedId === message.id ? <CheckIcon size={13} /> : <CopyIcon size={13} />}
                      </button>
                      <button
                        type="button"
                        className="icon-button"
                        title="编辑"
                        aria-label="编辑"
                        onClick={() => startEdit(message.id, message.text)}
                      >
                        <EditIcon size={13} />
                      </button>
                      <button
                        type="button"
                        className="icon-button"
                        title="重试"
                        aria-label="重试"
                        onClick={() => retryTurn(message.id)}
                      >
                        <RetryIcon size={13} />
                      </button>
                    </div>
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
                );
              })}
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
            {phase === "streaming" ? (
              <button
                className="composer-submit composer-submit--stop"
                type="button"
                title="停止生成"
                aria-label="停止生成"
                onClick={stopStreaming}
              >
                <StopIcon size={13} />
                停止
              </button>
            ) : (
              <button className="composer-submit" type="submit" disabled={!draft.trim()}>
                发送
                <span className="composer-key" aria-hidden="true">
                  ⌘ ↵
                </span>
              </button>
            )}
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
