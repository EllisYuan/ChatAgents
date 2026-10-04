import { useMemo } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";

import { ResizableColumns } from "./components/ResizableColumns";
import { EvalsPage } from "./features/evals/EvalsPage";
import { SessionPage } from "./features/session/SessionPage";
import { SettingsDialog } from "./features/settings/SettingsDialog";
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
          <span>ChatAgents</span>
        </NavLink>
      </header>
      <ResizableColumns
        className="app-body"
        storageKey="chatagents.sessions-width"
        label="调整 Sessions 宽度"
        fixedSide="start"
        defaultWidth={256}
        minWidth={200}
        maxWidth={480}
        contentMinWidth={480}
        start={<SessionSidebar activeSessionId={activeSessionId} />}
        end={<main className={`route-stage${activeSessionId ? " route-stage--session" : ""}`} tabIndex={0} aria-label="页面内容">
          <Routes>
            <Route path="/" element={<LandingPage />} />
            <Route path="/s/:sessionId" element={<SessionPage />} />
            <Route path="/evals" element={<EvalsPage />} />
            <Route path="*" element={<Navigate replace to="/" />} />
          </Routes>
        </main>}
      />
      <SettingsDialog />
    </div>
  );
}

function LandingPage() {
  // 会话随第一条用户消息诞生（issue #65）：这里只生成路由用的 UUIDv7，不创建
  // 任何后端记录——真正的会话行要等用户发出第一条消息时由 upsert 产生。
  const draftSessionId = useMemo(() => uuidv7(), []);

  return (
    <section className="landing-page" aria-labelledby="landing-title">
      <h1 id="landing-title">有什么可以帮你？</h1>
      <p className="landing-copy">开始新会话，或从左侧继续之前的会话。</p>
      <NavLink className="primary-action" to={`/s/${draftSessionId}`}>
        <span>开始新会话</span>
      </NavLink>
    </section>
  );
}

export default function App() {
  return <Shell />;
}
