import { NavLink, Navigate, Route, Routes } from "react-router-dom";

import { EvalsPage } from "./features/evals/EvalsPage";
import { SessionPage } from "./features/session/SessionPage";

function Shell() {
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
      <main className="route-stage">
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/s/:sessionId" element={<SessionPage />} />
          <Route path="/evals" element={<EvalsPage />} />
          <Route path="*" element={<Navigate replace to="/" />} />
        </Routes>
      </main>
      <footer className="site-footer">
        <NavLink className="text-button" to="/evals">
          评测数据
        </NavLink>
      </footer>
    </div>
  );
}

function LandingPage() {
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
      <NavLink className="primary-action" to="/s/00000000-0000-0000-0000-000000000000">
        <span>打开 session 骨架</span>
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
