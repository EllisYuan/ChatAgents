# ChatAgents 前端

这是 ChatAgents 的 Vite + React SPA。前端是呈现层：聊天、AG-UI 流和 trace 细节会在后续 feature 中接入；本票先提供稳定的 session 路由、状态管理接缝和类型管道。

## 开发

```bash
npm install
npm run dev
```

Vite 会把 `/api` 与 `/health` 代理到本地 FastAPI（默认 `http://127.0.0.1:8080`）。可以通过 `VITE_BACKEND_ORIGIN` 覆盖后端地址：

```bash
VITE_BACKEND_ORIGIN=http://127.0.0.1:19180 npm run dev
```

直接打开 `/s/<uuid>` 或刷新该地址时，Vite dev server 会回退到 `index.html`；生产静态服务器也必须配置 `try_files $uri $uri/ /index.html`。

## 类型管道

后端唯一的契约源是 `backend/src/chat_agents/main.py` 的 `app.openapi()`。本地运行 `npm run generate:types` 会通过 `uv` 临时导出该 schema，再调用 `openapi-typescript` 生成 `src/generated/api.d.ts`。CI 则下载后端 job 上传的 OpenAPI artifact，通过 `OPENAPI_INPUT` 复用同一脚本。

OpenAPI JSON 和生成的 TypeScript 都被 `.gitignore` 排除，不提交契约副本。AG-UI 流事件的 envelope 来自精确锁定的 `@ag-ui/core`；自有 payload 由 OpenAPI components schema 提供。

```bash
npm run lint
npm run typecheck
npm run build
```

本项目不安装 Vitest、React Testing Library、Playwright、`@ag-ui/client` 或 `rxjs`。前端 CI 的门禁是 lint、`tsc --noEmit` 与 production build。
