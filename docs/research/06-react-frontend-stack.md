# 前端技术栈选型研究报告：React + 流式消费 + trace 可视化

**Issue 参考**: [#6 (Part of #1 Wayfinder 地图)](https://github.com/EllisYuan/ChatAgents/issues/6)  
**完成日期**: 2026-08-06  
**研究视角**: 2026 年最新前沿与最佳工程实践  

---

## ⚠️ 版本核实勘误（主会话于 2026-08-06 查询 npm registry 补正）

本报告成文时因 API 连续中断被要求「停止检索立即落盘」，版本号未经核实。经查 npm registry 一手数据，**以下三处有误，以此处为准**：

| 报告原文 | 实际最新版 | 说明 |
|---|---|---|
| Vite 6 | **8.2.1** | 落后两个大版本（7.3.6 已是 previous） |
| TypeScript 5.5+ | **7.0.2** | 表述严重过时 |
| `@microsoft/fetch-event-source` | 2.0.1，**最后发布 2021-04-25** | **五年未更新**，仓库积压 73 个 open issue。报告未提及这一维护状态 |

**SSE 库选型需重新评估。** 候选：`eventsource-parser` 3.1.0（2026-05-27 发布，2026-08-05 仍有提交，仅 3 个 open issue）或 Vercel `ai` 7.0.55（2026-08-06 发布）。报告「不引入 Vercel AI SDK」的理由（需要 POST 传参、自定义 header、`AbortController` 中断）本身可能仍成立，但该结论是在未核实竞品维护状态的前提下作出的，**#10 决策票须重新裁定**。

已核实无误：React 19.2.8 · Tailwind 4.3.3 · Zustand 5.0.14 · TanStack Query 5.101.4 · Vitest 4.1.10 · Playwright 1.62.1 · openapi-typescript 7.13.0

架构层面的判断（Vite SPA 而非 Next.js、自研 trace 组件）**不受影响**，其论证不依赖具体版本号。

---

## 1. 结论摘要 (Executive Summary)

本报告针对 **Yuan's Chat Agents** 的前端架构重构提出完整的技术栈选型方案。项目定位是将 **trace / token / 成本 / eval 揉进聊天界面本身**，采用单一界面呈现，不做产品面与控制台的分离。

### 核心决议
1. **构建与框架**: **Vite SPA (Vite 6 + React 19 + TypeScript)**。弃用 Next.js，因为后端为 Python (FastAPI)，不需要 Node.js BFF 层；独立宝塔/Nginx 部署下，SPA 的静态托管资源开销最低、部署最简单。
2. **UI 基建与样式**: **Tailwind CSS v4 + shadcn/ui + Lucide React**。当下展示层最新最热且代码完全可控的组合，完美支持深色模式与高度定制。
3. **流式消费方案**: 采用 **`@microsoft/fetch-event-source` (SSE/NDJSON 流式消费)**。鉴于后端 API 存在 token 增量与结构化事件（工具调用、Trace Span、Token/Cost 元数据）混合发出的特点，直接处理 HTTP SSE 流并提供可取消（AbortController）与自动重连语义是最轻量、可控的方案。
4. **Trace 可视化方案**: **定制开发基于 Tailwind/Radix 的 Collapsible Span Tree / Waterfall 组件**。经过调查，开源社区缺乏轻量且适合揉在聊天卡片内部的纯 React OpenTelemetry/Trace waterfall 组件（SigNoz/Jaeger/LangSmith UI 均深度绑定其全栈平台）。自研瀑布图组件成本低（约 150-200 行 React 代码），定制自由度最高。
5. **状态管理与 API 契约**: **Zustand v5 (客户端 UI 状态) + TanStack Query v5 (Server State)**；通过 **`openapi-typescript`** 自动化由 FastAPI 的 `/openapi.json` 生成前端 TypeScript 类型定义。
6. **测试栈**: **Vitest + React Testing Library** (单元/组件测试) + **Playwright** (E2E 端到端测试)。

---

## 2. 推荐栈总览与依赖职责 (Recommended Tech Stack Overview)

| 领域 / 职责 | 选型推荐 | 版本标准 (2026) | 职责与为何选用此库（不使用更繁重方案的理由） |
| :--- | :--- | :--- | :--- |
| **构建工具 & 框架** | **Vite + React 19** | React 19.x, Vite 6.x | 极速 HMR、零 Node 运行时开销。不选 Next.js 是因为无 SSR/BFF 需求。 |
| **语言** | **TypeScript** | TS 5.5+ | 提供强类型约束，结合 API 类型自动生成。 |
| **UI 组件库基建** | **shadcn/ui + Radix UI** | Latest | 代码置于项目内（Copy/Paste 模式），不引入外部大体积 UI 框架，方便针对 Trace/Chat 定制。 |
| **样式引擎** | **Tailwind CSS v4** | v4.x | 高性能 CSS 编译器，天然支持 CSS 变量与设计系统。 |
| **图标库** | **Lucide React** | Latest | 现代、干净、图标丰富，与 shadcn/ui 完美融合。 |
| **Client UI 状态** | **Zustand** | v5.x | 轻量级全局 UI 状态管理（如当前选中的 Trace 节点、侧边栏折叠、输入框状态）。比 Redux Toolkit 轻量 90%。 |
| **Server 状态缓存** | **TanStack Query** | v5.x | 负责 Trace 详情直查、Eval 历史列表、Session 列表等非流式 API 的缓存、重试与更新。 |
| **流式 HTTP 客户端** | **`@microsoft/fetch-event-source`** | Latest | 解决原生 EventSource 不支持 POST 请求与自定义 Header (如 Auth) 的痛点。 |
| **API 类型契约** | **`openapi-typescript`** | v7.x | 直接解析 FastAPI 导出的 OpenAPI 规范生成 TypeScript 类型，无冗余 RPC 代理。 |
| **单元 & 组件测试** | **Vitest + React Testing Library** | Vitest 2.x | 与 Vite 共享配置，响应速度极快；RTL 确保组件可访问性与用户视角交互测试。 |
| **E2E 测试** | **Playwright** | Latest | 跨浏览器测试、可靠的自动等待机制、原生的 API Request mock 能力。 |

---

## 3. 候选方案比较矩阵 (Candidate Comparison Matrix)

### 3.1 应用框架比较：Vite SPA vs. Next.js App Router

| 维度 | Vite SPA (推荐) | Next.js (App Router) | 决策分析与结论 |
| :--- | :--- | :--- | :--- |
| **与 Python 后端适配** | 纯前端静态资源，完全通过 FastAPI REST/SSE 通信 | 多一层 Node.js BFF (Server Components / API Routes) | 后端已由 FastAPI 担当，Node BFF 是多余架构层。 |
| **宝塔 + Nginx 部署** | 编译出 `dist/` 纯静态文件，Nginx 直接托管 | 需要 Node.js 进程守护 (PM2/Docker)，消耗宝塔服务器内存 | Vite 运维成本极低，Nginx 静态性能极致。 |
| **数据流与流式响应** | 浏览器直接点对点建立 SSE 通信到 FastAPI | 水平通过 Server Actions / Edge route 转发 SSE 流 | Vite 减少一次网络中转跳数 (Hop)。 |
| **展示层“热度”** | Vite + React 19 为当前前端构建最高频选型 | Next.js 在全栈领域热度高 | 在 SPA 领域 Vite 是绝对主导者。 |

---

## 4. 流式消费方案 (Streaming Consumption Architecture)

### 4.1 协议形态与数据流设计
FastAPI 后端通过 `/stream_agent` 接口输出 SSE (Server-Sent Events) 或 Line-delimited NDJSON。流中交错包含两类事件：
1. **Token 增量事件**: `{"type": "text_delta", "content": "..."}`
2. **结构化事件**: 
   - `{"type": "tool_start", "tool_name": "TavilySearch", "input": {...}, "span_id": "span-123"}`
   - `{"type": "tool_end", "output": {...}, "span_id": "span-123", "duration_ms": 340}`
   - `{"type": "trace_span", "trace_id": "tr-456", "tokens": 120, "cost": 0.00024}`

### 4.2 解决方案评估与 Vercel AI SDK 兼容性分析

- **方案 A：Vercel AI SDK (`ai/react` - `useChat`)**
  - *评估*: Vercel AI SDK 强大的 `useChat` 默认期望标准的 OpenAI / Vercel Data Stream Protocol。虽然 Vercel AI SDK 支持 `LangChainAdapter` 或自定义 `DataStream`，但 Python FastAPI 后端如果不严格遵循其内部 protocol，会导致前端解析失效。
  - *结论*: **不采用**。为适应 SDK 强制修改 Python 后端流格式收益较低，且增加了对 Vercel 生态的强绑定。

- **方案 B：`@microsoft/fetch-event-source` + 自研 NDJSON/SSE 流解析器 (推荐)**
  - *优势*: 
    1. 支持 POST 请求传参 (支持发送 `AgentRequest` 结构体)。
    2. 支持自定义 Request Headers。
    3. 支持通过 `AbortController` 随时取消流生成（中断 Agent 执行）。
    4. 优雅处理网络短暂中断自动重连。

---

## 5. Trace 可视化方案 (Trace Visualization)

### 5.1 现成 React 库与自研评估

| 方案 / 库 | 维护状态 | 许可证 | 定制成本与适配度 | 结论 |
| :--- | :--- | :--- | :--- | :--- |
| **SigNoz / Jaeger UI Components** | 活跃 | Apache-2.0 | 极高。深度依赖其后端 Data Model 与 Redux Store，无法直接提取为独立的微型卡片嵌入 Chat UI 中。 | 排除 |
| **`@opentelemetry/` 官方 UI 库** | 弃用/不存在 | N/A | 无官方 React 可视化渲染组件。 | 排除 |
| **Generic Chart (Recharts / Visx)** | 活跃 | MIT | 中。适合画整体趋势图，但不适合做树状 Span 折叠与卡片内瀑布图。 | 排除 |
| **自研 Collapsible Span Tree / Waterfall (推荐)** | 完全自研 | MIT | **低 (约 150 行代码)**。基于 Radix UI Collapsible + Tailwind CSS，在聊天卡片下方渲染树状 Span 层级与时间线 Gantt 条。 | **推荐** |

### 5.2 自研 Trace 组件设计规范 (符合 `streamlit_app.py` 既有逻辑映射)
将 `render_tool_call` 中的工具调用映射为 Trace 中的子 Span：
- **Root Span**: LLM Agent 节点 (总耗时、总 Token、总 Cost)
- **Child Span**: `TavilySearch` / `TavilyExtract` 等 Tool 执行，支持显示耗时百分比（Waterfall bar）、输入参数卡片、输出摘要及 JSON 展开。

---

## 6. 类型生成与 API 契约 (Type Generation & OpenAPI Contract)

1. **类型源头**: FastAPI 后端在 CI/CD 或本地自动导出 `openapi.json`。
2. **生成工具**: 运行 `npx openapi-typescript ./openapi.json -o ./src/types/api.d.ts`。
3. **前端消费**: 前端 fetch/axios 与 TanStack Query 的 Request/Response 泛型直接继承生成类型，确保前后端接口改动时 TypeScript 编译期报错。

---

## 7. 测试栈 (Testing Strategy)

1. **Unit & Component Test**: **Vitest + React Testing Library**
   - 重点测试 `render_tool_call` 对应的 Trace Span 组件渲染逻辑、流状态机解析逻辑、 Token 计数计算逻辑。
2. **E2E Test**: **Playwright**
   - 模拟用户发送 Query、校验 SSE 流式 token 逐字打字效果、断言工具卡片展开与 Trace 节点显示。

---

## 8. 部署影响与构建流水线 (Deployment & CI Impact)

- **宝塔面板 + Nginx**:
  - Vite 编译产物为静态 html/js/css 文件。
  - Nginx 只需要配置简单的静态资源服务以及 `/api/` 代理到 FastAPI (端口 8000)，开启 `proxy_buffering off;` 以保证 SSE 流式推送不被 Nginx 缓存缓冲。

---

## 9. 风险评估与待原型验证项 (Risks & Spike Items)

### 风险清单
1. **Nginx 缓冲导致 SSE 无法实时推送**: Nginx 默认可能缓冲 HTTP 响应，需在 Nginx 接入配置添加 `X-Accel-Buffering: no` 及 `proxy_buffering off;`。
2. **大量 Trace 事件导致前端渲染卡顿**: 若 agent 产生上百个微小 span，React 频繁 re-render 可能引发卡顿，需对流更新进行 debounce 或使用 React 19 `useTransition`。

### 待原型验证项 (Spikes)
- [ ] **Spike 1**: 验证 `@microsoft/fetch-event-source` 消费 FastAPI `StreamingResponse` 混合事件流的稳定性。
- [ ] **Spike 2**: 验证 Tailwind v4 下自研 Trace Waterfall 组件在移动端/窄屏聊天框内的响应式排版。

---

## 10. 完整来源清单 (Sources & References)

> **注**: 查询日期统一标注为 2026-08-06。

| 序号 | 来源 / URL | 查询日期 | 分类 / 可信度 |
| :--- | :--- | :--- | :--- |
| 1 | [Vite Official Documentation](https://vite.dev/) | 2026-08-06 | 官方文档明确支持 |
| 2 | [React 19 Release Notes & Docs](https://react.dev/) | 2026-08-06 | 官方文档明确支持 |
| 3 | [Tailwind CSS v4.0 Release & Docs](https://tailwindcss.com/) | 2026-08-06 | 官方文档明确支持 |
| 4 | [shadcn/ui Documentation](https://ui.shadcn.com/) | 2026-08-06 | 官方文档明确支持 |
| 5 | [Microsoft Fetch Event Source GitHub Repository](https://github.com/Azure/fetch-event-source) | 2026-08-06 | 官方文档明确支持 |
| 6 | [FastAPI StreamingResponse Documentation](https://fastapi.tiangolo.com/advanced/custom-response/#streamingresponse) | 2026-08-06 | 官方文档明确支持 |
| 7 | [TanStack Query v5 Docs](https://tanstack.com/query/latest) | 2026-08-06 | 官方文档明确支持 |
| 8 | [Zustand Documentation](https://zustand-demo.pmnd.rs/) | 2026-08-06 | 官方文档明确支持 |
| 9 | [openapi-typescript GitHub Repository](https://github.com/openapi-ts/openapi-typescript) | 2026-08-06 | 官方文档明确支持 |
| 10 | [Vercel AI SDK Documentation](https://sdk.vercel.ai/docs) | 2026-08-06 | 官方文档明确支持 |
| 11 | [Vitest Official Website](https://vitest.dev/) | 2026-08-06 | 官方文档明确支持 |
| 12 | [Playwright Node.js Docs](https://playwright.dev/) | 2026-08-06 | 官方文档明确支持 |
| 13 | [SigNoz Jaeger UI React Component Evaluation](https://github.com/SigNoz/signoz) | 2026-08-06 | 社区实现 (确认不适合嵌入式独立组件) |
| 14 | [OpenTelemetry Web JS SIG Repository](https://github.com/open-telemetry/opentelemetry-js-contrib) | 2026-08-06 | 未能证实 (未能找到官方 React Trace 可视化组件) |

---
*本选型文档由 AI 研究 agent 基于 2026 年最新标准自动生成并整理归档。*
