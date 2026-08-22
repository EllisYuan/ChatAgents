import { useMemo } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";

import { EvalsPage } from "./features/evals/EvalsPage";
import { SessionPage } from "./features/session/SessionPage";
import { SessionSidebar } from "./features/sessions/SessionSidebar";
import { uuidv7 } from "./utils/uuid";

function Shell() {
  const location = useLocation();
  // 侧边栏高亮当前会话——Shell 在 Routes 之外，读不到 useParams，从路径里取。
  const activeSessionId = useMemo(() => {
    const match = /^\/s\/([^/]+)/.exec(location.pathname);
    return match ? decodeURIComponent(match[1]) : null;
  }, [location.pathname]);

  return (
    <div className="app-shell">
      <header className="topbar">
        <NavLink className="brand" to="/" aria-label="返回 ChatAgents 首页">
          <span className="brand-mark" aria-hidden="true">
            ◒
          </span>
          <span>CHATAGENTS</span>
        </NavLink>
        <div className="topbar-status">
          <span className="status-dot" aria-hidden="true" />
          <span>LOCAL / READY</span>
        </div>
      </header>
      <div className="app-body">
        <SessionSidebar activeSessionId={activeSessionId} />
        <main className="route-stage">
          <Routes>
            <Route path="/" element={<LandingPage />} />
            <Route path="/s/:sessionId" element={<SessionPage />} />
            <Route path="/evals" element={<EvalsPage />} />
            <Route path="*" element={<Navigate replace to="/" />} />
          </Routes>
        </main>
      </div>
      <footer className="site-footer">
        <NavLink className="text-button" to="/evals">
          评测数据
        </NavLink>
      </footer>
    </div>
  );
}

function LandingPage() {
  // 会话随第一条用户消息诞生（issue #65）：这里只生成路由用的 UUIDv7，不创建
  // 任何后端记录——真正的会话行要等用户发出第一条消息时由 upsert 产生。
  const draftSessionId = useMemo(() => uuidv7(), []);

  return (
    <section className="landing-page" aria-labelledby="landing-title">
      <p className="eyebrow">OBSERVABILITY / CHAT SURFACE</p>
      <h1 id="landing-title">
        Think in
        <span>signals.</span>
      </h1>
      <p className="landing-copy">
        一个面向 agent run 的工作台。输入 session link，进入对话、工具调用与 trace 的同一条时间线。
      </p>
      <NavLink className="primary-action" to={`/s/${draftSessionId}`}>
        <span>开始新会话</span>
        <span aria-hidden="true">↗</span>
      </NavLink>
      <div className="landing-index" aria-hidden="true">
        <span>01</span>
        <span className="index-line" />
        <span>CHAT / TRACE / RUN</span>
      </div>
    </section>
  );
}

export default function App() {
  return <Shell />;
}
