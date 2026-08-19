import { create } from "zustand";

import {
  deleteSession,
  getSessionDetail,
  listSessions,
  renameSession,
  type SessionSummary,
} from "../api/client";

const PAGE_SIZE = 50;

type SessionListState = {
  sessions: SessionSummary[];
  loaded: boolean;
  loadingMore: boolean;
  hasMore: boolean;
  error: string | null;
  loadInitial: () => Promise<void>;
  loadMore: () => Promise<void>;
  touchDraft: (sessionId: string) => void;
  applyTitle: (sessionId: string, title: string) => void;
  refreshSession: (sessionId: string) => Promise<void>;
  /** 返回 false 表示删除失败——调用方（例如侧边栏的离开导航）不应继续。 */
  remove: (sessionId: string) => Promise<boolean>;
  rename: (sessionId: string, title: string | null) => Promise<void>;
};

function upsert(sessions: SessionSummary[], entry: SessionSummary): SessionSummary[] {
  const next = sessions.filter((session) => session.id !== entry.id);
  next.push(entry);
  next.sort((a, b) => (a.updated_at < b.updated_at ? 1 : a.updated_at > b.updated_at ? -1 : 0));
  return next;
}

/**
 * 共享会话列表侧边栏的状态（issue #68）。
 *
 * 列表项只存 `app` schema 内的三个字段——不做仪表盘、不放 token（ADR-0013）。
 * `touchDraft`/`applyTitle` 提供「新会话」骨架微光到标题淡入替换的过渡状态；
 * `refreshSession` 在一次运行收尾后向后端要回权威的标题与消息数，不做客户端估算。
 */
export const useSessionListStore = create<SessionListState>((set, get) => ({
  sessions: [],
  loaded: false,
  loadingMore: false,
  hasMore: true,
  error: null,

  loadInitial: async () => {
    if (get().loaded) {
      return;
    }
    try {
      const page = await listSessions({ limit: PAGE_SIZE });
      set({ sessions: page, loaded: true, hasMore: page.length === PAGE_SIZE, error: null });
    } catch (error) {
      set({ loaded: true, error: error instanceof Error ? error.message : "加载会话列表失败" });
    }
  },

  loadMore: async () => {
    const { sessions, loadingMore, hasMore } = get();
    if (loadingMore || !hasMore || sessions.length === 0) {
      return;
    }
    const last = sessions[sessions.length - 1];
    set({ loadingMore: true });
    try {
      const page = await listSessions({
        limit: PAGE_SIZE,
        beforeUpdatedAt: last.updated_at,
        beforeId: last.id,
      });
      set((state) => ({
        sessions: [...state.sessions, ...page],
        hasMore: page.length === PAGE_SIZE,
        loadingMore: false,
      }));
    } catch (error) {
      set({
        loadingMore: false,
        error: error instanceof Error ? error.message : "加载更多会话失败",
      });
    }
  },

  touchDraft: (sessionId) => {
    set((state) => {
      if (state.sessions.some((session) => session.id === sessionId)) {
        return state;
      }
      const now = new Date().toISOString();
      return {
        sessions: upsert(state.sessions, {
          id: sessionId,
          title: null,
          created_at: now,
          updated_at: now,
          message_count: 1,
        }),
      };
    });
  },

  applyTitle: (sessionId, title) => {
    set((state) => {
      const existing = state.sessions.find((session) => session.id === sessionId);
      if (!existing) {
        return state;
      }
      return { sessions: upsert(state.sessions, { ...existing, title }) };
    });
  },

  refreshSession: async (sessionId) => {
    const detail = await getSessionDetail(sessionId);
    if (!detail) {
      return;
    }
    set((state) => ({
      sessions: upsert(state.sessions, {
        id: detail.id,
        title: detail.title,
        created_at: detail.created_at,
        updated_at: detail.updated_at,
        message_count: detail.messages?.length ?? 0,
      }),
    }));
  },

  remove: async (sessionId) => {
    try {
      await deleteSession(sessionId);
      set((state) => ({
        sessions: state.sessions.filter((session) => session.id !== sessionId),
        error: null,
      }));
      return true;
    } catch (error) {
      set({ error: error instanceof Error ? error.message : "删除会话失败" });
      return false;
    }
  },

  rename: async (sessionId, title) => {
    try {
      const view = await renameSession(sessionId, title);
      set((state) => {
        const existing = state.sessions.find((session) => session.id === sessionId);
        return {
          sessions: upsert(state.sessions, {
            id: view.id,
            title: view.title,
            created_at: view.created_at,
            updated_at: view.updated_at,
            message_count: existing?.message_count ?? 0,
          }),
          error: null,
        };
      });
    } catch (error) {
      set({ error: error instanceof Error ? error.message : "重命名会话失败" });
    }
  },
}));
