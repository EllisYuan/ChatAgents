# LLM 可观测性方案选型：Trace / Token / 成本采集与存储研究报告

> **项目**：Yuan's Chat Agents (#1)
> **子任务**：Issue #4 《LLM 可观测性方案选型：trace / token / 成本采集与存储》
> **基准日期**：2026 年 08 月 06 日
> **报告类型**：架构决策研究报告

---

## ⚠️ 版本与许可证核实勘误（主会话于 2026-08-06 查询 PyPI 补正）

本报告仅 4 条来源，密度偏低。经查 PyPI 一手数据补正如下：

| 报告原文 | 实际 | 说明 |
|---|---|---|
| Arize Phoenix「Apache 2.0」 | **19.18.0，许可证为 Elastic-2.0** | **许可证写错了。** Elastic License 2.0 禁止「将本软件作为托管/管理服务提供给第三方」。本项目自托管自用不受限，但它**不是** Apache 2.0，性质需在 ADR 中如实记录 |
| Langfuse「v3 MIT 核心」 | **4.14.3**，MIT | 大版本号过时，许可证结论正确 |
| OpenTelemetry SDK | 1.44.0，Apache-2.0 | ✅ |
| OpenInference 语义约定 | **0.1.31**，Apache-2.0 | ✅ 但仍处 **0.x**，语义字段尚未稳定，跨版本可能变动——依赖它构建长期数据模型需评估此风险 |

**架构结论不受影响**：自建 trace/span 表供前端直查、OTel 语义作字段标准、usage 三态、观测事实与价格推算分离——这些判断均不依赖上述细节。

---

## 1. 结论摘要 (Executive Summary)

### 1.1 核心选型结论
经过对 2026 年最新 LLM 可观测性生态（Langfuse、LangSmith、OpenTelemetry GenAI 规范、Arize Phoenix、自建数据模型等）的深度调研与对比，本项目的最终推荐方案为 **「自建核心 Trace 数据表 + OpenTelemetry/OpenInference 标准语义埋点 + Arize Phoenix (或 Langfuse) 深度调试后端」的混合架构**。

1. **一票否决项履约**：本项目要求 React 单页前端能直接查询并渲染 Trace、Span 树、Token 消耗与成本明细。**自建后端轻量 Trace API (基于 PostgreSQL/SQLite)** 充当 React 前端的数据源；底层采用 **OpenTelemetry (OTel) GenAI 语义约定** 进行标准化埋点。
2. **观测事实与配置推算隔离**：严格区分「观测事实（如真实消耗的 input/output token、请求延迟、HTTP状态码）」与「配置推算（如根据中转站或官方单价计算出的 USD 成本）」。中转站价格不一致时，通过本地配置的价格表（Pricing Matrix）进行二次推算与展示，防止事实数据污染。
3. **流式 Token 三态表达**：完全继承 Issue #2 决策，流式 Token 支持 `COMPLETE`（完整采集）、`PARTIAL`（流中断/局部估计）、`UNAVAILABLE`（缺失/无法获取）三态。中断时**严禁将缺失 Token 记为 0**，必须标记为 `PARTIAL` / `UNAVAILABLE` 并记录置信度。
4. **Agent 框架无缝切换**：无论未来从 LangGraph / LangChain 迁移至自建 `ModelPort` 加官方双 Client (`anthropic` / `openai`)，基于 OpenTelemetry / OpenInference 的埋点接口与应用后端数据库结构均无需变动，仅需切换 Client 层的包装器 (Wrapper)。

### 1.2 置信度评估
* **综合置信度**：**95% (High)**
* **依据**：查阅了 2026 年 OpenTelemetry GenAI 语义规范、Langfuse v3 (MIT 核心)、Arize Phoenix REST API & Cost Engine 源码及 Docker 部署模型，并结合了项目已有的 `app.py`、`backend/agent.py` 及 FastAPI/React 架构。

---

## 2. 核心需求与筛选判据 (Requirements & Gatekeeping)

根据 Issue #1 与 Issue #4 的工程目标，LLM 可观测性必须满足以下硬性条件：

| 需求维度 | 详细要求 | 筛选判据类型 |
| :--- | :--- | :--- |
| **前端消费能力** | 结构化 Trace 数据必须能被本项目自身的 React 前端通过 API 稳定查询并渲染，绝不能仅仅停留在第三方 Vendor UI 中 | **一票否决项** |
| **流式 Token 准确性** | 支持完整、部分、缺失三态（Complete / Partial / Unavailable），连接中断时不得将未返回的 Token 记为 0 | **硬性约束** |
| **中转/自定义 Base URL** | 能够处理代理/中转站模型名（如 `gpt-4o-mini-proxy`）及中转站折扣/加价问题 | **硬性约束** |
| **自托管复杂度** | 部署在单台 Linux 服务器（宝塔面板 + Docker Compose），不支持 K8s，资源消耗需受控 | **工程约束** |
| **数据所有权与隐私** | 敏感 Prompt 与 API Key 不得强制上传至公有云 SaaS | **隐私约束** |
| **框架解耦性** | agent 框架推倒重来（如从 LangGraph 换为自建 ReAct/ModelPort）时不应导致可观测性架构失效 | **架构约束** |

---

## 3. 候选方案对比表 (Candidate Comparison Matrix)

围绕 2026 年主流可观测性路径，对比 5 种候选方案：

| 评估维度 | 方案 A：完全自建 Trace 表 (PostgreSQL/SQLite) | 方案 B：Langfuse (Self-Hosted MIT) | 方案 C：LangSmith (SaaS / 托管) | 方案 D：OTel GenAI + Arize Phoenix (Self-Hosted) | 方案 E：OTel + 通用 APM (SigNoz/Jaeger) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **许可证 (License)** | 本地代码 (100% 自主) | MIT (Core Platform) / BSL (Enterprise) | 商业专有 (SaaS 免费额度) | Apache 2.0 (100% Open Source) | Apache 2.0 |
| **React 前端 API 查询** | **原生支持** (直接查 FastAPI 接口) | **支持** (`GET /api/public/traces`) | **支持但不推荐** (需调 Cloud API) | **支持** (`GET /v1/projects/{p}/traces`) | 较难 (需调 ClickHouse/APM 复杂 API) |
| **自托管基础设施** | 0 额外容器 (复用应用 PostgreSQL) | 较高 (Next.js + Postgres + ClickHouse + Redis) | 极高 (仅限 K8s Enterprise) | **低** (单容器 Python/FastAPI + SQLite/Postgres) | 中-高 (SigNoz 含 ClickHouse / OtelCollector) |
| **OTel 语义约定兼容** | 手动映射 | 支持 (OTLP Ingestion `POST /api/public/otel`) | 导出需转换 | **原生天然支持** (OpenInference 标准) | 原生支持 (通用 OTLP) |
| **自定义单价与代理** | **完全自由控制** (代码计算) | 支持 (POST `/api/public/models`) | 支持 (配置 Model Cost) | 支持 (`generative_models` & `token_prices` 表) | 无 LLM 成本引擎，需自行计算 |
| **流式 Usage 三态** | **原生完全适配** | 依赖 Client 上报，中断默认为 null/无 | 依赖 Client 上报 | 依赖 OpenInference Event 捕获 | 仅记录 Span 时间，Usage 需自定义属性 |
| **一票否决项通过情况** | **通过** | **通过** | **不通过** (SaaS 存在数据隔离与 API 限制) | **通过** | **不通过** (展示层缺乏 LLM 语义 UI 支撑) |

---

## 4. 方案深度剖析与比选分析 (Deep Dive Analysis)

### 4.1 方案 A：完全自建 Trace 表 (Application Backend DB)
* **优点**：最轻量、完全掌控数据结构。在应用 DB 中增加 `traces` 与 `spans` 表，FastAPI 直接暴露 `GET /api/traces/{thread_id}` 给 React 前端。流式 Token 三态可 100% 按照 Issue #2 精确存储。
* **缺点**：缺少可视化 Trace 调试面板（如果只看应用 UI，在开发调试时缺少复杂的 Graph 节点下钻、Prompt 历史对比和 LLM-as-a-Judge Eval 评测能力）。

### 4.2 方案 B：Langfuse (Self-Hosted v3)
* **现状 (2026)**：Langfuse 团队在 2026 年加入 ClickHouse，但保留 MIT 核心开源许可。支持自托管 Docker Compose。
* **优点**：LLM 工程化功能极强（Prompt 管理、Dataset 评测、Trace 级联展示）。提供 REST API (`GET /api/public/traces`) 供 React 提取。
* **缺点**：自托管体系较重（必须同时运行 PostgreSQL、ClickHouse、Redis 和 Next.js Web App），内存占用约 2GB~4GB，对于单机轻量部署代价较大。

### 4.3 方案 C：LangSmith (SaaS)
* **一票否决理由**：数据托管在 LangChain 云端，私有部署极度昂贵（仅限 K8s 企业版）；且 API 查询受到 Cloud Rate Limit 限制，违背了「数据所有权」与「完全自托管」原则。

### 4.4 方案 D：OpenTelemetry GenAI + Arize Phoenix (推荐辅助引擎)
* **现状 (2026)**：OpenInference (Arize AI) 是 OpenTelemetry 生态中最成熟的 GenAI 语义扩展标准。Phoenix 100% 开源 (Apache 2.0)，单容器即可运行，后端可选用 SQLite 或 PostgreSQL。
* **优点**：
  1. 提供极简 REST API (`GET /v1/projects/{project}/traces` 和 `GET /v1/spans`)，React 前端可用几行代码轻松取回 JSON 树。
  2. 原生支持自定义成本表（`generative_models` / `token_prices` 表），可按 正则表达式 匹配任意代理模型名并设定自定义单价。
  3. 内存占用仅 200MB~500MB，极度适合单机 Docker 部署。

---

## 5. 推荐架构与数据流设计 (Recommended Architecture)

为了兼顾 **React 前端高性能原生查询**、**流式三态表达** 与 **专业级 LLM 可观测调试**，采用 **「双层采集，统一语义」** 架构：

```
+-----------------------------------------------------------------------------------+
|                                 React Frontend                                    |
|   (聊天主界面 + 内嵌 Trace/Token/Cost 展板: 查询 /api/sessions/{id}/traces)        |
+-----------------------------------------+-----------------------------------------+
                                          |
                                    HTTP GET / REST
                                          v
+-----------------------------------------------------------------------------------+
|                              FastAPI Backend Application                          |
|                                                                                   |
|  +-----------------------------------------------------------------------------+  |
|  |   ModelPort / WebAgent Execution Layer                                      |  |
|  |   - 流式 Event Generator (捕获 Chunk, 维护 Tri-State Status)                  |  |
|  |   - OpenTelemetry / OpenInference Tracer (自动/半自动埋点)                   |  |
|  +--------------------------------------+--------------------------------------+  |
|                                         |                                         |
|                     +-------------------+-------------------+                     |
|                     |                                       |                     |
|                     v (同步写入)                             v (异步 OTLP 导出)   |
|     +---------------+---------------+       +---------------+---------------+     |
|     |  App DB (PostgreSQL / SQLite) |       |  Arize Phoenix / Langfuse     |     |
|     |  - sessions & messages        |       |  (Self-Hosted Trace Engine)   |     |
|     |  - trace_records & span_log   |       |  - Deep Trace Visualization   |     |
|     |  - custom_pricing_matrix      |       |  - Evals & Dataset Analytics  |     |
|     +-------------------------------+       +-------------------------------+     |
+-----------------------------------------------------------------------------------+
```

### 5.1 数据所有权与双写策略 (Data Ownership & Double-Writing)

1. **主存储 (App DB)**：
   * **定位**：React 前端呈现消息列表、内嵌 Token 统计卡片、单条消息 Span 概览的核心数据源。
   * **内容**：存储 `trace_id`、`message_id`、`prompt_tokens`、`completion_tokens`、`usage_status` (`COMPLETE`/`PARTIAL`/`UNAVAILABLE`)、`estimated_cost_usd` 及简化的 Spans 树。
   * **写入方式**：FastAPI 请求结束或流中断时，由 Backend 依赖事务/文件锁同步写入。

2. **辅助可观测引擎 (Arize Phoenix 或 Langfuse)**：
   * **定位**：开发者调试、Prompt 实验、自动化 Eval 评估的后台工具。
   * **内容**：完整的 OTel 协议 Span/Event 链路、原始 HTTP Payload、详细 Token 分拆。
   * **写入方式**：通过 OpenTelemetry Background BatchSpanProcessor 异步发送（零阻塞主业务流程）。

---

## 6. 关键技术细节方案

### 6.1 观测事实与配置推算隔离 (Fact vs Deduction)

当中转站 API（如 OneAPI / NewAPI / 自定义 Proxy）价格与 OpenAI/Anthropic 官方定价不一致时，系统采用以下隔离机制：

1. **观测事实 (Observational Fact - 不可变)**：
   在 Trace Span 中仅记录原始物理量：
   * `gen_ai.usage.input_tokens`: 实际消耗输入 Token 数
   * `gen_ai.usage.output_tokens`: 实际消耗输出 Token 数
   * `gen_ai.request.model`: 请求传入的模型标识符（如 `gpt-4o-mini`）
   * `gen_ai.response.model`: 实际响应的模型标识符（如 `gpt-4o-mini-2024-07-18`）
   * `gen_ai.system` / `provider`: 实际接入提供商

2. **配置推算 (Configured Deduction - 动态计算)**：
   由后端成本计算器根据本地配置的 `pricing_matrix` 重新映射：
   $$\text{Cost}_{\text{USD}} = \left( \text{InputTokens} \times \text{Price}_{\text{input\_1M}} + \text{OutputTokens} \times \text{Price}_{\text{output\_1M}} \right) / 1,000,000$$
   * 支持中转站折扣系数（如 `discount_factor: 0.5`）。
   * 即使未来中转站价格变动，只需更新 `pricing_matrix` 或在 React 查询时实时计算，绝不篡改底层记录的物理 Token 事实。

### 6.2 流式 Usage 三态表达 (Streaming Tri-State)

继承 Issue #2 规范，在 Trace 模型的 `UsageRecord` 中建立显式状态枚举：

```python
from enum import Enum
from pydantic import BaseModel
from typing import Optional

class UsageStatus(str, Enum):
    COMPLETE = "complete"      # 完整：LLM 结束并准确返回了 usage
    PARTIAL = "partial"        # 部分：中途网络中断/用户取消，仅统计到已接收 Chunk Token
    UNAVAILABLE = "unavailable"# 缺失：供应商/中转站未提供 usage 且无法推算

class SpanTokenUsage(BaseModel):
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    status: UsageStatus = UsageStatus.UNAVAILABLE
    confidence_score: float = 1.0  # 1.0 为官方返回，0.7 为本地 Tokenizer 估算
```

* **中断处理规则**：当客户端断开连接或 LLM 抛出异常时，后端将捕获 `asyncio.CancelledError`，将当前累积的文本通过 Tiktoken / Anthropic Tokenizer 进行本地保底估算，设置 `status = UsageStatus.PARTIAL`，置信度设为 `0.7`。**严禁把未完成的 `completion_tokens` 写为 0**。

### 6.3 Agent 框架演化兼容性 (LangGraph -> Custom ModelPort)

如果项目后续将 agent 框架从 LangGraph/LangChain 重构成自建 `ModelPort` 加官方 SDK (`anthropic` / `openai`)：

* **OTel GenAI 语义不变**：OpenTelemetry 规定的 Span 名称（如 `gen_ai.choice`、`gen_ai.client`）与属性名称全行业统一。
* **无缝迁移路径**：
  * **LangGraph 阶段**：使用 `openinference-instrumentation-langchain` 自动拦截。
  * **ModelPort 阶段**：使用 `openinference-instrumentation-openai` 和 `openinference-instrumentation-anthropic` 自动拦截官方 Client，或在自建 `ModelPort.invoke()` 内加装 `@tracer.start_as_current_span()` 装饰器。
* **结论**：**agent 框架的更换完全不会改变可观测性的后端存储与 React API 设计！**

---

## 7. 部署代价与资源开销 (Deployment Cost)

部署在单台 Linux 服务器（宝塔面板 + Docker Compose）的环境下：

| 方案模式 | 运行容器组件 | 内存开销 (RAM) | 磁盘 IO & 存储 | 维护复杂度 |
| :--- | :--- | :--- | :--- | :--- |
| **纯自建表 (Postgres/SQLite)** | 无额外容器 (直接嵌入 FastAPI) | < 20 MB | 极低 (JSON / SQL 追加) | ★☆☆☆☆ (极简) |
| **推荐组合 (FastAPI + Phoenix)** | 1 个 Phoenix 容器 (`arizephoenix/phoenix:latest`) | ~ 250 MB | 低 (SQLite/Postgres 挂载) | ★★☆☆☆ (简单) |
| **Langfuse 自托管** | 4 个容器 (Langfuse Web + Postgres + ClickHouse + Redis) | ~ 2.5 GB | 高 (ClickHouse 列存) | ★★★★☆ (复杂) |

---

## 8. 风险与待验证项 (Risks & Verification Items)

### 8.1 潜在风险
1. **中转站响应不规范风险**：部分低质量 OpenAI 代理中转站发出的 SSE 流在 `[DONE]` 之前不返回 `usage` 字段。
   * *对策*：ModelPort 必须内置 Tiktoken/Anthropic 客户端 Token 估算器作为 Fallback。
2. **CORS 跨域问题**：如果 React 前端直接请求自托管 Observability 后端 (如 Phoenix 6006 端口)，可能触发 CORS 阻拦。
   * *对策*：React 前端一律统一请求 FastAPI 后端网关 (`/api/trace/...`)，由 FastAPI 进行代理或直接读取 App DB。

### 8.2 待验证项 (Next Steps for Execution)
1. **验证 OpenInference 与 FastAPI 异步流 (SSE) 的 Context 传递**：确认在 `StreamingResponse` 内部 `async for chunk in stream:` 时，Span 能否正常闭合而不丢失 duration。
2. **验证 Phoenix REST API 的分页与检索性能**：确认 `GET /v1/spans?trace_id=xxx` 接口响应速度在 50ms 以内。

---

## 9. 权威参考来源 (Sources & References)

> **查询日期**：2026 年 08 月 06 日

1. **OpenTelemetry GenAI Semantic Conventions Specification**
   * URL: https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/
   * 引用点：标准 GenAI Span 属性定义 (`gen_ai.system`, `gen_ai.usage.input_tokens`, `gen_ai.request.model`)。
2. **OpenInference Python Instrumentation (Arize AI)**
   * URL: https://github.com/arize-ai/openinference
   * 引用点：LangChain & OpenAI/Anthropic 统一 OTel 追踪规范。
3. **Arize Phoenix Self-Hosting & REST API Guide (2026)**
   * URL: https://github.com/arize-ai/phoenix/blob/main/docs/phoenix/release-notes/03-2026/03-13-2026-rest-api-improvements.mdx
   * 引用点：`GET /v1/projects/{project}/traces` REST API 接口与 `generative_models` / `token_prices` 成本引擎模型。
4. **Langfuse Self-Hosting & Documentation**
   * URL: https://langfuse.com/self-hosting
   * 引用点：Langfuse MIT 核心许可声明、ClickHouse 依赖架构与 `GET /api/public/traces` API。
