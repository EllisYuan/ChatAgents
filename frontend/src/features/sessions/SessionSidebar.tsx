import { useEffect } from "react";

import { useSessionListStore } from "../../stores/session-list-store";
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

  useEffect(() => {
    void loadInitial();
  }, [loadInitial]);

  return (
    <nav className="session-sidebar" aria-label="会话列表">
      <p className="eyebrow">SESSIONS</p>
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
        >
          {loadingMore ? "加载中…" : "加载更多"}
        </button>
      )}
    </nav>
  );
}
