# Yuan's ChatAgents

<div align="center">

**一个把 trace、token、evals 揉进聊天界面本身的 ReAct agent**

![Python](https://img.shields.io/badge/Python-3.11--3.12-blue.svg)
![React](https://img.shields.io/badge/React-19-61DAFB.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18.4-336791.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

[English](./README_EN.md) | **简体中文**

</div>

---

## 这是什么

一个能联网搜索的对话式 agent，但它真正想展示的不是「会搜索」，而是 **LLM 应用工程**：执行过程可观测、压缩决策可解释、指标可复现、模型接入可替换。

界面只有一个。运行详情就地长在每条回答下方——不是抽屉、不是侧栏、不是「工程师模式」开关。访客只看到一行 `▸ 2 步 · 1.8k tok · 3.1s`，技术读者点开它能一路看到跨度树、工具结果卡片和本次运行用的提示词版本。这条取舍记在 [ADR-0028](./docs/adr/0028-the-chat-surface-is-the-only-console.md)。

> 这个仓库保留了完整 git 历史：它起步时是一个 Streamlit + LangGraph 的 demo，现在是下面描述的样子。「从 demo 演进到工程级」本身就是这份作品集的一部分。

## 三条真实的差异点

大多数 agent 项目都会说自己「支持多模型、有 trace、跑了 evals」。下面三条是这个项目做了而别处基本没做的，每条都指向仓库里可验证的落点。

### 1. 压缩决策全程可观测

上下文膨胀的来源从来不是对话文本，是工具结果正文——一次 `web_reader` 的返回可能是同轮用户消息的几百倍。而这个站点的会话公开共享、任何访客可续聊，**增长没有自然终点**。

处理办法是**观察掩蔽**（[ADR-0019](./docs/adr/0019-old-observations-are-masked-not-summarized.md)）：重建模型输入序列时，只有最近 N 对工具调用/结果保留完整正文，更早的结果换成结构化指代——工具名、入参、来源标题与 URL，不留正文。掩蔽只作用于投影，**消息表原样不动**；工具调用与结果的配对关系不破，因此不制造悬空调用。

不做的是**摘要**。摘要把原文替换成转述，模型据此写出的引用对应不上任何一段真实原文——引用忠实度当场崩掉。

别家的多层压缩对用户是黑的：看不到当前在哪一层、清了什么、省了多少。这里不是：

| 事实 | 落点 |
|---|---|
| 本次运行的保留窗口 | `RunDetail.retention_window` → 运行详情的「本次运行配置」 |
| 累计丢弃了几轮已完成运行 | `RunDetail.pruned_run_count` → 同上 |
| 掩蔽了哪几对观察、留下哪些来源 | `conversation/masking.py` 的 `MaskingProjection.attributes` |

> **如实标注缺口**：整轮削减（`pruned_run_count`）已经打通并在界面上呈现；**单条工具观察的掩蔽标记目前还没有数据源**，运行详情里「模型现在只看到标题与 URL」那行标注尚未出现。见 [#77](https://github.com/EllisYuan/ChatAgents/issues/77)。

### 2. 压缩强度做成评测自变量

保留窗口 N 的首版取值**是拍的，不是算的**。既然是拍的，就得有办法校准它——而校准它需要知道「压得更狠，引用忠实度掉多少、成本省多少」。

所以 N 不是一个写死的常量，是一根**扫描轴**：打一个 release tag 会触发 `ci.yml` 的 `release-eval` job，用 `N ∈ {1, 2, 3, 5, 8}` 的网格各跑一遍同一批数据、同一个判官，产出「压缩强度 × 引用忠实度 × 成本」曲线，经 `GET /api/evals/summary` 落到站点的 `/evals` 页。

公开可复现的这条曲线，业界目前没有第二家给出过。

### 3. token 估算器自校准

全项目只有**一个** token 口径：上游响应报告的输入 token 数（[ADR-0020](./docs/adr/0020-there-is-one-token-yardstick.md)）。

这条措辞是有后果的。它意味着本地估算器的职责**不是「数 token」，是「预测上游会数出多少」**——正确性判据因此是「与上游报告的用量接近」，不是「符合某个 tokenizer 规范」。

为什么不用精确的本地 tokenizer？因为不存在这样的东西：Anthropic 不公开 tokenizer；官方计数端点自己的文档里写着 "The token count is an **estimate**"；同一段文本在相邻两代模型上计数能差三成；而计数端点三个协议里只有一个有。

真值好在它不是近似——它就是账单本身。估算器只承担真值覆盖不到的那部分（本轮新增的增量），**误差被压在增量上，不落在全量上**。

而估算器会自己校准：观测侧每次调用都有实测输入 token 数，按模型分组算「实测 ÷ 估算」就得到该模型的偏差系数——`token_estimation.py` 的 `compute_calibration_factors()`。**校准数据来自这个项目自己的 trace**，零额外网络调用、零 tokenizer 依赖。

一把尺，两处用：`web_reader` 的分节阈值（纯校准后估算，那段文本还没进过任何模型）与保留窗口预算（上一轮真值 + 本轮增量估算）。两处读的是同一把尺，因此可以互相推理。

---

## 架构

### 五个能力模块与它们的依赖方向

后端按**能力**切，不按技术层切（[ADR-0007](./docs/adr/0007-backend-is-split-by-capability-not-by-layer.md)）。判据是可测试性：`api/ + services/ + repositories/` 那种切法会让「业务模块不得依赖观测模块」这条纪律在目录上完全看不见，只能靠 code review 盯；按能力切之后它退化成一条 import 规则。

下图画的是**代码里实际存在的直接 import 边**：

```mermaid
graph TD
    main["main.py<br/>FastAPI 装配 · 三重包装组装处"]

    subgraph caps["五个能力模块"]
        conv["conversation/<br/>会话 · 消息 · 输入序列重建 · 观察掩蔽"]
        agent["agent/<br/>ReAct Loop · 工具执行器 · 提示词与工具集版本"]
        obs["observability/<br/>跨度写入 · trace 查询 · 用量聚合"]
        llm["llm/<br/>端点档案 · ModelPort · 三协议适配器 · 模型发现 · 回放"]
        tools["tools/<br/>web_search · web_reader"]
    end

    subgraph edge["边界与共享叶子"]
        transport["transport/<br/>AG-UI over SSE 编码"]
        evals["eval_summary/<br/>站点评测展示面"]
        db["db/ · database.py<br/>ORM · app 与 obs 两个 schema"]
        leaf["token_estimation.py · validation.py<br/>error_codes.py · exceptions.py · model_catalog.py"]
    end

    main --> conv
    main --> agent
    main --> obs
    main --> llm
    main --> transport
    main --> evals
    main --> db

    conv --> agent
    conv --> llm
    conv --> db
    agent --> llm
    agent --> tools
    agent --> db
    obs --> agent
    obs --> llm
    obs --> db
    transport --> agent
    transport --> llm
    evals --> llm
    db --> llm

    llm --> leaf
    tools --> leaf
    conv --> leaf
    agent --> leaf
    transport --> leaf
```

三条值得单独指出来的性质：

- **`llm/` 不认识 agent / conversation / observability。** 因此三协议契约测试完全独立可跑：不需要数据库，不需要 FastAPI。
- **依赖方向单向，`observability/ → agent/`，反过来没有。** 观测可丢、业务不可丢；一旦业务反向依赖观测，「观测写失败不影响业务」这条纪律就作废了。
- **模块名是 `llm/` 而不是 `models/`。** `models` 在 Python web 生态里约定俗成指 ORM，占用它会让每个新读者误解一次。ORM 因此保住 `<模块>/models.py` 这个通行位置。

模块内四层：`router.py`（HTTP ↔ 领域类型，不含业务）→ `service.py`（规则、编排、事务边界）→ `repository.py`（查询，不含规则、不开事务）→ `models.py`（ORM）。

> 📌 `docs/adr/0007` 里那段依赖方向的文字与当前实现有出入（它写 `agent/ ─→ conversation`，实际方向相反）。上图以代码为准，偏差已单独记录，不在文档变更里顺手改代码或改决策。

### 三重包装

一次运行的事件流从内到外穿过三层，每层职责单一、失败语义各不相同。这段形状逐字取自 `backend/src/chat_agents/main.py`：

```
encode_sse(              # transport/       领域事件 → AG-UI 线格式
  observe(               # observability/   落跨度，独立事务，失败只记日志
    persist(             # conversation/    落消息，业务事务，失败要报错
      runner.run(messages, ...))))
         ▲
         └── agent/  纯 ReAct Loop：不碰数据库、不碰 HTTP、不知道 SSE 存在
```

| 层 | 干什么 | 写失败了怎么办 |
|---|---|---|
| `runner.run` | 跑 ReAct 迭代，吐**领域事件**（不带任何线格式） | 事件化成 `RunFailed` |
| `persist` | 每次模型调用完成即写一条消息，不攒到最后 | **向上抛**——用户的话丢了必须报错 |
| `observe` | 闭合即写跨度，每次写入自己开短事务 | **只记日志**——少一条观测不该拖垮业务 |
| `encode_sse` | 翻成 AG-UI 事件 | 收敛成一条 `RUN_ERROR` 结束流 |

两个不显然但重要的点：

**「观测写失败不影响业务」是结构性成立的，不靠人记住。** 业务写入与观测写入各自 `async with session_factory()`，物理上不可能同事务提交。

**流开始后的失败一律走 `RUN_ERROR` 事件，HTTP 状态码改不了。** 一旦第一个字节发出去，HTTP 已经是 200。`encode_sse` 是这条纪律唯一的执行位置——它包一层 `try/except`，任何从内三层冒出来的异常都在这里收敛，不再向上抛。流**开始前**的失败（档案校验、会话不存在、空消息）才走正常 HTTP 状态码，用 RFC 9457 的 `application/problem+json`。同一个失败在两条路径上取**同一个错误码**（`error_codes.py` 是唯一的码表）。

### 一次运行发生了什么

```mermaid
sequenceDiagram
    participant U as 浏览器
    participant API as main.py
    participant C as conversation/
    participant R as agent/ AgentRunner
    participant M as llm/ ModelPort
    participant T as agent/ ToolExecutor
    participant O as observability/

    U->>API: POST /api/runs
    API->>C: 落用户消息（业务事务）
    C-->>API: 重建模型输入序列（观察掩蔽在此发生）
    API->>R: run(messages, profile, effort)

    loop 每次迭代（受努力档位的硬上限约束）
        R->>M: stream(messages, tools, system_prompt)
        M-->>R: TextDelta / ReasoningDelta / ToolCall
        R-->>U: SSE：STEP_STARTED · TEXT_MESSAGE · REASONING
        opt 模型发起了工具调用
            R->>T: 执行（超时 · 重试 · 错误分类全在这一处）
            T-->>R: ToolStarted / ToolFinished
            R-->>U: SSE：TOOL_CALL · chatagents.tool_result
        end
        R-->>O: 落跨度与用量（独立事务）
        R-->>U: SSE：chatagents.usage · chatagents.span
    end

    R-->>U: SSE：RUN_FINISHED（或 RUN_ERROR）
```

**工具执行器是调用工具的唯一入口。** 超时、重试、错误分类、跨度记录、结果渲染全部集中在那一处，工具本身只是一个干净的异步函数。新加的工具挂进 `tools/registry.py` 就自动获得这一整套横切能力——**结构上不可能漏掉**。

工具失败分两类，这个区分是硬的：**外部失败**（超时、限流、目标不可达、供应商报错）不抛异常，作为工具结果交回模型，由模型决定下一步；**程序错误**（参数校验不过、代码 bug、密钥没配）中止运行并上报，绝不伪装成工具结果喂给模型。

### 两个 schema

业务数据与观测数据同一个 PostgreSQL 实例、两个 schema（[ADR-0002](./docs/adr/0002-business-and-observability-share-a-database.md)）。物理同库保住跨表 join——trace 是这个项目的核心展示物，前端要在聊天界面里直接点开某条消息看它的执行细节；逻辑分 schema 让边界在代码里可见。

```mermaid
erDiagram
    SESSION ||--o{ MESSAGE : "app 内"
    SESSION ||--o{ RUN : "obs 指向 app"
    MESSAGE ||--o{ RUN : "trigger_message_id"
    PROMPT_VERSIONS ||--o{ RUN : "obs 指向 app"
    TOOL_SCHEMA_VERSIONS ||--o{ RUN : "obs 指向 app"
    RUN ||--o{ SPAN : "obs 内"
    SPAN ||--o{ SPAN : "parent_span_id"

    SESSION {
        uuid id PK "前端生成 UUIDv7"
        text title "可空：由辅助模型生成"
        timestamp deleted_at "软删除标记"
    }
    MESSAGE {
        uuid id PK
        int seq "会话内单调递增"
        text role
        jsonb content "完整的模型视角序列"
    }
    PROMPT_VERSIONS {
        text version_id PK "内容哈希，非人手递增"
    }
    TOOL_SCHEMA_VERSIONS {
        text version_id PK "粒度是工具集，不是单个工具"
    }
    RUN {
        uuid id PK
        uuid trigger_message_id FK "消息区间的下界"
        int last_message_seq "消息区间的上界"
        jsonb attributes "保留窗口 · 削减计数"
    }
    SPAN {
        uuid id PK
        text kind "llm 或 tool"
        text usage_status "complete / partial / unavailable"
        int input_tokens "真值：上游报告的口径"
    }
```

**外键只能 `obs` → `app`，单向。** 这条约束有个不显然的后果：**消息表上不能有 `run_id`**。「这条消息属于哪次运行」只能从观测侧圈定——靠 `trigger_message_id` 加 `last_message_seq` 反查（一次运行产出的消息在会话里必然连续）。

三条相关的建模纪律：

- **没有成本字段。** 成本是可推算量（随价格配置变化），不是观测事实，与 token 数分开存放。
- **缺失的用量不以 0 表示。** 用量三态 `complete` / `partial` / `unavailable`，三者之外没有第四种状态。
- **会话删除是软删除。** 站点无鉴权、会话列表公开共享，硬删除要么级联把 trace 一起销毁（核心展示物被路人一键抹掉），要么留下一堆孤儿跨度。

### 模型接入：三协议并列，互不翻译

`llm/` 对项目其余部分零业务依赖，`ModelPort` 是它对外的唯一出入口：

```
                   ┌─ openai_responses         ─┐
ModelPort.stream ──┼─ openai_chat_completions  ─┼──→ 统一的 ModelEvent 流
                   └─ anthropic_messages       ─┘
```

几条设计取舍：

- **协议是端点档案的属性，不是模型的属性。** `ModelPort` 签名上不接受「厂商」参数，没有从模型标识推断协议的余地。同一个 base URL 可以配多份档案，各自声明不同协议。
- **模型清单运行时发现，前后端都不硬编码**（[ADR-0016](./docs/adr/0016-the-model-list-is-discovered-and-persisted.md)）。清单**不保证可用**——里面的标识仍可能因欠费、凭证冷却、上游下线而调不通。发现失败是提示性的，不是中断性的：服务照常跑，界面改为让用户手填。
- **上游错误原文透传，不分类。** 不建立错误码映射表，上游说什么就是什么——那不是这个项目的话。
- **回放发生在 `ModelPort` 边界，不在 HTTP 传输层**（[ADR-0025](./docs/adr/0025-replay-happens-at-the-model-port-not-the-http-transport.md)）。录下来的是适配器已经产出的 `ModelEvent`，不含 HTTP 帧、chunk 时序或鉴权信息——因此回放层对「上游 SDK 换了哪个 HTTP 客户端库」完全免疫。这不是理论上的洁癖：`openai` 3.x 已经切到 `httpx2`，而 `anthropic` 仍在 `httpx`，一个进程里两个库并存是预期状态。

### 工具：能力与实现分开

只有两个工具，且**锁死**：

| 工具 | 干什么 | 当前供应商 |
|---|---|---|
| `web_search` | 搜索相关网页 | Tavily |
| `web_reader` | 读取网页与 PDF 正文 | Jina Reader |

**工具的身份是「名字 + 描述 + 入参 schema」三件事，属于契约；身份不随背后由谁实际执行而改变**（[ADR-0004](./docs/adr/0004-tools-are-capabilities-providers-are-implementations.md)）。换掉 Tavily 不改变 `web_search` 是什么。每个工具内部切成三层：契约（`contract.py`）、端口（`port.py`，唯一碰网络的地方）、编排（`orchestration.py`，纯函数）。

长文档不整篇塞进上下文：`web_reader` 先返回文档结构（标题与章节清单），由模型按需索取具体章节（**渐进披露**，[ADR-0005](./docs/adr/0005-long-documents-use-progressive-disclosure.md)）。只做一级，不做多级路由，不做 RAG。

### 执行控制：努力档位

用户为每次运行选一个档位，它同时决定**硬上限**（执行层强制的天花板，模型越不过）与**软预算**（写进系统提示词、告知模型的额度）。软预算低于硬上限，留出余量，使越限成为异常而非常态。

| 档位 | 软预算 | 硬上限 |
|---|---|---|
| `low` | 3 | 4 |
| `medium` | 6 | 8 |
| `high` | 10 | 13 |
| `xhigh` | 16 | 20 |

保留窗口**与努力档位正交**，不随档位变化——N 的最优值由引用忠实度决定，档位由任务复杂度决定，两者不是同一个自变量；耦合之后评测也没法单独扫这一维。

---

## 快速开始

### 环境要求

- **Python** 3.11–3.12，装 [uv](https://docs.astral.sh/uv/)
- **Node** 22（前端）
- **Docker** 与 docker compose 插件（跑本地 PostgreSQL）
- **API 密钥**：[Anthropic](https://console.anthropic.com/) 或 [OpenAI](https://platform.openai.com/)（至少一个）、[Tavily](https://tavily.com/)；Jina Reader 可选（不填也能用，只是配额低）

### 1. 装依赖

```bash
git clone https://github.com/EllisYuan/ChatAgents.git
cd ChatAgents
uv sync --project backend
npm --prefix frontend ci
```

### 2. 起数据库

**首次跑测试之前必须先起本地 PostgreSQL**——集成测试打真库，没有内存库替身：

```bash
docker compose up -d postgresql
```

> ⚠️ compose service 的名字是 **`postgresql`**，不是 `postgres`。

本地默认值（都可以用同名环境变量覆盖）：

| 项 | 默认值 |
|---|---|
| Compose service | `postgresql` |
| 容器名 | `chatagent-postgresql` |
| 数据库 | `chat_agents` |
| 用户 | `root` |
| 密码 | `Agent@Dev_1` |
| 监听 | `127.0.0.1:5432` |
| 数据卷 | `chatagent_postgres-data` |

密码写进连接 URL 时，`@` 必须编码成 `%40`：

```text
postgresql+psycopg://root:Agent%40Dev_1@127.0.0.1:5432/chat_agents
```

compose 起 backend 时会先跑 `migrate` service；单独初始化数据库：

```bash
docker compose run --rm migrate
```

### 3. 配环境变量

```bash
cp .env.sample .env
```

### 4. 起服务

```bash
# 终端 1：后端
uv run --project backend python -m uvicorn chat_agents.main:app --app-dir backend/src --reload

# 终端 2：前端
npm --prefix frontend run dev
```

| 入口 | 地址 |
|---|---|
| 前端 | http://localhost:5173 |
| 后端（本地直起） | http://localhost:8080 |
| 后端（容器映射） | http://127.0.0.1:19180 |
| OpenAPI 文档 | `<后端地址>/docs` |

用 compose 起数据库和后端（前端仍在宿主上跑 dev server）：

```bash
docker compose up -d --build
VITE_BACKEND_ORIGIN=http://127.0.0.1:19180 npm --prefix frontend run dev
```

## 配置

### 环境变量

| 变量 | 说明 | 必需 |
|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic 密钥，对应 `anthropic-official` 档案 | 至少配一个 |
| `OPENAI_API_KEY` | OpenAI 密钥，对应 `openai-official` 档案 | 至少配一个 |
| `TAVILY_API_KEY` | `web_search` 用 | ✅ |
| `JINA_API_KEY` | `web_reader` 用；不填也能跑，只是配额低 | ❌ |
| `DATABASE_URL` | 完整连接串；compose 会用 `POSTGRES_*` 拼出来 | ❌ |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | compose 用 | ❌ |
| `POSTGRES_PASSWORD_URLENCODED` | 同上，但 `@` 要写成 `%40` | ❌ |
| `CHATAGENTS_ENDPOINTS_CONFIG_PATH` | 端点档案 YAML 的位置 | ❌ |
| `CHATAGENTS_EVAL_REPORTS_DIR` | 评测产出目录，默认 `.eval-reports/` | ❌ |
| `APP_VERSION` | 构建时注入的 git tag；本地为 `dev` | ❌ |
| `VITE_BACKEND_ORIGIN` | 前端 dev server 代理到哪个后端 | ❌ |

### 端点档案

档案定义在 `backend/config/endpoints.yaml`，**只存密钥的环境变量名，不存密钥本身**。这份文件是应用配置，随仓库走、烘进镜像（[ADR-0032](./docs/adr/0032-app-config-lives-in-the-repo-machine-config-does-not.md)）：

```yaml
default_profile: anthropic-official

endpoints:
  - name: anthropic-official
    protocol: anthropic_messages
    base_url: https://api.anthropic.com
    auth_field: x-api-key
    auth_secret_ref: ANTHROPIC_API_KEY
    main_model: claude-sonnet-4-5-20250929
```

`base_url` 可以指向任意中转站——「支持自定义 base URL」是硬需求，不是附赠功能。`auth_field` 可配，因为不同中转站期待的 header 名不一样。

### 版本号

**版本号只由 git tag 决定**，`backend/pyproject.toml` 里的 `version` 永久钉死 `0.0.0`（[ADR-0030](./docs/adr/0030-the-git-tag-is-the-only-version.md)）。构建时 `ARG APP_VERSION` 把 tag 打进镜像，后端经 `/health` 暴露，前端经 Vite 的 `define` 进 `import.meta.env`。

> 看到 `pyproject.toml` 写着 `0.0.0` 而线上 `/health` 返回 `v1.4.2` 时，第一反应通常是「这里漏改了」。**`0.0.0` 是故意的**——`uv_build` 不支持 VCS 驱动的包版本，让它保持一个显然无意义的值，好过让它保持一个看起来有意义、实际会撒谎的值。

---

## 部署

### 链路

```
                    ┌───────────────────────────────────────────────┐
                    │  宿主 nginx（宝塔面板管 TLS 与证书续期）      │
浏览器 ── HTTPS ──▶ │                                               │
                    │  location /      root .../frontend/current    │──▶ 直接读磁盘
                    │                  try_files → index.html       │    （前端不进容器）
                    │                                               │
                    │  location /api/  proxy_pass 127.0.0.1:19180   │──┐
                    │                  proxy_buffering off          │  │
                    └───────────────────────────────────────────────┘  │
                                                                       ▼
                                          ┌──────────────────────────────────┐
                                          │  backend 容器（ghcr.io 镜像）    │
                                          │  uvicorn :8080                   │
                                          └──────────────┬───────────────────┘
                                                         │ backend-network
                                          ┌──────────────▼───────────────────┐
                                          │  postgresql 容器（postgres:18.4）│
                                          │  app schema + obs schema         │
                                          └──────────────────────────────────┘
```

### ⚠️ 在宝塔面板里改 nginx 会被下一次部署覆盖

`deploy/nginx/site.conf` 随 `git checkout <tag>` 换版，面板里的手改内容**不会被保留**——下一次部署的 `git checkout` 会把它还原。

判据是「这是机器的属性还是应用的属性」（[ADR-0032](./docs/adr/0032-app-config-lives-in-the-repo-machine-config-does-not.md)）：

| 归宝塔面板 | 归仓库 `deploy/nginx/site.conf` |
|---|---|
| TLS 参数、证书路径、证书续期、监听端口 | `location` 路由、`proxy_buffering off`、超时、静态资源的 `root` 与 `try_files` |

**换一台服务器还成立的，是应用的属性——改仓库里那份，再发布。**

### SSE 只能穿一层 nginx（结构性要求）

`X-Accel-Buffering` 属于 `X-Accel-*` 一族，**只在离用户最近的那一层生效——被第一层吃掉就不会向下传**。如果 `/api/` 串了两层 nginx（比如又经过一层容器内的），就必然有一层照常缓冲。

**而且失效是静默的**：流式响应不报错，只是攒一坨再吐。本地单层环境永远复现不出来。

解法不是「两层都配 `proxy_buffering off`」，而是让 `/api/` **只穿一层**——宿主 nginx 直连后端，静态资源走另一条 `location`。**这是前端不进容器的理由之一。**

### 一次性服务器准备（人做，CD 做不了）

1. 建站 `agent.ellisyuan.com`、申请证书（宝塔面板）
2. `git clone` 到 `/www/chatagents/repo`
3. 在 clone 目录**之外**写 `/www/chatagents/.env`，`chmod 600`——CD 只读它，**绝不写它**
4. 宝塔站点配置里加一行：
   ```nginx
   include /www/chatagents/repo/deploy/nginx/site.conf;
   ```
5. 配 GitHub Actions 的 SSH 部署密钥与服务器 IP 白名单

### 发布与回滚

打一个 `v*` tag 触发 `release.yml`：构建后端镜像推 ghcr.io → 构建前端产物 → 发 GitHub Release → SSH 到服务器跑 `deploy.sh`。

**回滚就是换一个旧 tag 重跑同一个脚本**：

```bash
./scripts/deploy.sh v1.4.2
```

不依赖 CI 是否可用。一个 tag 出厂的东西——后端镜像、前端静态产物、compose 与 nginx 配置——**同进同退**，不做兼容矩阵：不存在「后端 v1.4 配前端 v1.3」这种组合。

### 部署后必做：`curl -N` 实测

这是「SSE 被静默攒批」**唯一的检出手段**，且不归 CI（CI 环境里没有真实 nginx）：

```bash
curl -N https://agent.ellisyuan.com/api/runs -X POST \
  -H "Content-Type: application/json" \
  -d '{"session_id":"...", "message":"你好"}'
# 应逐条打印事件，而不是卡住不动然后一次性吐出一大坨
```

同时验证另外两件事：

```bash
curl https://agent.ellisyuan.com/health
# {"status":"ok","version":"v1.4.2"}——版本号来自当次部署的 git tag

curl -I https://agent.ellisyuan.com/s/00000000-0000-0000-0000-000000000000
# 刷新前端路由不该 404——依赖 site.conf 里的 try_files
```

---

## 测试与门禁

**测试与评测是两个系统**（[ADR-0026](./docs/adr/0026-tests-and-evals-are-two-systems.md)）。前者确定性、是门禁；后者非确定性、花钱、只给警告。

### 提交前本地自检

```bash ci-command
uv sync --project backend --locked
uv run --project backend pytest backend/tests
uv run --project backend pytest backend/tests/contract_test.py -m contract --maxfail=1
uv run --project backend ruff check --config=backend/pyproject.toml backend
uv run --project backend ruff format --check --config=backend/pyproject.toml backend
uv run --project backend mypy --config-file=backend/pyproject.toml backend
```

前端（在 `frontend/` 下执行）：

```bash ci-command
npm ci
npm run lint
npm run typecheck
npm run build
```

> 上面两块打了 `ci-command` 标记，`scripts/check-readme-ci-commands.sh` 会断言它们**逐字**出现在 `.github/workflows/ci.yml` 里。**CI 是权威**——文档漂移会让这条检查变红。

### 门禁与警告

| 检查 | 阻断合并 | 说明 |
|---|---|---|
| Ruff · mypy · 后端测试 | ✅ | 打真 PostgreSQL，不用内存库 |
| REST 契约测试 | ✅ | 进程内直打 FastAPI，确定性 |
| 前端 lint · tsc · build | ✅ | 前端的门禁就是这三条 |
| README 命令一致性 | ✅ | 就是上面那个断言 |
| 提示词 / 工具集变更评测 | ⚠️ 警告 | 只在模型输入真的变了时才跑 |
| 上游契约测试 | ⚠️ 不进 CI | 打真实网络，非确定性 |

区别不在重要性，**在信号是否确定：会抖的信号不做门禁**。

### 回放：零网络零数据库

用录好的运行事件序列驱动一次完整运行。录制物取自 `ModelPort` 边界，不是 HTTP 响应——因此它与上游 SDK 用哪个 HTTP 客户端库无关。

### 评测

七个指标，五个零成本确定性 + 两个判官模型打分：

| 指标 | 怎么算 |
|---|---|
| 引用忠实度 | 回答引用的来源 ∩ 模型实际观察到的来源，除以回答引用的来源 |
| 工具触发率 | 该联网时联了、不该联网时没闲置联网的比例 |
| 轨迹效率 | 硬上限触达率 · 重复读同一 URL · 搜完不读就作答，三个子信号的均值 |
| 参数合规率 | 工具调用入参过当次工具 JSON Schema 的比例 |
| 系统约束遵从度 | 实际迭代数对软预算的遵从 |
| 事实幻觉率 | 判官模型打分 |
| 任务完成度 | 判官模型打分 |

**没有「工具误选率」**——两个语义正交的工具下，误选率恒为常数，没有区分度。

评测在 PR 上**只在模型输入真的变了时**才触发：`eval-trigger` job 比较当前 checkout 与 base revision 的提示词 / 工具集内容哈希，按内容判断而非按文件路径，所以变量拼装逻辑的改动也会触发。触发后新旧两版**在同一次 CI 里用同一批数据、同一判官各跑一遍**，不读历史分数当基线——换了判官历史分数就不可比，所以每条结果都带**判官快照**。

```bash
# 默认不跑评测
uv run --project backend pytest backend/tests

# 显式跑
uv run --project backend pytest -m eval backend/tests/evals
```

工具供应商在评测里被**冻结的夹具**替换（Tavily 与 Jina 两个 Port），但 `ModelPort` 不替换——**被评测的模型保持在线**，否则测的就不是模型了。

---

## 目录结构

```
ChatAgents/
├── backend/
│   ├── src/chat_agents/
│   │   ├── main.py              # FastAPI 装配 · 三重包装唯一组装处
│   │   ├── conversation/        # 会话 · 消息 · 输入序列重建 · 观察掩蔽
│   │   ├── agent/               # ReAct Loop · 工具执行器 · 版本化
│   │   ├── llm/                 # ModelPort · 三协议适配器 · 发现 · 回放
│   │   ├── tools/               # web_search · web_reader
│   │   ├── observability/       # 跨度写入 · trace 查询 · 用量聚合
│   │   ├── transport/           # AG-UI over SSE 编码
│   │   ├── eval_summary/        # 站点评测展示面
│   │   ├── db/                  # ORM：app 与 obs 两个 schema
│   │   └── token_estimation.py  # 全项目唯一的 token 估算器
│   ├── alembic/                 # 迁移（只增不改）
│   ├── config/endpoints.yaml    # 端点档案
│   └── tests/
│       ├── evals/               # 评测（marker 隔离，不随默认测试跑）
│       └── integration/         # 打真 PostgreSQL
├── frontend/                    # React 19 + Vite + TanStack Query + Zustand
│   └── src/features/            # session · sessions · trace · evals
├── deploy/nginx/site.conf       # 应用属性那半份 nginx 配置
├── docs/adr/                    # 33 份架构决策记录
├── scripts/deploy.sh            # 发布 / 回滚
├── compose.yaml                 # 本地
├── compose.prod.yaml            # 线上叠加（换成 ghcr.io 镜像）
└── CONTEXT.md                   # 术语表：只定义术语是什么
```

## 契约

前后端之间的接口形状由**两个来源**共同构成，两者之外没有第三处（[ADR-0021](./docs/adr/0021-the-contract-has-two-sources.md)）：

- **流式事件的信封**来自 AG-UI 的 schema（版本锁定的 `@ag-ui/core`）
- **非流式 REST 面与本项目自有的事件载荷**来自后端代码生成的 OpenAPI 文档

前端类型由 `openapi-typescript` 从后端导出的 schema 生成，**不提交类型副本**——任何手写的类型副本都不是契约，是它的复制品。

主要端点：

| 端点 | 说明 |
|---|---|
| `POST /api/runs` | 发起一次运行，返回 AG-UI over SSE 流 |
| `GET /api/sessions` | 会话列表（复合游标分页） |
| `GET /api/sessions/{session_id}/messages` | 会话消息 |
| `GET /api/sessions/{session_id}/runs` | 该会话的运行列表，供客户端与消息序列合并 |
| `GET /api/runs/{run_id}` | 运行详情：跨度树 · 用量汇总 · 运行配置 |
| `GET /api/models` · `POST /api/models/refresh` | 模型清单与刷新 |
| `GET /api/evals/summary` | 站点评测展示面的四个数字 |
| `GET /health` | 版本号的唯一出口 |

**URL 里没有版本号**（[ADR-0024](./docs/adr/0024-there-is-no-url-versioning.md)）——前后端同一个 tag 出厂、同进同退，给一个不会独立演进的东西加版本号只是仪式。

---

## 故障排查

### 刷新 `/s/<uuid>` 返回 404

`try_files` 没生效——要么宝塔站点配置漏了那行 `include`，要么 `root` 指向的目录不是当前发布版本。

```bash
nginx -T | grep -A3 "location /"
readlink -f /www/chatagents/frontend/current
```

### 流式回复攒一坨才吐出来

`/api/` 串了不止一层 nginx，或某一层缺了 `proxy_buffering off`。见上文「SSE 只能穿一层 nginx」——用 `curl -N` 实测确认逐条到达。

### `/api/` 返回 404

`proxy_pass` 末尾多了一条斜杠，把 `/api/` 前缀截断了：

```nginx
proxy_pass http://127.0.0.1:19180/;  # ❌ 末尾斜杠 → 路径被截断
proxy_pass http://127.0.0.1:19180;   # ✓ 保留完整路径
```

### 集成测试连不上数据库

先确认 `docker compose up -d postgresql` 起来了，且连接串里的 `@` 编码成了 `%40`。

### 会话列表拿不到第二页

游标是 `(before_updated_at, before_id)` **复合**的：第一页两项都省略，后续页**必须同时传**。query 参数没有 JSON `null` 的表达，客户端应当**省略**空值，不要发 `before_id=null`。

### 会话历史丢了

`compose.yaml` 用 named volume 持久化，正常重启不要带 `-v`：

```bash
docker compose down          # ✓
docker compose down -v       # ❌ 永久删除 chatagent_postgres-data
```

备份：

```bash
docker compose exec postgresql pg_dump -U root -d chat_agents > chat_agents.sql
```

### 看日志

```bash
docker compose logs backend --tail 100 -f
docker compose logs postgresql --tail 100 -f
```

> 流式路径的日志量是**每次运行 0~1 条**，不是每个 token 一条；而且**日志里不写模型输出的文本内容**。「一次运行内部发生了什么」归跨度，日志只记跨运行的系统事件。要看某次运行干了什么，去 trace，不要去日志。

---

## 文档

| 文件 | 内容 |
|---|---|
| [`CONTEXT.md`](./CONTEXT.md) | 术语表——只定义术语**是什么**，不记录实现方式 |
| [`docs/adr/`](./docs/adr/) | 33 份架构决策记录，含被否决方案与理由 |
| [`docs/research/`](./docs/research/) | 选型阶段的调研报告 |
| [`frontend/src/features/trace/SPEC.md`](./frontend/src/features/trace/SPEC.md) | 跨度树的客户端合并规则 |

几份值得先读的 ADR：

- [ADR-0001](./docs/adr/0001-messages-are-the-single-source-of-truth.md) 消息是唯一事实来源
- [ADR-0007](./docs/adr/0007-backend-is-split-by-capability-not-by-layer.md) 后端按能力切，不按技术层切
- [ADR-0019](./docs/adr/0019-old-observations-are-masked-not-summarized.md) 历史观察被掩蔽，不被摘要也不被丢弃
- [ADR-0020](./docs/adr/0020-there-is-one-token-yardstick.md) token 只有一个口径
- [ADR-0028](./docs/adr/0028-the-chat-surface-is-the-only-console.md) 聊天界面是唯一的控制台

## 贡献

1. Fork 并建分支
2. **先起数据库**：`docker compose up -d postgresql`
3. 跑一遍上面的自检块
4. 提 PR

代码注释与 ADR 用中文，代码标识符与 commit message 用英文，README 中英双语。

## 许可证

[MIT](./LICENSE)

## 作者

**Yuan** — [GitHub @EllisYuan](https://github.com/EllisYuan) · [yuan.sn@outlook.com](mailto:yuan.sn@outlook.com)

## 致谢

[FastAPI](https://fastapi.tiangolo.com/) · [AG-UI](https://github.com/ag-ui-protocol/ag-ui) · [SQLAlchemy](https://www.sqlalchemy.org/) · [React](https://react.dev/) · [Vite](https://vite.dev/) · [Anthropic](https://www.anthropic.com/) · [OpenAI](https://openai.com/) · [Tavily](https://tavily.com/) · [Jina Reader](https://jina.ai/reader/)
