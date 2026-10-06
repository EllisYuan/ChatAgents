import { type FormEvent, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { TracePanel } from "../trace/TracePanel";
import { useUiStore } from "../../stores/ui-store";
import { QuickModelPicker } from "./QuickModelPicker";
import { EffortSwitcher } from "./EffortSwitcher";
import { CheckIcon, CloseIcon, CopyIcon, EditIcon, RetryIcon, StopIcon } from "./icons";
import { MessageMarkdown } from "./MessageMarkdown";
import { ThinkingDots } from "./ThinkingDots";
import { useAgentRun } from "./useAgentRun";

export function SessionPage() {
  const { sessionId = "" } = useParams<{ sessionId: string }>();
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
  const openSettings = useUiStore((state) => state.openSettings);
  const setModelSettingsDisabled = useUiStore((state) => state.setModelSettingsDisabled);
  useEffect(() => {
    setModelSettingsDisabled(phase === "streaming");
    return () => setModelSettingsDisabled(false);
  }, [phase, setModelSettingsDisabled]);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [sentHistory, setSentHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState<number | null>(null);
  const [draftBeforeHistory, setDraftBeforeHistory] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState("");
  const messageScrollRef = useRef<HTMLDivElement>(null);
  const followBottomRef = useRef(true);
  const previousStreamingIdRef = useRef<string | null>(null);

  useLayoutEffect(() => {
    followBottomRef.current = true;
  }, [sessionId]);

  useLayoutEffect(() => {
    if (streamingId && streamingId !== previousStreamingIdRef.current) followBottomRef.current = true;
    previousStreamingIdRef.current = streamingId;
    const scroll = messageScrollRef.current;
    if (scroll && followBottomRef.current) scroll.scrollTop = scroll.scrollHeight;
  });

  const handleMessageScroll = () => {
    const scroll = messageScrollRef.current;
    if (scroll) followBottomRef.current = scroll.scrollHeight - scroll.clientHeight - scroll.scrollTop <= 48;
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!draft.trim() || phase === "streaming") {
      return;
    }
    const text = draft;
    void sendMessage(text, effort).then((accepted) => {
      if (accepted) {
        setDraft("");
        setHistoryIndex(null);
        setSentHistory((prev) => (prev[prev.length - 1] === text.trim() ? prev : [...prev, text.trim()]));
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
    <section className="session-page" aria-label="会话">
      <div className="session-grid">
        <article className="conversation-card" aria-label="对话">
          <div className="message-scroll" ref={messageScrollRef} onScroll={handleMessageScroll} tabIndex={0} role="region" aria-label="聊天内容">
          {isEmpty ? (
            <div className="empty-conversation">
              <div>
                <h2>有什么可以帮你？</h2>
                <p>发送消息，开始会话。</p>
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
                  <span className="chat-turn-role">{message.role === "user" ? "你" : "助手"}</span>
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
                    <p className="chat-tool-note">正在使用工具 {activeTool}</p>
                  )}
                  {message.role === "assistant" && errors[message.id] && (
                    <p className="chat-error" role="alert">
                      运行出错：{errors[message.id]}
                    </p>
                  )}
                  {message.role === "assistant" && message.id !== streamingId && interruptedIds[message.id] && (
                    <p className="chat-tool-note">已停止生成</p>
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

          </div>
          <div className="composer-dock">
          <div className="composer-toolbar">
            <EffortSwitcher value={effort} onChange={setEffort} disabled={phase === "streaming"} />
            <QuickModelPicker disabled={phase === "streaming" || !historyLoaded} />
          </div>
          <div className="composer-settings">
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
                  className="settings-done"
                  onClick={() => {
                    setDraft("");
                    void confirmConfigChoice("current");
                  }}
                >
                  使用当前配置发送
                </button>
                <button
                  type="button"
                  className="text-button"
                  onClick={() => {
                    openSettings();
                    void confirmConfigChoice("custom");
                  }}
                >
                  填写并使用自定义配置
                </button>
              </div>
            </div>
          )}

          </div>
          <form className="composer" onSubmit={handleSubmit} aria-label="发送消息">
            <textarea
              className="composer-input"
              value={draft}
              onChange={(event) => {
                setDraft(event.target.value);
                setHistoryIndex(null);
              }}
              onKeyDown={(event) => {
                if (event.nativeEvent.isComposing || event.keyCode === 229) return;
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  handleSubmit(event as unknown as FormEvent<HTMLFormElement>);
                  return;
                }
                const el = event.currentTarget;
                if (event.key === "ArrowUp" && el.selectionStart === 0 && el.selectionEnd === 0) {
                  if (sentHistory.length === 0) return;
                  event.preventDefault();
                  setHistoryIndex((current) => {
                    const nextIndex = current === null ? sentHistory.length - 1 : Math.max(0, current - 1);
                    if (current === null) setDraftBeforeHistory(draft);
                    setDraft(sentHistory[nextIndex]);
                    return nextIndex;
                  });
                  return;
                }
                if (
                  event.key === "ArrowDown" &&
                  historyIndex !== null &&
                  el.selectionStart === el.value.length &&
                  el.selectionEnd === el.value.length
                ) {
                  event.preventDefault();
                  setHistoryIndex((current) => {
                    if (current === null) return null;
                    const nextIndex = current + 1;
                    if (nextIndex >= sentHistory.length) {
                      setDraft(draftBeforeHistory);
                      return null;
                    }
                    setDraft(sentHistory[nextIndex]);
                    return nextIndex;
                  });
                }
              }}
              placeholder="发送消息…"
              aria-label="消息内容"
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
                  ↵
                </span>
              </button>
            )}
          </form>
          </div>
        </article>
      </div>
    </section>
  );
}
