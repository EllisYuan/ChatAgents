import { useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";

import type { SessionSummary } from "../../api/client";
import { useSessionListStore } from "../../stores/session-list-store";

function formatAbsoluteTime(iso: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(iso));
}

interface SessionListItemProps {
  session: SessionSummary;
  active: boolean;
}

/**
 * 会话列表的一行——标题 / 绝对时刻 / 消息数三个字段，没有任何观测派生量（ADR-0013）。
 *
 * 标题为空时显示「新会话」+ 骨架微光；`title` 变化时用 `key` 切换触发一次
 * CSS 淡入，不做打字机效果（issue #68）。鉴权整块不做——任何访客都能改名、删除。
 */
export function SessionListItem({ session, active }: SessionListItemProps) {
  const [renaming, setRenaming] = useState(false);
  const [draft, setDraft] = useState(session.title ?? "");
  const rename = useSessionListStore((state) => state.rename);
  const remove = useSessionListStore((state) => state.remove);
  const navigate = useNavigate();

  const startRename = () => {
    setDraft(session.title ?? "");
    setRenaming(true);
  };

  const commitRename = () => {
    setRenaming(false);
    const next = draft.trim();
    if (next === (session.title ?? "")) {
      return;
    }
    void rename(session.id, next || null);
  };

  const handleDelete = () => {
    void remove(session.id).then((ok) => {
      if (ok && active) {
        navigate("/");
      }
    });
  };

  return (
    <li className={`session-item${active ? " session-item--active" : ""}`}>
      {renaming ? (
        <input
          className="session-item-rename"
          autoFocus
          value={draft}
          maxLength={200}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={commitRename}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              commitRename();
            }
            if (event.key === "Escape") {
              setRenaming(false);
            }
          }}
        />
      ) : (
        <NavLink className="session-item-link" to={`/s/${session.id}`}>
          {session.title === null ? (
            <span className="session-item-title session-item-title--skeleton">新会话</span>
          ) : (
            <span key={session.title} className="session-item-title session-item-title--enter">
              {session.title}
            </span>
          )}
          <span className="session-item-meta">
            <span>{formatAbsoluteTime(session.updated_at)}</span>
            <span>{session.message_count} 条</span>
          </span>
        </NavLink>
      )}
      <span className="session-item-actions">
        <button type="button" className="session-item-action" onClick={startRename} aria-label="重命名会话">
          改名
        </button>
        <button type="button" className="session-item-action" onClick={handleDelete} aria-label="删除会话">
          删除
        </button>
      </span>
    </li>
  );
}
