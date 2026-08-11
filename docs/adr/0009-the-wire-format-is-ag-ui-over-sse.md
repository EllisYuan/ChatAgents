# 线格式说 AG-UI，跑在 SSE 上

[ADR-0008](./0008-a-run-emits-domain-events-not-wire-frames.md) 把[运行事件](../../CONTEXT.md)与线格式切开后，留下一个没答的问题：线格式究竟长什么样。现状是 `json.dumps(...) + "\n"` 配 `media_type="application/json"`——既不是 SSE，也不是任何有名字的东西，中间层没有任何理由不缓冲它。

**决定：线格式采用 AG-UI 协议，传输用 SSE。运行事件仍是自有领域类型，映射发生在 `encode_sse` 一处。**

## 为什么是 AG-UI 而不是自定义 schema

AG-UI 在 2025-05 由 CopilotKit 发布，2026 年已是既成事实：MIT、15.2k star、每三五天一个 release，[AWS 在 2026-03 给 Bedrock AgentCore Runtime 加了支持](https://aws.amazon.com/about-aws/whats-new/2026/03/amazon-bedrock-agentcore-runtime-ag-ui-protocol/)，[Microsoft Agent Framework 也写进了集成文档](https://learn.microsoft.com/en-us/agent-framework/integrations/ag-ui/)。它的事件分类与本项目要传的东西高度重合，`ag-ui-protocol` 0.1.19 只依赖 `pydantic`，并自带 `ag_ui.encoder.EventEncoder`——`encode()` 就是 `data: {json}\n\n`。

在一个已经收敛出标准的地方自创一套事件 schema，是评审第一眼就会问的问题。它不满足业务要求的那天再重构，成本远低于现在就替一个假想的未来买保险。

## 为什么领域层不直接用 AG-UI 的类型

因为运行事件有**四个下游**：前端、跨度写入、消息落库、评测回放。

AG-UI 的事件表里**没有用量、成本、跨度的位置**——那恰好是本项目的核心叙事。让 Runner 直接吐 AG-UI 类型，跨度写入器就得从 `Custom` 事件的无类型 `value` 里把用量捞回来：我们自己的核心数据，在自己代码读到之前先被编码进逃生口，方向是反的。另外两处具体的硌：`TOOL_CALL_ARGS` 传的是 JSON 字符串增量，而消息落库要的是拼装好的结构化入参；`CustomEvent.value` 是 `Any`，恰好在最该有类型的字段上丢掉 Pydantic。

所以 AG-UI 只做线格式。这不是重造轮子——没重造的是线格式，运行事件是 ADR-0008 已经定下的领域类型，本来就要存在，映射表是一处几十行的 `match`。

## 用量与跨度走 `Custom`

规范明确把 `Custom` 定为**有意的协议扩展**（application-defined semantics，并要求各家自行文档化），`Raw` 是给外来系统事件套壳的，文档里那个 `MetaEvent` 至今没进包。所以只剩 `Custom`，加命名空间前缀：

- `chatagents.usage`——一次模型调用完成时发：[模型角色](../../CONTEXT.md)、模型标识、输入/输出 token、[用量三态](../../CONTEXT.md)。
- `chatagents.span`——模型调用[跨度](../../CONTEXT.md)闭合时发：跨度标识、父跨度标识、类型、耗时。工具跨度不必自己发，`TOOL_CALL_START/END` 自带 `toolCallId` 足够关联。
- `chatagents.tool_result`——`tool_call_id` + 裁剪后的结构化结果 + 耗时 + 外部失败标记。

最后一个是 [ADR-0004](./0004-tools-are-capabilities-providers-are-implementations.md)「一份结果两个出口」在流里的落点。`ToolCallResultEvent` 带 `message_id` 和 `role="tool"`，它在 AG-UI 语义里**就是消息表里那条 tool 消息**，往它的 `content` 里塞 JSON 会让线上的消息序列与消息表对不上，而消息表存的是模型视角（[ADR-0001](./0001-messages-are-the-single-source-of-truth.md)）。于是渲染文本走 `TOOL_CALL_RESULT`、结构化走 `chatagents.tool_result`，各自流向各自的消费者。

**成本不进流**，理由与 [ADR-0002](./0002-business-and-observability-share-a-database.md) 定的不落库一致：成本是[推算](../../CONTEXT.md)不是[观测事实](../../CONTEXT.md)。

## 为什么 SSE 而不是 WebSocket

一次运行是服务端独白，客户端中途唯一想说的是"停"——而"停"就是挂断（`AbortController`），ADR-0008 已经把挂断定义成就地停。为一个能靠挂断表达的信号架双向通道是纯负担。

且 WebSocket 会撞坏已定的东西：它没有 HTTP 状态码，而 ADR-0008 的"流前失败走状态码、流后失败走 `RunFailed`"正建立在状态码上。顺带，OpenAI Responses 与 Anthropic Messages 两个上游本身就吐 SSE，AG-UI 默认也跑在 SSE 上——整条链路一种框帧。

## 后果

**消息标识必须确定性派生。** 一次运行产出多条助手消息（每次模型调用一条）与多条 tool 消息，数量运行时才知道，而 `TextMessageStartEvent` 每条都要 `message_id`。Runner 内部 `uuid4()` 会毁掉评测 L2 回放"同输入同事件流"的可断言性，所以只有运行标识由调用方预生成，消息标识一律 `uuid5(运行标识, 迭代序号[, 工具序号])` 派生。这让纯度是**结构性成立**的，而不是靠测试时记得注入假生成器。代价：**消息主键得是外部可生成的，不能是数据库自增**；[ADR-0001](./0001-messages-are-the-single-source-of-truth.md) 定的会话内 `seq` 排序不受影响，`seq` 仍由落库时分配。

**只吃 `@ag-ui/core`。** `@ag-ui/client` 会拖进精确钉死的 `rxjs` 7.8.1，而前端状态方案是 Zustand + TanStack Query，再进一套 RxJS 就是第二套状态范式共存；`@ag-ui/proto` 的 protobuf 用不上。流的消费自己写：`fetch` + `eventsource-parser` 3.1.0。不选 `eventsource` 4.1.1 是因为它实现完整 EventSource 语义**含自动重连**，而断连就地停的前提下自动重连会闷声重开一次运行、重复烧钱；不选 Vercel `ai` 是因为它自带整套 agent/model 抽象，与自建 `ModelPort` 正面冲突。

**zod 3 与 zod 4 会并存。** AG-UI 全线在 `zod ^3`，而 zod 当前是 4.4.3。只吃 `core` 是为把这个污染面压到最小。

**三个包钉精确版本，Renovate 单开一组、不自动合并。** 0.0.x 下 semver 不保证任何东西。前后端同版本号同发布，所以破坏性变更不需要兼容窗口，只需要一次同步升，由契约测试把门。

**33 个事件类型只发 15 种。** `THINKING_*`（被 `REASONING_*` 取代）、三个 `*_CHUNK`（那是给不知道消息边界的生产者的便利形态）、`STATE_*`（Agent 状态快照只写不读）、`MESSAGES_SNAPSHOT`（历史走 REST）、`ACTIVITY_*` / `RAW` 一律不发。`REASONING_*` 语义位留着但本期不发——原生 reasoning 的采集还没有票覆盖，现在发等于先定一个没人产出的格式。
