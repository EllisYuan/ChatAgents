# 研究报告索引

Wayfinder 地图 [#1 重构蓝图：从 demo 到 LLM 应用工程标杆](https://github.com/EllisYuan/ChatAgents/issues/1) 前沿研究票的产出。

**这些是证据，不是决定。** 最终选型以 `docs/adr/` 中的 ADR 为准；研究报告只提供事实与候选比较，供决策票裁决。

调研基准日期统一为 **2026-08-06**。

## 报告清单

| 票 | 报告 | 行数 | 核心结论 |
|---|---|---|---|
| [#2](https://github.com/EllisYuan/ChatAgents/issues/2) | [模型接入层](./02-model-access-layer.md) | 744 | 官方 client + 自建 `ModelPort`；**三协议并列**（Responses 优先）；**两层密钥来源**（用户优先、未填降级）；**模型清单运行时发现**（前后端均不硬编码）；**模型角色分离**（main / tool 独立可配） |
| [#3](https://github.com/EllisYuan/ChatAgents/issues/3) | [ReAct 框架](./03-react-agent-framework.md) | 378 | 自建显式 Async ReAct Loop；淘汰 LangGraph（类型系统与 `ModelPort` 冲突）；次选 Pydantic AI |
| [#4](https://github.com/EllisYuan/ChatAgents/issues/4) | [LLM 可观测性](./04-llm-observability.md) | 224 | 自建 trace 表供前端直查 + OTel GenAI 语义 + 自托管 Phoenix/Langfuse 深度调试 |
| [#5](https://github.com/EllisYuan/ChatAgents/issues/5) | [Agent 评测](./05-agent-evals.md) | 406+ | DeepEval + pytest 五层金字塔；**否定 vcrpy 录制 SSE**；判官模型只定标准不写型号 |
| [#6](https://github.com/EllisYuan/ChatAgents/issues/6) | [React 前端栈](./06-react-frontend-stack.md) | 156 | Vite SPA（不用 Next.js，BFF 多余）+ Tailwind/shadcn + 自研 trace 组件 |
| [#7](https://github.com/EllisYuan/ChatAgents/issues/7) | [Python 工具链](./07-python-engineering-toolchain.md) | 502+ | uv + Ruff + mypy 标准增量档 + Renovate；pre-commit 与 CI 分工 |
| [#8](https://github.com/EllisYuan/ChatAgents/issues/8) | [工具链扩展](./08-agent-tool-expansion.md) | 318 | 只加 `web_reader`（Jina Reader）替代 Tavily Extract/Crawl；**明确拒绝 MCP** |

## 已解决的交叉冲突

研究票并行执行，因此后完成的票可能推翻先完成的票的前提。以下冲突已在结算时识别并处理：

1. **#3 淘汰 LangGraph → 影响 #5、#7**
   两份报告成文时假定继续使用 LangGraph，其 L2 回放方案依赖 `StateSnapshot`。#3 给出了替代方案（自建 Loop 的显式 `AgentState` JSON dataclass），能力完全覆盖。已在 #5、#7 报告顶部加勘误声明，未改动原文。

2. **#5 否定 vcrpy → #7 已正确继承**
   #7 成文晚于 #5，已采纳 `httpx.MockTransport` 结论。一致，无需处理。

3. **#4 trace 前端直查 ↔ #6 前端假设**
   两份报告独立得出一致结论（FastAPI 暴露结构化 API 供 React 直查）。相互印证。

4. **#6 选定 SSE ↔ #10 流式协议票（未开工）**
   #6 已预判了 #10 的结论。#10 开票时须显式确认或推翻，不得默认继承。

## 版本核实结果（主会话于 2026-08-06 直查 PyPI / npm registry）

针对成色存疑的报告，主会话独立核实了全部关键包的版本、发布日期与许可证。**查出三处实质错误**，已在对应报告顶部加勘误块。

### 已确认的错误

| 报告 | 错误 | 实际 |
|---|---|---|
| #6 | Vite 6 | **8.2.1**（落后两个大版本） |
| #6 | TypeScript 5.5+ | **7.0.2** |
| #6 | 推荐 `@microsoft/fetch-event-source` 未提维护状态 | **最后发布 2021-04-25，五年未更新**，73 个 open issue |
| #4 | Arize Phoenix「Apache 2.0」 | **Elastic-2.0**（禁止作为托管服务提供给第三方） |
| #2 | 「MVP 只做 Chat Completions，Responses 留作日后预留适配器」 | **判断有误（用户指正）**。OpenAI 格式本就是两种协议，且应优先 Responses。已改为三协议并列、Responses 优先；Responses contract test 从 P2 升为 P0 |

### 已核实无误

- **前端**：React 19.2.8 · Tailwind 4.3.3 · Zustand 5.0.14 · TanStack Query 5.101.4 · Vitest 4.1.10 · Playwright 1.62.1 · openapi-typescript 7.13.0
- **Python**：uv 0.12.2 · Ruff 0.16.1 · **mypy 2.3.0** · deepeval 4.1.5 · langgraph 1.2.10 · langgraph-prebuilt 1.1.0 · pydantic-ai 2.25.0 · smolagents 1.26.0 · mcp 2.0.0 · tavily-python 0.7.27 · opentelemetry-sdk 1.44.0 · langfuse 4.14.3

### 核实中发现的两个新风险

1. **`httpx` 停在 0.28.1（2024-12-06），一年半未发版**。而 #5 与 #7 的整个 mock 方案建立在 `httpx.MockTransport` 之上——这个依赖的活跃度需在 #17 决策票中过一眼。
2. **`vcrpy` 8.3.0 于 2026-07-04 仍有更新**，并非无人维护。#5 否定它的理由是「异步 SSE 支持有硬伤」（技术原因），该理由不因活跃度而失效；但若据此认为它已过气，则不准确。
3. **OpenInference 语义约定仍在 0.1.31（0.x）**，字段尚未稳定，跨版本可能变动。以它为长期数据模型基础需评估此风险。

## 其余质量提示

- **#3、#5** 均为 v2 重做版本，来源密度达标（各 12+ 条），并明确列出了推翻 v1 的证据。抽查的版本号全部属实。
- **#3 的一处修正值得注意**：v1 猜测「`create_react_agent` 已弃用」，v2 定位到源码 `@deprecated(LangGraphDeprecatedSinceV10)` 及官方迁移路径 `langchain.agents.create_agent`，并把淘汰主因从「已弃用」修正为更扎实的「类型系统与 `ModelPort` 矛盾」。
- **架构判断未受版本错误影响**：#6 的 Vite SPA 选型与自研 trace 组件论证、#4 的自建 trace 表与 OTel 语义方案，均不依赖具体版本号。

## 下一步

研究票关闭后，按地图的阻塞依赖逐张推进决策票（#9–#19），每张决策票产出 ADR。地图全部清空后才进入 `/to-spec` → `/to-tickets` → `/implement`。
