# 模型接入层选型：自定义 Base URL + OpenAI/Anthropic 双格式

> 对应 issue：[#2](https://github.com/EllisYuan/ChatAgents/issues/2)，上位约束见 [#1](https://github.com/EllisYuan/ChatAgents/issues/1)  
> 调研基准日期：**2026-08-06**  
> 结论对象：模型调用与协议适配边界；不替代后续 agent 框架、路由策略、可观测性产品或部署网关的独立选型。

## 一、结论摘要

### 明确推荐

采用 **“项目自有的协议感知双 client 适配层”** 作为长期模型接入边界：

- OpenAI Chat Completions 格式由官方 `AsyncOpenAI` client 驱动；
- Anthropic Messages 格式由官方 `AsyncAnthropic` client 驱动；
- 上层只依赖项目自定义的 `ModelPort`、规范化事件和 usage/error 类型；
- `protocol`、`base_url`、`model`、认证与 capability 必须分别配置，不能再用 `provider=claude/openai` 同时表达厂商和协议；
- **不在模型接入层内部把两种协议互相翻译**。只规范化上层真正需要的稳定语义，并保留原始响应元数据；
- LiteLLM Proxy 或 Bifrost 可在未来作为**可选部署网关**接到同一接口后面，但不是代码的唯一正确性边界，也不应成为 ReAct runtime 的类型依赖。

这是对本 issue 三条硬需求最稳妥的回答：官方 clients 都支持自定义 `base_url`、SSE、工具调用、usage 和显式 retry/timeout 配置；两种协议各自的工具、流事件和 usage 语义又确实不同，保留双原生适配比“统一成一种看似通用的格式”更不容易损失信息。[S3][S4][S8][S9]

### 关键判断

1. **“支持 OpenAI/Anthropic 厂商”不等于“接受 OpenAI/Anthropic 两种 HTTP 格式”。** One API 能把 Anthropic 当上游，却只暴露 OpenAI 风格主要路由；反过来，Anthropic 官方虽提供 OpenAI SDK compatibility，也明确说它主要用于测试比较，并非多数生产场景的长期方案，而且会忽略或改写部分字段。[S12][S27]
2. **“OpenAI 格式”是两种协议，MVP 就要同时支持，并以 Responses API 为优先。** OpenAI 同时提供 `/v1/responses` 与 `/v1/chat/completions`，二者是**不同的数据模型、工具循环与流事件协议**，不能暗中合并——但也**不应把 Responses 推迟为「日后预留」**。Responses 是 OpenAI 当前推荐的新项目接口 [S6]，本项目应**优先按 Responses 建模**，Chat Completions 作为面向存量中转站的兼容协议并列实现。因此接入层的协议枚举从一开始就是三项（`openai_responses` / `openai_chat_completions` / `anthropic_messages`），`protocol` 字段必须能精确表达是哪一种，而不是含义不明的 `provider=openai`。

   > **勘误说明**：本条原文曾写作「MVP 中明确为 Chat Completions……架构应预留 `openai_responses` 适配器」，把 Responses 降级为后续项。经用户指正，该判断有误——OpenAI 格式本就可调用两种协议，且应优先考虑新版本。已按此重写，第二章「本次协议范围」、第八章路线图与第十章建议中的相应表述一并修正。
3. 流式 usage 不能只设计成一个整数三元组：OpenAI Chat 的完整 usage 通常在 `[DONE]` 前的额外 final chunk 中，流中断时可能收不到；Anthropic 的输入 usage 出现在 `message_start`，输出 usage 在 `message_delta` 中累计，且 HTTP 200 后仍可能出现 SSE `error`。因此必须记录 `complete/partial/unavailable`，不能把缺失值当 0。[S4][S9][S13]
4. 并行工具调用需要分成两个概念：**模型一次返回多个调用**与**应用是否并发执行这些调用**。OpenAI 用顶层 `parallel_tool_calls`；Anthropic 可在一个 assistant turn 中返回多个 `tool_use` block，并通过 `tool_choice.disable_parallel_tool_use` 控制是否允许多个调用；真正并发还是顺序执行应归 Tool Executor，而不是模型 client。[S5][S11]
5. LangChain 现有适配器适合作为迁移期 bridge，不适合作为长期领域边界。当前代码直接依赖 `BaseChatModel` 和已在 LangGraph v1 中弃用的 `create_react_agent`，若继续把 model access 暴露为 LangChain 类型，未来换 agent 框架仍需重写这一层。[S14][S15][S16]
6. **密钥来源分两层，用户优先、未填则降级到服务端预设。** 服务端环境变量预设让 demo 开箱即用（用户无感知）；前端「高级选项」允许访客填入自己的 `base_url` / `protocol` / `auth_field` / key。**用户填了就用用户的，没填才用服务端的**；用户 key 调用失败时**如实报错，不静默 fallback 到服务端 key**，否则成本归属会失真。两层共用同一个 `EndpointProfile` 结构，适配层不需要知道这次用的是谁的 key。详见第十二章。
7. **模型清单必须运行时发现，不得前后端各硬编码一份。** 现状 `llm_config.py:27-48` 与 `frontend/src` 各存一份清单且无同步机制——这正是无效型号 ID 能长期潜伏的原因（`.get(model, 默认值)` 会静默回退）。改为后端按 protocol 调用模型列表接口发现、下发给前端；发现失败回退静态兜底并标记 `source=fallback`；用户指定的无效 model ID **显式报错而非静默替换**。详见 12.8。
8. **模型角色分离：主模型与 tool 模型各自独立可配。** 现状 `backend/src/chat_agents/main.py:163-172` 把工具摘要模型硬编码为 Claude Haiku——用户主模型选 OpenAI 时仍会去调 Anthropic，既可能直接失败，也会让用户自带 key 的场景意外消耗项目方额度。规则：**tool 模型默认跟随主模型**（保证零配置时无跨厂商意外调用），用户可在高级选项独立覆盖，甚至指向完全不同的 endpoint profile。trace 须按角色区分用量。详见 12.9。
9. 统一网关不是不能用，而是不应默认承担协议正确性。LiteLLM、Bifrost、New API 都能提供双格式入口或跨格式转换，但跨 provider 的 tools、并行控制、usage、错误与流中途失败仍存在文档空白或已能从源码看到的转换缺口，必须逐 endpoint 原型认证。[S22][S23][S25][S26]

### 决策句

> **长期边界选“官方 OpenAI/Anthropic 异步 client + 项目自有双协议适配器”；LangChain 只保留为迁移 shim；网关只作为可插拔基础设施，不作为协议语义的唯一来源。**

---

## 二、先把“厂商”与“协议”拆开

| 概念 | 本报告定义 | 示例 |
|---|---|---|
| 上游厂商 / provider | 最终提供推理能力或托管模型的实体 | OpenAI、Anthropic、Azure、Bedrock、OpenRouter、某中转站 |
| HTTP 协议 / wire protocol | 客户端实际发送和接收的路径、JSON 与 SSE 事件格式 | OpenAI Chat Completions、OpenAI Responses、Anthropic Messages |
| endpoint profile | 本项目可调用的一个具体连接配置 | `protocol=anthropic_messages` + `base_url=https://proxy.example.com` + `model=claude-*` |
| model alias | 本项目展示给 UI 或路由器的逻辑名称 | `reasoning-primary`、`fast-summary` |

同一个 Claude 模型可能通过两种完全不同的格式暴露：

```yaml
# 中转站 A：Claude 模型，但使用 OpenAI Chat Completions 格式
protocol: openai_chat_completions
base_url: https://relay-a.example.com/v1
model: claude-sonnet-x

# 中转站 B：同类模型，使用 Anthropic Messages 格式
protocol: anthropic_messages
base_url: https://relay-b.example.com
model: claude-sonnet-x
```

反之，“支持 Anthropic provider”也可能只是网关把 Anthropic 当下游，然后只向调用方暴露 `/v1/chat/completions`。这不满足 issue #2 的“双格式入口”要求。

### 本次协议范围

**三种协议都必须支持，各自独立建模，互不翻译**：

| 协议枚举值 | endpoint | 定位 | 优先级 |
|---|---|---|---|
| `openai_responses` | `POST /v1/responses` | OpenAI 当前推荐的新项目接口 [S6] | **优先实现** |
| `openai_chat_completions` | `POST /v1/chat/completions` | 存量兼容面：绝大多数中转站的 “OpenAI-compatible” 指的是这一个 | 并列实现 |
| `anthropic_messages` | `POST /v1/messages` | Anthropic 原生格式 | 并列实现 |

**为什么 Responses 优先而非推迟**：OpenAI 已将 Responses 定位为新项目推荐接口 [S6]，其工具循环与状态管理模型也更贴合 agent 场景。若先只做 Chat Completions、把 Responses 留作「日后适配器」，等于让新代码一出生就建立在被官方标记为存量的协议上，日后迁移要动整条事件通路。反之，Chat Completions 也不能省——它是中转站生态的事实兼容面，砍掉它等于放弃自定义 base URL 这条硬需求的大半场景。

**结论**：`protocol` 从第一天起就是三值枚举，不是布尔。三个 adapter 各自实现，共享 `ModelPort` 出口契约，内部不互相翻译。

---

## 三、当前代码现状与问题

| 位置 | 当前事实 | 对选型的影响 |
|---|---|---|
| `backend/src/chat_agents/llm/14-19` | `LLMProvider` 只有 `claude/openai/groq`，表达的是厂商名 | 无法表达“Claude 模型走 OpenAI 格式”或“非 Anthropic 模型走 Messages 格式” |
| `backend/src/chat_agents/llm/51-120` | `ChatAnthropic`、`ChatOpenAI` 工厂没有 `base_url`、headers、timeout、retry、capability 参数 | 不满足自定义中转；也无法显式管理重试所有权与 beta/version header |
| `backend/src/chat_agents/llm/27-48` | 模型列表硬编码在 Python 字典中 | endpoint、协议与模型生命周期被绑死在业务代码；别名和真实 model ID 容易漂移 |
| `backend/src/chat_agents/main.py:129-169` | 主模型按 provider 分支创建；摘要模型始终优先创建 Claude | 只配置 OpenAI 格式 endpoint 时，摘要路径仍会尝试 Anthropic；双格式支持并不贯穿整条调用链 |
| `backend/src/chat_agents/main.py:217-325` | 只消费 LangGraph 文本 callback；没有收集 provider usage、request ID、finish reason 或 TTFT | 当前即使底层 SDK 返回 usage，也没有稳定通道交给可观测性层 |
| `backend/src/chat_agents/main.py:211-214, 435-445` | `tool_calls_list` 被初始化但没有写入 | 会话记录无法可靠还原工具调用，后续 trace/eval 也缺少原始事实 |
| `backend/src/chat_agents/agent/3,108-225` | graph 接口直接接收 `BaseChatModel`，并调用 `langgraph.prebuilt.create_react_agent` | 模型层与 LangChain/LangGraph 类型耦合；当前 API 又已进入弃用迁移路径 [S16] |
| `requirements.txt:9-19` | 使用 LangChain 0.3 / LangGraph 0.4 代际依赖；`langchain-anthropic>=0.1.0` 还未给上界或精确版本 | 不能把旧版本行为当作 2026 当前能力；后续应通过 contract tests 锁定实际版本组合 |

本票不修改业务代码，但这些现状决定了推荐方案不能只是在现有工厂函数上补一个 `base_url` 参数：还必须把“协议、endpoint、事件、usage、错误”的边界从 agent 框架类型中抽出来。

---

## 四、已核实的两种协议行为

### 4.1 官方 clients 与自定义 Base URL

| 项目 | OpenAI Python SDK | Anthropic Python SDK |
|---|---|---|
| 自定义 endpoint | `OpenAI/AsyncOpenAI(base_url=...)` 或 `OPENAI_BASE_URL` | `Anthropic/AsyncAnthropic(base_url=...)` 或 `ANTHROPIC_BASE_URL` |
| HTTP 代理 | 可注入 `DefaultHttpxClient` / async client 并设置 proxy、transport | 可注入 `DefaultHttpxClient` / async client；也可换 aiohttp backend |
| timeout | 可配置；当前文档默认 10 分钟 | 可配置；当前文档默认 10 分钟 |
| 默认自动重试 | 2 次 | 2 次 |
| 默认重试范围 | 连接错误、408、409、429、5xx | 连接错误、408、409、429、5xx |
| 请求标识 | 成功响应 `_request_id`，失败 `APIStatusError.request_id` | 成功响应 `_request_id`；错误 body/header 也带 request ID |

两套 SDK 都能直连任意声称兼容相应协议的中转站；这意味着“自定义 base URL”本身并不需要再引入统一网关。[S3][S8]

但 SDK 类型正确不代表中转站正确。中转可能遗漏事件、返回非标准字段、拒绝某些 headers，或者只实现协议子集，所以仍需要 endpoint certification，而不能只做一次普通文本请求。

### 4.2 流式与 usage

| 维度 | OpenAI Chat Completions | Anthropic Messages | 接入层要求 |
|---|---|---|---|
| 传输 | SSE completion chunks | SSE named events | adapter 分别解析，不用字符串猜格式 |
| 文本增量 | `choices[].delta.content` | `content_block_delta/text_delta` | 统一成 `TextDelta`，保留原始 index/event |
| 工具参数增量 | 按 tool call index/id 分片的 arguments | `input_json_delta.partial_json`，直到 block stop 才保证完整对象 | 不在中途强行 `json.loads`；按 call/block 累积 |
| 完成信号 | finish reason + `[DONE]` | `message_delta` + `message_stop` | 必须收到协议完成信号才标记 complete |
| 流式 usage | `stream_options.include_usage=true` 后，通常在 `[DONE]` 前额外 final chunk；中断可能缺失 | `message_start` 带输入 usage，`message_delta` 带累计输出 usage | usage 带 `complete/partial/unavailable` |
| 流内错误 | transport/SDK 异常；兼容网关可能自定义 | HTTP 200 后仍可能收到 SSE `error`，如 `overloaded_error` | `ErrorEvent` 必须是正常事件模型的一部分 |

来源：[S4][S9][S13]

### 4.3 Tool calling / tool use 与并行调用

| 维度 | OpenAI Chat Completions | Anthropic Messages |
|---|---|---|
| 工具定义 | `tools[].function.{name,description,parameters,strict}` | `tools[].{name,description,input_schema,...}` |
| 模型返回 | assistant message 的一个或多个 `tool_calls` | assistant content 中一个或多个有序 `tool_use` blocks |
| 结果回传 | 每个结果为 `role=tool` message，通过 `tool_call_id` 关联 | 下一条 user message 中放一个或多个 `tool_result` blocks，通过 `tool_use_id` 关联 |
| 并行开关 | 顶层 `parallel_tool_calls` | `tool_choice.disable_parallel_tool_use`，默认允许多个调用 |
| 完成原因 | `finish_reason=tool_calls` | `stop_reason=tool_use` |
| 执行顺序 | API 只返回调用；应用执行 | API 只返回调用；应用可并发、顺序或混合执行 |

OpenAI 与 Anthropic 都允许一轮返回多个工具调用，但**协议开关、消息回传形状和 content ordering 不同**。[S5][S10][S11] 因而推荐的规范化层只把它们归一成“有序的工具调用集合”，并把并发执行策略交给 Tool Executor；不要把 OpenAI message 结构直接当领域结构。

### 4.4 错误与重试

两套官方 SDK 都提供 typed exceptions 和相近的默认 transport retry，但协议层仍有三个必须显式处理的差异：

1. Anthropic 有明确的 `529 overloaded_error`，且流中可能在 HTTP 200 后发 error event；只按 HTTP status 处理会漏错。[S13]
2. OpenAI/Anthropic-compatible 中转站可能把上游错误重写成另一家的 error schema，甚至保持 HTTP 200 后在 SSE 中报错。
3. SDK、应用层和网关都可能重试。如果三层同时开启，实际尝试次数会乘法放大，成本与延迟难以解释。

建议规则：

- endpoint profile 明确 `retry_owner=client|gateway`；只允许一层拥有自动 transport retry；
- 客户端已收到第一个可见文本、tool delta 或 usage event 后，**不得静默重放整个流**；应结束为 `partial_error`，由 ReAct/runtime 决定是否发起新的、可观测的恢复请求；
- model transport retry 与 tool execution retry 分开记账；
- 统一错误分类只用于控制流，原始 HTTP status、provider error type/body、request ID、gateway request ID 必须保留。

---

## 五、需求矩阵

| ID | 级别 | 需求 | 验收标准 |
|---|---|---|---|
| R1 | 硬需求 | 协议与厂商解耦 | 同一模型可分别配置 `openai_chat_completions` 或 `anthropic_messages` |
| R2 | 硬需求 | 任意 Base URL | endpoint 可配置完整 base URL、headers、API key ref、TLS/proxy、timeout |
| R3 | 硬需求 | 双格式流式文本 | 两种协议都能发出有序 text deltas，并有可验证的正常完成信号 |
| R4 | 硬需求 | 双格式工具调用 | 单工具、混合文本+工具、工具参数分片、结果回传都能往返 |
| R5 | 硬需求 | 并行工具调用 | 能保留多个调用及各自 ID；模型并行开关与应用执行策略分离 |
| R6 | 硬需求 | usage/token 元数据 | 输入、输出、缓存、推理 token 尽可能保留；缺失或中断不得伪造为 0 |
| R7 | 硬需求 | 错误与重试可解释 | typed category + 原始错误 + request IDs + attempt 数；无重复隐式重试 |
| R8 | 硬需求 | ReAct 解耦 | ReAct runtime 不 import provider SDK 或 LangChain chat model 类型 |
| R9 | 重要 | 可观测性 | 记录 request、TTFT、总延迟、finish reason、usage、tool calls、错误和 retry |
| R10 | 重要 | 代理兼容性 | 每个 endpoint profile 通过 contract suite 后才标记可用于 production demo |
| R11 | 重要 | 可扩展协议 | 后续可独立增加 `openai_responses`，不破坏现有两种 adapter |
| R12 | 重要 | 原始信息保留 | normalized 字段之外保留安全过滤后的 raw metadata/provider details |

---

## 六、候选方案比较

### 6.1 总表

| 候选 | 双 HTTP 格式 | 自定义 Base URL | 流式 + tools + 并行 | usage / 错误 | ReAct 解耦 | 结论 |
|---|---|---|---|---|---|---|
| **官方 OpenAI + Anthropic 双 client，项目自有 adapter** | 满足；两个原生 adapter，不做互译 | 两套 SDK 均原生支持 | 原生能力最完整；需自行写两套事件映射 | 原生信息最完整，retry 可显式配置 | **最好**；上层只依赖项目 port | **推荐为长期边界** |
| LiteLLM Python SDK | 对上层主要统一为 OpenAI 风格；另有 Anthropic facade | 支持 `api_base` | 广，但按 provider 映射；unsupported params 可能报错或被配置为丢弃 | 统一 OpenAI 风格异常；原始语义部分保留 | 中等；会依赖 LiteLLM 类型与映射 | 不作为核心边界 |
| LiteLLM Proxy | 有 `/chat/completions`、`/responses`、`/v1/messages`；另有 Anthropic passthrough | client 指向 proxy；proxy 上游可配置 | 文档声明支持 stream/tools；跨 provider 并行与流中途失败仍需验证 | usage、成本、router retry/fallback 强；错误被标准化 | 好；HTTP 边界 | **可选二期网关**，优先 native passthrough |
| Bifrost Gateway | OpenAI、Anthropic、Google 兼容入口；可跨 provider 转换 | custom provider 支持 base URL、path override | gateway 核心支持 streaming/tool accumulation；Anthropic integration 文档细节仍不足 | 可聚合 usage/cost/latency；首字节后的 stream 不会 fallback | 好；HTTP 边界 | 有潜力，需原型后再与 LiteLLM 二选一 |
| LangChain `ChatOpenAI` + `ChatAnthropic` | 两个 provider adapter 分别支持 | 两者均可配 base URL | `bind_tools`、stream、usage normalization 成熟；`ChatOpenAI` 只承诺官方 OpenAI 字段 | 依赖底层 SDK，LangChain 再包装 metadata | **较差**；暴露 `BaseChatModel` 会绑框架 | 仅迁移 shim |
| Pydantic AI Model/Provider | `OpenAIChatModel`、`OpenAIResponsesModel`、`AnthropicModel` 分开 | provider/client 可注入 | 支持流式；多个 tool calls 默认并发执行，也可顺序 | `RequestUsage/RunUsage`、provider details 较完整；retry 可定制 | 中等；若只取 model 层仍引入其消息与工具类型 | 只有整体选择 Pydantic AI agent 时再考虑 |
| New API | 明确暴露 `/v1/chat/completions`、`/v1/responses`、`/v1/messages` | 支持自定义渠道 | 名义覆盖广；源码已有跨格式 tool choice/parallel/mixed-content 映射缺口 | 有 usage 修补、计费和渠道 retry | HTTP 边界 | 不作为工具正确性的唯一边界 |
| One API | **不满足**；支持 Anthropic 上游，但主要入站路由无 `/v1/messages` | 支持渠道/代理地址 | OpenAI 格式范围内可用 | 有配额/重试能力 | HTTP 边界 | **硬需求淘汰** |

### 6.2 官方双 client + 自有 adapter

**优点**

- 直接获得两个协议的 typed requests/responses、SSE helpers、request ID、官方错误与最新功能；
- 无额外网络 hop；可直连官方、任意中转或未来网关；
- 可对 OpenAI 与 Anthropic 的工具、usage、headers、beta 功能分别做 capability gating，而不是求一个脆弱的最大公约数；
- ReAct/runtime 与 provider SDK 完全隔离；换 LangGraph、Pydantic AI 或自研循环时，endpoint 配置与协议 contract 不变。

**代价**

- 需要维护两套 request/stream adapter 和 contract tests；
- 需要自己定义最小 normalized schema；
- 不能指望“统一 library”自动处理跨 provider fallback、预算、虚拟 key 等网关功能。

这里的自研范围应严格受控：只实现本项目需要的 text、client tools、parallel calls、usage、errors，不重做完整网关，也不试图覆盖两家所有原生工具。

### 6.3 LiteLLM

LiteLLM 是当前最完整的统一 SDK/Proxy 候选之一：Proxy 同时提供 OpenAI 风格端点、Anthropic `/v1/messages`，并可用 `/anthropic/v1/messages` 做原生 Anthropic passthrough；Router/Proxy 还提供 retries、fallbacks、cooldown、成本追踪。[S22][S23][S24]

但它更适合成为**基础设施层**而不是领域接口：

- `/v1/messages` 跨 provider 调用依赖协议转换；文档没有对所有 provider 的 parallel tools 和所有流事件给出统一保证；
- unsupported OpenAI params 默认可能抛异常，开启 `drop_params` 又会静默丢字段；
- 错误被映射到 OpenAI 风格，虽然保留部分 provider details，但精确语义仍可能变化；
- Router 文档没有承诺“已输出部分流后”能够安全 fallback；任何自动重放都必须通过原型确认。

因此若后续采用 LiteLLM Proxy，应优先：

1. Anthropic 原生上游走 `/anthropic/v1/messages` passthrough；
2. OpenAI 原生上游走 OpenAI 端点；
3. 只有经过 contract suite 的 endpoint 才允许跨协议/跨 provider 转换。

### 6.4 Bifrost

Bifrost 是 2026 年值得关注的网关候选：支持 OpenAI/Anthropic SDK 入口、custom provider、请求路径覆盖、重试/回退、流聚合与成本/延迟统计。[S25]

它的优点是 HTTP 边界清晰、Go/Rust 类网关部署形态轻于在应用进程里引入庞大 Python 适配库；源码还明确显示 streaming fallback 只发生在取得 stream channel 之前，流已经开始后不会暗中切换 provider，这个边界比模糊重放更安全。[S25]

但当前公开的 Anthropic SDK integration 文档没有充分规定 tool use、parallel、usage 和 error 的完整映射；“支持 SDK”仍不能直接等价为“本项目要求的 ReAct contract 全部通过”。因此列为 LiteLLM 的强备选，而不是未经原型直接推荐。

### 6.5 LangChain 自带 adapters

LangChain 当前文档确认：

- `ChatOpenAI(base_url=...)` 可连 OpenAI-compatible endpoint；
- `ChatAnthropic(base_url=...)` 可连 Messages-compatible endpoint；
- 两者支持流式、标准化 `tool_calls` 和 `usage_metadata`；
- 但 `ChatOpenAI` 只处理官方 OpenAI 规范，第三方非标准字段不会保留，官方建议需要 provider 特性时使用专用集成。[S14][S15]

这与当前代码集成成本最低，但长期问题是类型耦合。`backend/src/chat_agents/agent` 把 `BaseChatModel` 直接当核心接口，而 `create_react_agent` 已进入弃用路径。[S16] 因此它可以作为迁移 shim，不能成为目标架构的 `ModelPort`。

### 6.6 Pydantic AI

Pydantic AI 2.x 已有相当完整的 Model/Provider 抽象：OpenAI Chat、OpenAI Responses、Anthropic 分开建模，允许注入自定义 clients/base URL；`RunUsage` 支持 input/output/cache/cost/details；多个 tool calls 默认并发调度，也能在模型或工具级强制顺序。[S17][S18][S19][S20][S21]

问题不在能力，而在决策顺序：issue #2 只决定模型接入层，地图又明确 agent 框架可更换。现在用 Pydantic AI 的 `ModelRequest/ModelResponse`、toolset 和 retry 作为公共类型，会提前替后续 agent 框架票做决定。若未来整套 ReAct runtime 选 Pydantic AI，再复用其 model layer 是合理的；当前不应反向用 model layer 锁死 runtime。

### 6.7 New API 与 One API

- **One API**：源码入站路由包括 `/v1/chat/completions` 等 OpenAI 路径，但没有 `/v1/messages`；“有 Anthropic adaptor”只说明它能把 Anthropic 当上游，不满足双协议格式硬需求。[S27]
- **New API**：已经新增 `/v1/messages`、`/v1/responses` 和跨格式转换，是 One API 类产品中更接近需求的候选。[S26] 但当前源码显示：
  - Anthropic Messages 转 OpenAI Chat 时没有完整转发 `tool_choice` 与并行控制；
  - 同一 Anthropic message 同时包含文本/媒体与 tool use 时，部分转换路径会优先 tool calls 而丢失其他内容；
  - OpenAI 转 Anthropic 的并行开关需经自定义映射，语义不是简单一一对应；
  - 项目另有专门测试补丁来补全流式 `message_delta.usage`，说明实际中转 usage 需要修复和合并。

这些并不代表 New API 不可用，而是说明“路由存在”与“ReAct 工具流完整等价”是两回事。它更适合账号/渠道管理或作品集演示网关，不应未经认证成为工具正确性的唯一基础。

---

## 七、推荐架构边界

### 7.1 配置模型

建议 endpoint profile 至少包含：

```text
id
protocol                 # openai_chat_completions | anthropic_messages | future: openai_responses
base_url
model
api_key_ref              # 引用 secret，不把 key 写入普通配置或 trace
default_headers          # 如 anthropic-version / beta / 中转自定义 header
timeout
max_retries
retry_owner              # client | gateway
capability_overrides     # stream_usage、parallel_tools、strict_tools 等已认证能力
pricing_key              # 与 endpoint alias 分离
```

`provider` 可作为观测标签，但不能决定 wire protocol。

### 7.2 项目自有 port

上层只看到项目类型，例如：

```python
class ModelPort(Protocol):
    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelEvent]: ...
    async def complete(self, request: ModelRequest) -> ModelResponse: ...
```

`ModelEvent` 的最小集合：

- `ResponseStarted`
- `TextDelta`
- `ToolCallStarted`
- `ToolCallArgumentsDelta`
- `ToolCallCompleted`
- `UsageUpdated`
- `ResponseCompleted`
- `ModelError`

事件至少携带 `request_id`、`response_id`、`model`、`protocol`、序号/内容块 index、时间戳；provider-specific data 放在经过脱敏的 `raw_metadata`。

### 7.3 Usage 规范化

建议结构：

```text
input_tokens?
output_tokens?
total_tokens?
cache_read_tokens?
cache_write_tokens?
reasoning_tokens?
source                  # provider | gateway | estimated
status                  # complete | partial | unavailable
raw_usage
```

规则：

- 未返回就是 `null`，不是 `0`；
- OpenAI final usage chunk 未到时标 `partial/unavailable`；
- Anthropic 缓存 token 单独保留，不提前揉进一个不可逆的 input 数；
- 成本计算放在独立 pricing service，通过 normalized + raw usage 计算，并记录价格表版本；
- 本地始终测量 start、TTFT、completion、tool latency，不依赖 provider 是否返回 latency。

### 7.4 Tool Executor 边界

模型 adapter 只负责产出有序 tool calls；Tool Executor 决定：

- 哪些只读工具可并发；
- 哪些有副作用工具必须串行；
- timeout、取消、结果大小与错误包装；
- 将多个结果按各协议正确形状回传。

这样保留了 ReAct 范式，又不会把“并行工具执行”错误地委托给 SDK 或网关。

### 7.5 网关边界

网关放在 clients 之后，保持可插拔：

```text
官方 client -> 官方 endpoint
官方 client -> 中转站
官方 client -> LiteLLM/Bifrost/New API -> 上游 provider
```

对应用而言三者都只是 endpoint profile。新增或移除网关不改变 `ModelPort`，也不改变 ReAct/tool/trace 的领域类型。

---

## 八、集成草图

```text
FastAPI / WebSocket-SSE API
          |
          v
ReAct Runtime  -----------------------> Tool Executor
(只依赖 ModelPort)                     |  并发策略 / timeout / tool events
          |                             |
          | ModelRequest                | ToolResult[]
          v                             |
Project-owned ModelPort <--------------+
          |
          +--> Protocol Router
                  |
                  +--> OpenAIResponsesAdapter          [优先]
                  |       +--> AsyncOpenAI(base_url=...).responses
                  |
                  +--> OpenAIChatCompletionsAdapter    [并列]
                  |       +--> AsyncOpenAI(base_url=...).chat.completions
                  |
                  +--> AnthropicMessagesAdapter        [并列]
                          +--> AsyncAnthropic(base_url=...)

所有 ModelEvent / ToolEvent
          |
          +--> Trace recorder
          +--> Token / latency / cost projector
          +--> 前端统一流事件
```

### 当前仓库的迁移边界

1. 先定义 endpoint profile 与 contract tests；
2. 将 `LLMConfig` 的厂商工厂替换为协议路由，但不让官方 SDK 类型越过 adapter；
3. 迁移期若仍使用 LangGraph prebuilt agent，可在 `integrations/langchain/` 放一个临时 bridge，禁止业务代码直接 import `ChatOpenAI` / `ChatAnthropic`；
4. 随 ReAct runtime 重构，改成 runtime 直接依赖 `ModelPort`，删除 bridge；
5. 可观测性直接消费规范化事件，不从 LangChain callback 的字符串表示反推 usage 或 tool call。

### 双协议映射必须保留的语义

| 领域语义 | OpenAI adapter | Anthropic adapter |
|---|---|---|
| system instruction | system/developer message 策略 | 顶层 `system` |
| 多工具调用 | `tool_calls[]` | 多个有序 `tool_use` blocks |
| 工具结果 | 多条 `role=tool` | 同一 user turn 中多个 `tool_result` blocks |
| 禁用并行 | `parallel_tool_calls=false` | `tool_choice.disable_parallel_tool_use=true` |
| 工具参数流 | 按 tool index/id 聚合 arguments | 按 content block index 聚合 partial JSON |
| usage 完整性 | final usage chunk 是否到达 | message start/delta/stop 是否完整 |
| 正常完成 | finish reason + stream end | `message_stop` |

---

## 九、被淘汰或降级为条件选项的方案

| 方案 | 本次结论 | 淘汰/降级理由 | 何时可重新考虑 |
|---|---|---|---|
| 所有模型统一走 OpenAI-compatible | 淘汰 | 不满足 Anthropic Messages 格式硬需求；原生 tool/strict/cache/thinking 等语义可能丢失；Anthropic 官方也不建议把其 OpenAI compatibility 当多数生产场景长期方案 [S12] | 产品明确放弃 Anthropic 原生格式时 |
| One API 作为唯一接入层 | 淘汰 | 入站路由没有 `/v1/messages`；支持 Anthropic 上游不等于支持 Anthropic 协议 [S27] | 项目硬需求改变为只支持 OpenAI 格式时 |
| New API 作为唯一协议正确性边界 | 淘汰 | 虽有双入口，但源码可见 tool choice/parallel/mixed content/usage 修补风险 [S26] | contract suite 对目标 endpoint/model 全部通过，且接受 AGPL/运维边界后 |
| LangChain `BaseChatModel` 作为领域接口 | 淘汰 | 与 agent 框架耦合；当前 prebuilt ReAct API 已弃用迁移 [S16] | 仅作为短期 bridge，不向领域层泄漏 |
| Pydantic AI Model 类型作为公共接口 | 暂不选 | 会提前锁定后续 agent runtime；版本迭代快 | 后续 agent 框架票整体选择 Pydantic AI 时 |
| LiteLLM Python SDK 直接嵌入业务核心 | 暂不选 | 映射与依赖进入应用进程；统一格式会掩盖协议差异 | 只需快速多 provider PoC，且能接受 LiteLLM 类型泄漏时 |
| LiteLLM Proxy / Bifrost | 条件选项 | 增加网络 hop、运维与翻译面；跨格式工具流仍需认证 | 需要集中 virtual keys、路由、fallback、成本治理时，作为可拔插 gateway |

---

## 十、风险与待验证项

以下不是“查文档即可消除”的问题，必须做小型原型。原型应对**每个 endpoint profile**运行，而不是只测官方端点。

| 优先级 | 风险 / 未知 | 原型用例 | 通过标准 |
|---|---|---|---|
| P0 | OpenAI-compatible 中转不支持流式 usage | `stream=true + include_usage`，正常完成与主动断流各一次 | 正常流有完整 usage；断流明确标 partial/unavailable，不伪造 0 |
| P0 | Anthropic-compatible 中转的 SSE 事件不完整或非标准 | 记录全部 event type、顺序、message stop、error event | 能解析已知事件；未知事件可跳过/保留；缺 `message_stop` 不判成功 |
| P0 | 工具参数跨 chunk JSON 拼接错误 | 嵌套对象、数组、Unicode、长字符串工具参数 | block 完成后 JSON 与期望完全一致；中途不误执行 |
| P0 | 并行调用映射丢 ID 或顺序 | 一轮强制返回两个工具，结果逆序完成 | 两个 call ID 均稳定；结果正确关联；无重复调用 |
| P0 | 混合文本 + 多工具调用被翻译层丢失 | assistant 同轮先文本后两个工具 | 文本、顺序、两个 calls 全部保留 |
| P0 | 重试叠加导致多次计费/重复输出 | client 与 gateway 分别设置 retry，注入 429/500/timeout | 实际 attempts 与配置一致；trace 能解释每次尝试；首事件后不重放 |
| P0 | 流中途断开后的错误语义 | 首 token 后断 TCP、SSE error、取消请求 | 返回 partial error；连接释放；不把半截回答存成正常完成 |
| P1 | `tool_choice` 与禁用并行跨网关失真 | OpenAI `required/forced/parallel=false`；Anthropic `any/tool/disable_parallel` | 行为与协议预期一致，否则 capability 标记不支持 |
| P1 | 错误和 request ID 被中转重写 | 400、401、429、529/5xx 各测一次 | canonical category 正确，同时保留 status、raw type、provider/gateway request IDs |
| P1 | 自定义 headers 被中转过滤 | `anthropic-version`、beta header、自定义鉴权 header | header 到达上游；被拒绝时有明确 capability/config 错误 |
| P1 | model alias 导致成本归属错误 | 请求 alias，检查返回 model 与 gateway route metadata | trace 能记录请求 alias、实际模型/部署和价格表 key |
| P1 | 取消与 backpressure | 客户端断开、慢消费者、多并发流 | 上游请求及时取消；无连接泄漏；不会继续产生无主成本 |
| P1 | LangGraph 迁移 shim 是否保真 | `bind_tools`、stream、并行 calls、usage 经过 bridge | 事件不丢失；若做不到，优先重写 ReAct node 而非扩大 shim |
| **P0** | **OpenAI Responses 协议适配**（原列为 P2，勘误后升级）| Responses adapter 的流式、工具循环、usage 三态，与 Chat Completions 同标准验证 | 三种协议在 `ModelPort` 出口处产生一致的规范化事件；Responses 的 `response.*` 事件流与工具调用状态机被正确映射 |
| P1 | 同一模型经 Responses 与 Chat Completions 两条协议的行为差异 | 同一 endpoint 分别用两种协议跑同一组工具调用用例 | 差异被记录进 capability 表；不试图在适配层内部抹平 |
| **P0** | **模型发现接口在自定义 base_url / 中转站下不可用或格式不一致**（12.8）| 对官方端点与目标中转站分别调模型列表接口；含不实现该接口的站点 | 能发现时返回真实清单并标 `source=discovered`；不能发现时回退静态兜底并标 `source=fallback`，UI 有明确提示；**不因发现失败而阻断调用** |
| **P0** | **无效 model ID 被静默替换**（现状 `.get(model, 默认值)` 的行为）| 传入不存在的 model ID、拼写错误的 ID、其他 endpoint 的 ID | **显式报错**并指明可用清单；绝不悄悄换成默认模型 |
| P1 | **tool 模型与主模型指向不同 endpoint 时的行为**（12.9）| 主模型走用户自带 Claude key，tool 模型走服务端预设小模型 | 两条链路各自使用正确的 profile 与 key；trace 中两个角色的用量与成本**分别归属**，不混算 |

### 对网关候选的最小对比原型

如果后续确实需要集中网关，应让 LiteLLM Proxy 与 Bifrost 使用同一组测试：

1. OpenAI Chat 入站 -> OpenAI 上游（原生同格式）；
2. Anthropic Messages 入站 -> Anthropic 上游（原生同格式或 passthrough）；
3. OpenAI Chat 入站 -> Anthropic 上游（跨格式）；
4. Anthropic Messages 入站 -> OpenAI 上游（跨格式）；
5. 四条路径都跑单工具、并行工具、混合文本+工具、stream usage、429/5xx、首 token 后断流。

只要 3/4 的跨格式路径不稳定，也不影响本报告主方案：应用仍可用两个官方 client 分别调用网关的两个入口，且只启用已认证路线。

---

## 十一、建议的后续实施顺序

1. **先写协议 contract tests**，再改工厂；测试 fixture 同时覆盖官方端点 mock 与目标中转站。
2. 定义 `EndpointProfile`、`ModelPort`、`ModelEvent`、`Usage`、`ModelError`；禁止其中出现 LangChain/Pydantic AI/provider SDK 类型。
3. 实现三个 adapter，使用官方 async clients，显式配置 timeout/retries：**`OpenAIResponsesAdapter`（优先）**、`OpenAIChatCompletionsAdapter`、`AnthropicMessagesAdapter`。三者共享 `ModelPort` 出口契约，内部不互相翻译。
4. 让 ReAct runtime 消费 finalized tool calls，让 Tool Executor 负责并发与回传。
5. 将 trace/token/latency/cost 接到规范化事件；usage 不完整时在 UI 明示，而不是估算成“精确值”。
6. **把模型角色拆成 main / tool 两个独立配置**（详见 12.9）：移除 `backend/src/chat_agents/main.py:163-172` 摘要模型硬编码 Claude Haiku 的假设；tool 模型默认跟随主模型，可在高级选项独立覆盖，甚至指向不同的 endpoint profile。trace 按角色区分用量。
7. **实现模型运行时发现**（详见 12.8）：后端按 protocol 调模型列表接口，经 `GET /api/models` 下发；前端选单不得硬编码。发现失败回退静态兜底并标 `source=fallback`；无效 model ID 显式报错而非静默替换。
8. **实现两层密钥来源**（详见第十二章）：服务端 `EndpointProfile` 预设作默认；前端「高级选项」支持用户自定义（常用供应商预设 + 自定义地址/格式/认证字段）。**用户填了优先用用户的，未填才降级到预设**；用户 key 失败不静默 fallback。两层共用同一 `EndpointProfile` 结构。
9. 同步落实用户密钥的卫生要求：强制 HTTPS、服务端不持久化、trace 排除密钥字段、前端仅用 `sessionStorage`、UI 明示「仅本次会话使用」。
10. 最后再做 LiteLLM/Bifrost 网关 PoC；只有出现集中路由、virtual key、fallback 或治理的真实需求时才部署。

---

## 十二、配置形态：两层分离 —— 服务端 Endpoint Profile 与用户自定义模型

> **本章为勘误重写。** 初版把「运维侧的 endpoint 配置」与「用户侧的密钥输入」混在一起谈 profile 切换，与地图既定的「密钥放服务端环境、用户无感知」相矛盾。经用户指正，现明确拆为**两层**，并给出二者之间的降级规则。

### 12.1 矛盾在哪

初版第十二章提出「具名 profile 集合 + 运行时切换」，但没说清**谁在切**。这导致两种读法：

- 若是**运维在切** → 与「用户无感知」一致，但那就不该有 UI 选单；
- 若是**用户在切** → 意味着用户要填密钥，与「demo 由项目方出 key」相矛盾。

初版同时暗示了两者，是错的。正确的架构是**两层并存、各司其职**，用一条明确的降级规则连接。

### 12.2 两层职责

| | **第一层：服务端预设** | **第二层：用户自定义** |
|---|---|---|
| **配置在哪** | 服务端环境变量 / 配置文件 | 前端「高级选项」，随请求传递 |
| **谁维护** | 项目方（运维） | 访客自己 |
| **密钥归属** | 项目方的 key，**永不下发到浏览器** | 访客自己的 key，**服务端不持久化** |
| **默认可见性** | 用户无感知 | 折叠在高级选项内，默认不展开 |
| **用途** | 让 demo 开箱即用 | 让访客用自己的额度、自己的中转、自己的模型 |

**这不是二选一，而是有优先级的叠加。**

### 12.3 调用规则（用户指定）

> **优先调用用户填入的模型；用户未填写时，降级到环境变量预设。**

```
请求到达
   |
   +-- 用户在高级选项填了模型配置？
   |      |
   |      +-- 是 --> 用用户的 EndpointProfile（protocol / base_url / auth_field / key）
   |      |            |
   |      |            +-- 调用失败？--> 如实报错给用户，【不静默降级到服务端 key】
   |      |
   |      +-- 否 --> 用服务端环境变量预设的默认 profile
   |
   +-- 记录本次实际使用的是哪一层（进 trace，但密钥不入 trace）
```

**一处必须明确的边界**：用户填了 key 但调用失败时，**不能静默 fallback 到服务端 key**。否则用户以为在用自己的额度，实际却在消耗项目方的——这既是计费上的欺骗，也会让 trace 里的成本归属失真。失败就如实报错，让用户自己决定是改配置还是清空以使用预设。

### 12.4 用户侧「高级选项」的形态

界面分两级，参考 ccswitch 的字段划分（据用户提供的界面截图）：

**A. 常用供应商选单（预设调用地址）**

选中即自动填好 `base_url`、`protocol`、`auth_field` 的推荐值，用户只需粘贴自己的 key：

| 供应商 | 预设 base_url | 预设 protocol | 预设 auth_field |
|---|---|---|---|
| Anthropic 官方 | `https://api.anthropic.com` | `anthropic_messages` | `x-api-key` |
| OpenAI 官方 | `https://api.openai.com/v1` | `openai_responses` | `Authorization` |
| （其余主流供应商由 #15 决策票补全清单） | | | |

**B. 自定义选单**

供中转站与自建网关使用，四个字段全部由用户填写：

| 字段 | 说明 | 对应 ccswitch |
|---|---|---|
| **调用地址** | `base_url` | — |
| **API 格式** | 三值下拉：`OpenAI Responses` / `OpenAI Chat Completions` / `Anthropic Messages` | 「API 格式」下拉 |
| **认证字段** | header/env 名称可选，如 `x-api-key` / `Authorization` / `ANTHROPIC_AUTH_TOKEN` | 「认证字段」下拉 |
| **API Key** | 密钥本身 | — |

**认证字段可配置是本报告初版的盲点**：不同中转站期待的 header 名称不同，不能把它硬编码在 adapter 里。ccswitch 把它做成显式下拉，印证了这一点。

ccswitch 界面中「需开启路由」的标注也值得学——它诚实告知用户非原生协议需要中转站支持相应路由。对应到本项目，即 profile 的 **capability 声明**：某地址支持哪些协议应可探测并展示，而非假装全支持。

### 12.5 安全语义（必须在 UI 上讲清楚）

用户自定义这条路径意味着**密钥经浏览器传到后端**，这是有代价的，不能含糊：

- **必须 HTTPS**，否则密钥明文过网。
- **服务端不持久化用户密钥**：只在单次请求生命周期内使用，不写日志、不写 trace、不写会话存档。这一条要在 #4 的 trace 数据模型中显式排除密钥字段。
- **UI 上明示**「密钥仅本次会话使用，不会被保存」，并说明它会经过本服务器——让用户知情后再决定。
- 前端存储用户密钥仅限 `sessionStorage`（关闭标签即失效），不用 `localStorage`。

> 地图已将「访问层防刷 / 鉴权」划为 out-of-scope，本节讨论的**不是**鉴权，而是**用户自带密钥这条路径本身的卫生要求**，二者不冲突。

### 12.6 服务端预设的 Profile 形态

第一层（服务端）仍建议采用具名 profile，但**由运维配置，不暴露为用户选单**：

```yaml
# 形态示意，最终 schema 由 #13 后端分层架构票确定
default_profile: anthropic-official

endpoints:
  - name: "anthropic-official"
    protocol: anthropic_messages
    base_url: "https://api.anthropic.com"
    auth_field: "x-api-key"
    auth_secret_ref: "ANTHROPIC_API_KEY"   # 只存 env 变量名，不存明文
    capabilities: [streaming, tools, parallel_tools, usage_in_stream]

  - name: "openai-official-responses"
    protocol: openai_responses
    base_url: "https://api.openai.com/v1"
    auth_field: "Authorization"
    auth_secret_ref: "OPENAI_API_KEY"
    capabilities: [streaming, tools, parallel_tools, usage_in_stream]
```

**两层共用同一个 `EndpointProfile` 数据结构**——这是本方案的关键收益。服务端 profile 从配置文件构造，用户 profile 从请求构造，二者进入 `ModelPort` 后走完全相同的代码路径。适配层不需要知道这次用的是谁的 key。

### 12.7 与现状的关系

`backend/src/chat_agents/main.py:112-116` 现在已经是 `request.headers.get("X-Claude-Key") or os.getenv("ANTHROPIC_API_KEY")` 的形态——**本章规则正是这一既有行为的正式化与扩展**，而非新发明。差异在于：

| | 现状 | 本章规则 |
|---|---|---|
| 可配置项 | 只有 key | key + base_url + protocol + auth_field |
| header 命名 | 每厂商一个（`X-Claude-Key` / `X-OpenAI-Key`…） | 统一为结构化的 profile 传递 |
| 失败语义 | 未定义 | 用户 key 失败不静默降级 |
| 供应商预设 | 无 | 常用供应商选单 |
| 安全说明 | 无 | UI 明示 + 不持久化 + sessionStorage |

`backend/src/chat_agents/llm` 目前把模型 ID 硬编码在字典里、无 base_url、无 auth_field、`provider` 混淆厂商与协议，是这一整块的替换对象。

### 12.8 模型清单：从硬编码改为运行时发现

> 用户规则：**主页默认选项仍要提供模型切换；支持自动调用识别模型的名称，注入前端供用户选择。**

#### 现状的病根：清单存在两份且必然漂移

| 位置 | 内容 |
|---|---|
| `backend/src/chat_agents/llm/27-48` | `CLAUDE_MODELS` / `OPENAI_MODELS` 字典，别名 → 真实 model ID |
| `frontend/src` | **前端又硬编码一份**别名 → 展示名 |

两份清单没有任何同步机制。后端加一个模型，前端看不见；前端改一个别名，后端 `.get(model, 默认值)` 会**静默回退**到默认模型而不报错——这正是 `claude-opus-4-1-202508059`（日期段 9 位的无效 ID）能一直躺在代码里没被发现的原因。

#### 规则：模型清单由后端在运行时发现并下发

```
前端启动 / 用户切换 endpoint
        |
        v
GET /api/models?profile=<name>        <-- 后端返回该 endpoint 实际可用的模型
        |
        +-- 后端按 protocol 调用对应的模型发现接口
        |     - openai_responses / openai_chat_completions --> GET /v1/models
        |     - anthropic_messages                          --> GET /v1/models
        |
        +-- 发现失败？--> 回退到该 profile 的静态兜底清单，并标记 source=fallback
        |
        v
前端渲染选单（不再硬编码任何模型名）
```

**三条设计要求**：

1. **前端不得硬编码模型清单。** 选单内容一律来自后端接口。这消灭了上述漂移。
2. **必须有兜底。** 部分中转站不实现 `/v1/models`，或返回的清单不可信。此时回退到该 profile 配置里的静态清单，并在响应中标注 `source: discovered | fallback`，让 UI 能提示「此地址不支持模型发现，以下为预设清单」。
3. **禁止静默回退到默认模型。** 用户指定的 model ID 若不在可用清单中，应显式报错，而非 `.get(model, DEFAULT)` 悄悄换一个——现状的写法会掩盖无效 ID。

**待验证项（升为 P0）**：Anthropic 与 OpenAI 的模型列表接口在**自定义 base_url / 中转站**下的可用性与返回格式一致性，本会话未核实（搜索额度耗尽），须在 #15 决策时实测。

#### 模型清单的展示与分组

发现接口返回的是裸 model ID（如 `claude-sonnet-4-5-20250929`），对用户不友好。建议：

- **有预设映射的**（Anthropic / OpenAI 官方常用型号）显示友好名 + 定位说明
- **未知型号**直接显示原始 ID，不猜测、不隐藏——中转站常有自定义命名，猜错比不猜更糟
- 保留用户**手动输入任意 model ID** 的入口（高级选项内），因为发现接口不一定覆盖全部

### 12.9 Tool 模型独立可配

> 用户规则：**高级选项提供自定义 tool 模型的切换选单，用户可自定义调用 tool 时使用的模型。**

#### 现状的病根：tool 模型硬编码为 Claude Haiku

`backend/src/chat_agents/main.py:163-172`：

```python
summary_llm = LLMConfig.create_claude(   # 硬编码 Claude
    model="haiku",                        # 硬编码 haiku
    api_key=claude_api_key,               # 硬编码用 Claude 的 key
    ...
)
```

**即使用户主模型选了 OpenAI，工具输出摘要仍会去调 Anthropic。** 后果有三：

- 只配了 OpenAI endpoint 的用户，工具摘要路径直接失败；
- 用户自带 OpenAI key 时，摘要却在消耗**项目方的 Claude 额度**——与 12.3 的成本归属规则冲突；
- trace 里会出现一次用户没有选择、也无法解释的模型调用。

#### 规则：Tool 模型是独立的一等配置

**模型角色分离**——本项目至少有两个模型角色，各自独立配置：

| 角色 | 用途 | 默认行为 |
|---|---|---|
| **主模型**（main） | ReAct 推理、最终回答生成 | 用户在主页选单选择 |
| **工具模型**（tool） | 工具输出摘要 / 结构化处理 | **默认跟随主模型**，可在高级选项独立覆盖 |

**「默认跟随主模型」是关键的默认值选择**：它保证零配置时不会出现跨厂商的意外调用，也不会消耗用户没预期的 key。用户想省钱时，再主动在高级选项里把 tool 模型切成便宜的小模型——这是**用户的显式选择**，而不是系统替他做的假设。

**Tool 模型的配置面与主模型完全一致**：可以选同一个 endpoint 下的另一个模型，也可以指向**完全不同的 endpoint profile**（例如主模型走用户自己的 Claude，tool 模型走服务端预设的便宜模型）。因此：

- Tool 模型配置也是一个 `EndpointProfile` + model ID 的组合
- 它同样遵循 12.3 的两层降级规则
- **trace 中必须区分两个角色的调用与用量**，否则成本归属会把 tool 调用混进主模型账上（#4 承接）

#### 与 #14 的边界

工具输出摘要**是否还需要存在**，由 #14（工具链最终清单）决定——#8 已建议用 Jina Reader 替代 Tavily Extract/Crawl，其返回已是干净 Markdown，二级摘要可能整个不必要。

**但本节的架构要求不因此失效**：只要存在任何「非主模型的 LLM 调用」（摘要、重排、查询改写、结构化抽取），它就必须是独立可配的角色，而不是硬编码。若 #14 最终砍掉摘要，本节规则退化为「预留 tool 角色但无默认用途」，不影响 `ModelPort` 的设计。

### 12.10 移交

- **#13（后端分层架构）** — 承接 `EndpointProfile` 的数据结构、两层构造路径、**模型角色（main / tool）的表达方式**、以及那个悬而未决的「API key 传递路径要不要保留」问题。**本章的答案是：保留，并升级为一等功能。**
- **#15（多模型路由与降级）** — 承接常用供应商预设清单、capability 探测、「用户 key 失败不静默降级」的错误语义、**模型发现接口的实测与兜底策略**、**tool 模型默认跟随主模型的具体规则**。
- **#12（API 契约标准化）** — 承接 `GET /api/models` 的契约设计：发现结果、`source` 标记、错误语义。
- **#18（trace 界面呈现）** — 承接「本次用的是用户 key 还是服务端预设」的呈现，以及**主模型与 tool 模型的调用/成本如何分别展示**。
- **#4 的 trace 数据模型** — 须显式排除密钥字段，记录密钥来源，**并按模型角色区分 span 与用量**。
- **#6 前端栈** — 模型选单需从后端接口动态渲染，不得硬编码（现状 `frontend/src` 的做法不可延续到 React 版）。

> **来源说明**：本章 ccswitch 相关内容依据用户提供的界面截图（2026-08-06）总结其字段设计。ccswitch 项目本身的仓库地址、版本与实现细节**未经核实**（本会话网络搜索额度已用尽），故只借鉴其**配置抽象**，不对该工具的实现或成熟度作任何断言。

---

## 十三、来源清单

以下均为官方文档、官方 GitHub 仓库、源码或 GitHub issue；查询日期均为 **2026-08-06**。

- **[S1]** Wayfinder 地图 issue #1：<https://github.com/EllisYuan/ChatAgents/issues/1>（查询日期：2026-08-06）
- **[S2]** 本研究 issue #2：<https://github.com/EllisYuan/ChatAgents/issues/2>（查询日期：2026-08-06）
- **[S3]** OpenAI Python SDK README（base URL、proxy、retry、timeout、errors、request ID）：<https://github.com/openai/openai-python/blob/main/README.md>（查询日期：2026-08-06）
- **[S4]** OpenAI Chat Completions API reference（stream、tools、parallel、usage）：<https://developers.openai.com/api/docs/api-reference/chat/create>（查询日期：2026-08-06）
- **[S5]** OpenAI Function calling guide：<https://developers.openai.com/api/docs/guides/function-calling>（查询日期：2026-08-06）
- **[S6]** OpenAI Migrate to Responses / Responses 与 Chat Completions 定位：<https://developers.openai.com/api/docs/guides/migrate-to-responses>（查询日期：2026-08-06）
- **[S7]** OpenAI Rate limits 与错误处理：<https://developers.openai.com/api/docs/guides/rate-limits>、<https://developers.openai.com/api/docs/guides/error-codes>（查询日期：2026-08-06）
- **[S8]** Anthropic Python SDK（base URL、streaming、usage、tools、retry、timeout、errors）：<https://platform.claude.com/docs/en/api/sdks/python>（查询日期：2026-08-06）
- **[S9]** Anthropic Messages streaming event schema：<https://platform.claude.com/docs/en/api/messages-streaming>（查询日期：2026-08-06）
- **[S10]** Anthropic Define tools：<https://platform.claude.com/docs/en/docs/agents-and-tools/tool-use/implement-tool-use>（查询日期：2026-08-06）
- **[S11]** Anthropic Parallel tool use：<https://platform.claude.com/docs/en/agents-and-tools/tool-use/parallel-tool-use>（查询日期：2026-08-06）
- **[S12]** Anthropic OpenAI SDK compatibility 及限制：<https://platform.claude.com/docs/en/api/openai-sdk>（查询日期：2026-08-06）
- **[S13]** Anthropic API errors / mid-stream error / retries：<https://platform.claude.com/docs/en/api/errors>（查询日期：2026-08-06）
- **[S14]** LangChain ChatOpenAI / ChatAnthropic integrations：<https://docs.langchain.com/oss/python/integrations/chat/openai>、<https://docs.langchain.com/oss/python/integrations/chat/anthropic>（查询日期：2026-08-06）
- **[S15]** LangChain provider-specific 与 OpenAI-compatible 区别：<https://docs.langchain.com/oss/python/concepts/providers-and-models>（查询日期：2026-08-06）
- **[S16]** LangGraph v1 migration，`create_react_agent` 弃用：<https://docs.langchain.com/oss/python/migrate/langgraph-v1>（查询日期：2026-08-06）
- **[S17]** Pydantic AI Models overview：<https://pydantic.dev/docs/ai/models/overview/>（查询日期：2026-08-06）
- **[S18]** Pydantic AI OpenAI models/providers：<https://pydantic.dev/docs/ai/models/openai/>（查询日期：2026-08-06）
- **[S19]** Pydantic AI Anthropic models/providers：<https://pydantic.dev/docs/ai/models/anthropic/>（查询日期：2026-08-06）
- **[S20]** Pydantic AI parallel/sequential tool execution：<https://pydantic.dev/docs/ai/tools-toolsets/tools-advanced/>（查询日期：2026-08-06）
- **[S21]** Pydantic AI usage model：<https://pydantic.dev/docs/ai/usage/>（查询日期：2026-08-06）
- **[S22]** LiteLLM Anthropic-compatible `/v1/messages`：<https://docs.litellm.ai/docs/anthropic_unified>（查询日期：2026-08-06）
- **[S23]** LiteLLM Anthropic native passthrough：<https://docs.litellm.ai/docs/pass_through/anthropic_completion>（查询日期：2026-08-06）
- **[S24]** LiteLLM routing/retries 与 exception mapping：<https://docs.litellm.ai/docs/routing>、<https://docs.litellm.ai/docs/exception_mapping>（查询日期：2026-08-06）
- **[S25]** Bifrost 官方仓库、双 SDK integration、custom providers 与 stream fallback 源码：<https://github.com/maximhq/bifrost>、<https://github.com/maximhq/bifrost/blob/dev/docs/integrations/anthropic-sdk/overview.mdx>、<https://github.com/maximhq/bifrost/blob/dev/docs/integrations/openai-sdk/overview.mdx>、<https://github.com/maximhq/bifrost/blob/dev/docs/providers/custom-providers.mdx>、<https://github.com/maximhq/bifrost/blob/dev/core/bifrost.go>（查询日期：2026-08-06）
- **[S26]** New API 官方仓库、入站路由与协议转换源码：<https://github.com/QuantumNous/new-api>、<https://github.com/QuantumNous/new-api/blob/main/router/relay-router.go>、<https://github.com/QuantumNous/new-api/blob/main/relaykit/relayconvert/internal/claude_messages/to_oai_chat_req.go>、<https://github.com/QuantumNous/new-api/blob/main/relaykit/relayconvert/internal/oai_chat/to_claude_messages_req.go>、<https://github.com/QuantumNous/new-api/blob/main/relaykit/relayconvert/internal/oai_chat/to_claude_messages_resp.go>、<https://github.com/QuantumNous/new-api/blob/main/relay/channel/claude/message_delta_usage_patch_test.go>（查询日期：2026-08-06）
- **[S27]** One API 官方仓库与入站路由源码：<https://github.com/songquanpeng/one-api>、<https://github.com/songquanpeng/one-api/blob/main/router/relay.go>（查询日期：2026-08-06）
- **[S28]** 调研时版本快照：OpenAI Python `v2.53.0` <https://github.com/openai/openai-python/releases/tag/v2.53.0>；Anthropic Python `v0.120.2` <https://github.com/anthropics/anthropic-sdk-python/releases/tag/v0.120.2>；LiteLLM `v1.95.0` <https://github.com/BerriAI/litellm/releases/tag/v1.95.0>；Pydantic AI `v2.25.0` <https://github.com/pydantic/pydantic-ai/releases/tag/v2.25.0>；New API `v1.0.0-rc.23` <https://github.com/QuantumNous/new-api/releases/tag/v1.0.0-rc.23>（查询日期：2026-08-06）

[S11]: 
