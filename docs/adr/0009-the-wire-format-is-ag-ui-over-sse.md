# 线格式说 AG-UI，跑在 SSE 上

**线格式采用 AG-UI 协议，传输用 SSE。运行事件仍是自有领域类型，映射发生在 `encode_sse` 一处。**

## 为什么是 AG-UI 而不是自定义 schema

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

**消息标识必须确定性派生。** 一次运行可能生成多条助手消息（每次模型调用一条）和多条 tool 消息，具体数量只有运行过程中才能确定；但每条 `TextMessageStartEvent` 都必须携带 `message_id`。如果 Runner 内部调用 `uuid4()`，评测 L2 回放就无法断言“同输入产生同一事件流”。因此，只有运行标识由调用方预先生成，其他消息标识都按 `uuid5(运行标识, 迭代序号[, 工具序号])` 确定性派生。这样，纯度由实现结构保证，不依赖测试时记得注入假生成器。代价是：**消息主键必须支持外部生成，不能使用数据库自增**；[ADR-0001](./0001-messages-are-the-single-source-of-truth.md) 规定的会话内 `seq` 排序不受影响，`seq` 仍在落库时分配。

**只引入 `@ag-ui/core`。** `@ag-ui/client` 会引入固定版本的 `rxjs` 7.8.1，而前端已经采用 Zustand + TanStack Query 作为状态方案；再引入 RxJS，就会让两套状态范式并存。`@ag-ui/proto` 提供的 protobuf 在本项目中也用不上。因此，流的消费由我们自行实现：使用 `fetch` 加 `eventsource-parser` 3.1.0。不选 `eventsource` 4.1.1，是因为它实现了完整的 EventSource 语义，**包括自动重连**；在断连即停的前提下，自动重连可能悄悄重新启动一次运行，造成重复消耗。也不选 Vercel `ai`，因为它自带完整的 agent/model 抽象，与自建的 `ModelPort` 正面冲突。

**zod 3 与 zod 4 会并存。** AG-UI 全线依赖 `zod ^3`，而本项目当前使用的是 zod 4.4.3。只引入 `@ag-ui/core`，可以把这两套版本共存带来的污染面压到最小。

**三个包固定精确版本，Renovate 单独成组且不自动合并。** 在 0.0.x 阶段，semver 并不能提供可靠的兼容性保证。前后端使用同一版本号并同步发布，因此破坏性变更不需要兼容窗口，只需要一次同步升级，并由契约测试把关。

**33 个事件类型中只发送 20 种。** `THINKING_*`（已被 `REASONING_*` 取代）、三个 `*_CHUNK`（面向无法确定消息边界的生产者提供的便利形态）、`STATE_*`（Agent 状态快照只写不读）、`MESSAGES_SNAPSHOT`（历史消息通过 REST 获取）以及 `ACTIVITY_*` / `RAW` 一律不发送。原生 reasoning 的采集已有明确决定：七个 `REASONING_*` 中发送五个，只不发送 `REASONING_MESSAGE_CHUNK` 和 `REASONING_ENCRYPTED_VALUE`。
