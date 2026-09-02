import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

import { useSessionListStore } from "../../stores/session-list-store";
import { uuidv7 } from "../../utils/uuid";
import { SessionListItem } from "./SessionListItem";

interface SessionSidebarProps {
  activeSessionId: string | null;
}

/**
 * 共享会话列表侧边栏（issue #68）——默认展开，显示所有会话。
 *
 * 不做鉴权、不做站长下架、不置顶、不 fork：任何访客可删可改名可续聊。
 */
export function SessionSidebar({ activeSessionId }: SessionSidebarProps) {
  const sessions = useSessionListStore((state) => state.sessions);
  const loaded = useSessionListStore((state) => state.loaded);
  const hasMore = useSessionListStore((state) => state.hasMore);
  const loadingMore = useSessionListStore((state) => state.loadingMore);
  const error = useSessionListStore((state) => state.error);
  const loadInitial = useSessionListStore((state) => state.loadInitial);
  const loadMore = useSessionListStore((state) => state.loadMore);
  const navigate = useNavigate();

  useEffect(() => {
    void loadInitial();
  }, [loadInitial]);

  /*
    开新会话只是换一个路由标识——不调后端、不往列表里插行。会话随第一条
    用户消息诞生（ADR-0013），空会话在后端根本不存在；这里提前建行会造出
    一条永远不会有消息的幽灵。侧边栏的那一行由 `touchDraft` 在发送时补上。
  */
  const startNewSession = () => {
    navigate(`/s/${uuidv7()}`);
  };

  return (
    <nav className="session-sidebar" aria-label="会话列表">
      <div className="session-sidebar-head">
        <p className="eyebrow">SESSIONS</p>
        <button
          type="button"
          className="session-sidebar-new"
          onClick={startNewSession}
          aria-label="开始新会话"
        >
          + 新会话
        </button>
      </div>
      {error && (
        <p className="session-sidebar-error" role="alert">
          {error}
        </p>
      )}
      {loaded && sessions.length === 0 ? (
        <p className="session-sidebar-empty">还没有会话</p>
      ) : (
        <ol className="session-sidebar-list">
          {sessions.map((session) => (
            <SessionListItem key={session.id} session={session} active={session.id === activeSessionId} />
          ))}
        </ol>
      )}
      {hasMore && (
        <button
          className="text-button"
          type="button"
          onClick={() => void loadMore()}
          disabled={loadingMore}
          data-busy={loadingMore}
        >
          {loadingMore ? "加载中…" : "加载更多"}
        </button>
      )}
    </nav>
  );
}
