# 契约有两个来源：AG-UI 管信封，OpenAPI 管载荷

> **编号说明**：本文与同批的 0022–0024 从 0021 起编，跳过 0017–0020。原因是 `docs/context-truncation`（#25）与 `docs/native-reasoning`（#31）两条分支**各自都占用了 0017 与 0018**，且两条都尚未合入 main——撞号要到合并时才会暴露。本文凡需引用那两批结论处，一律链到对应 issue 而非 ADR 文件，以免在重编号后留下死链。

[ADR-0009](./0009-the-wire-format-is-ag-ui-over-sse.md) 定了线格式吃 AG-UI。[#11](https://github.com/EllisYuan/ChatAgents/issues/11) 定了契约不落盘、由 CI artifact 传递，代价是**失去了 `git diff` 基线**——仓库里没有可比对的契约文件，防漂移只能另找机制。

**决定：契约由两个来源共同构成——AG-UI 的 schema 定义流式事件的信封，`app.openapi()` 定义非流式 REST 面与三个自有载荷。两者之外没有第三处，任何手写的类型副本都是漂移源。**

## 为什么 schema-first 不在选项里

契约的单一事实来源只可能是后端代码。schema-first（先写一份 schema，两侧各自生成）需要那份 schema 作为入库文件存在，与 #11 的「不落盘」直接矛盾。重开这个选项等于推翻 #11。

代价必须写明：**契约的表达力上限就是 FastAPI 能从 Pydantic 模型推出来的东西**。写不出「这个字段在 A 情况下必有、B 情况下必无」这类跨字段约束。本文档中凡是 schema 表达不了的约束，都在下面点名了它对应的执行机制。

## 为什么流式面进不了 OpenAPI

实查（2026-08-13）：FastAPI 0.141.1 的 `openapi_version` 硬编码为 `"3.1.0"`。而描述 SSE 流中每个事件的形状需要 OpenAPI **3.2.0** 才引入的 `itemSchema`。下游同样没跟上——`openapi-typescript` 7.13.0 只支持 3.0/3.1。

所以 `POST /api/runs` 在 OpenAPI 里只能登记成「返回 `text/event-stream`」，事件形状在契约里无处安放。

考虑过在 CI 里 dump 完 3.1 再用脚本注入 `itemSchema` 并改写 `openapi` 字段——否掉了：那是一段无人维护的自造胶水，换来的产物下游生成器还读不了。

**认定 AG-UI 的 pydantic/zod schema 本身就是契约的一部分**，则这个洞不是洞。前端 `@ag-ui/core` 的类型与后端 `ag_ui.core` 的类型来自同一个包的同一次发布，它们对得上不是碰巧，是**上游替我们保证的**。三个包钉精确版本这条（ADR-0009 已定、#17 承接）因此不只是稳定性措施，它是这条契约成立的前提。

## 三个自有载荷：上游不管的那部分

AG-UI 的 `CustomEvent` 只约束信封 `{name, value}`,`value` 是 `Any`。本项目的三个自有载荷——`chatagents.usage`、`chatagents.span`、`chatagents.tool_result`——因此是**整份契约里唯一无人替我们把关的部分**。

**解法：把三个载荷定义成后端的 Pydantic 模型，注入进 `app.openapi()` 返回的 `components.schemas`，即使没有任何路径引用它们。**

实查确认这条可行（2026-08-13，读 `openapi-typescript` 源码 `transform/components-object.ts`)：它对 `components` 下各集合的迭代**没有任何基于引用的过滤**，循环是 `for (const [name, item] of getEntries<SchemaObject>(componentsObject[key], ctx))`。无路径引用的 schema 照常生成 TS 类型。`app.openapi()` 返回可修改的 dict、结果缓存在 `app.openapi_schema`，是 FastAPI 文档化的扩展模式。

买到的是：三个载荷走的是**和 REST 面同一条流水线、同一个单一事实来源**，因此同样漂移不了。前端拿生成的类型去断言 `CustomEvent.value`。

## 请求侧不吃 AG-UI

AG-UI 有官方请求类型 `RunAgentInput`，字段为 `thread_id` / `run_id` / `parent_run_id` / `state` / `messages` / `tools` / `context` / `forwarded_props` / `resume`。

**不吃。** 其中 `messages` / `state` / `tools` 假定**客户端持有会话状态**并把整个历史随请求送上来，而 [ADR-0001](./0001-messages-are-the-single-source-of-truth.md) 定的是消息表在服务端、每轮重建。吃它就得让这三个字段恒为空数组，等于在契约里摆三个骗人的字段。

判据与 [#31](https://github.com/EllisYuan/ChatAgents/issues/31) 拒发 `REASONING_ENCRYPTED_VALUE` 完全相同：AG-UI 那部分设计假定客户端持有状态，本项目定的是服务端持有。

**「吃 AG-UI」这个决定的精确范围是「响应事件流」，不是「整个协议」。** 响应侧吃标准是因为它的事件表确实描述了我们要发的东西；请求侧不吃是因为它描述的是另一种架构。这一条写死在这里，否则下一个读到的人会把只吃一半当成疏忽去「补全」。

请求体因此自造。运行标识**由后端生成**并在 `RUN_STARTED` 里回传——让客户端指定它，等于把 [ADR-0009](./0009-the-wire-format-is-ag-ui-over-sse.md) 定的 `uuid5` 确定性派生的根交给调用方，还能被人为撞号。

## 命名法：自有的一律 snake_case

AG-UI 的 `ConfiguredBaseModel` 配了 `alias_generator=to_camel`，而 `EventEncoder` 调的是 `model_dump_json(by_alias=True)`——**它的线上字段是 camelCase**(`threadId`、`toolCallId`)。本项目的 Pydantic 模型默认吐 snake_case。

结果是同一条 SSE 流里两种命名法并存：**信封 camelCase、`value` 里的自有载荷 snake_case**。

**接受这个不对称，自有部分一律 snake_case。** 给三个载荷单独配 camelCase 别名，等于在那条唯一的流水线中间插一个只对三个模型生效的例外，而例外正是漂移的温床。全项目改 camelCase 则要给每个出参模型挂别名配置，把成本摊到所有地方去换一个视觉一致。

这个不对称**本来就存在且无法消除**——AG-UI 的信封不归我们管。#10 已经交给前端一个同类的不对称（跨度树由 `chatagents.span` 与 `TOOL_CALL_START/END` 两处拼出），再多一个是同一笔账。

**这条必须有契约测试守**：断言三个载荷是 snake_case。否则将来有人「顺手」加别名让载荷跟信封对齐，TS 类型就与线上实际数据脱节——而那是 `tsc` **抓不到**的漂移，因为类型来自 schema、schema 也跟着改了，两边一致地错。

## 防漂移的三层

失去 diff 基线后，防漂移由三层承担，各管一件事：

1. **`tsc --noEmit`** —— 前端 CI 下载 schema artifact、跑 `openapi-typescript`、编译。前端引用了后端已改名的字段，当场红灯。这是主力，且零额外机制。
2. **运行时契约测试**(Schemathesis 4.24.3，支持 3.1、可 pytest 集成）—— 管「后端违反自己的契约」，即响应体与声明的模型不符。**只打非流式 REST 面**，在 CI 里打本地起的服务 + 真 Postgres(#9 已定测试要真库）,**不打中转站**。
3. **手写的载荷断言** —— 三个 `Custom` 的 `value` 逐字段断言，含上面那条命名法断言。这是唯一必须手写的一层，因为 AG-UI 不约束 `value`。

注意与**三协议契约测试**区分：那个打真实中转站、断言形状不断言标识([ADR-0016](./0016-the-model-list-is-discovered-and-persisted.md) 已警告清单会漂移）,`llm/` 对全项目零依赖([ADR-0007](./0007-backend-is-split-by-capability-not-by-layer.md))正是为了它能独立跑。**本 ADR 管的是「我们的 API 对前端的契约」，不是「上游对我们的契约」**，两者容易混为一谈。

## 后果

- 生成的 `.ts` 与 schema artifact 都不入库（#11 已定）。仓库里因此看不到契约文件，读者只能从 CI 配置看出这个项目有正式契约。
- **错误码词表流前流后共用这条，schema 层面无从校验**——流前是 RFC 9457 响应体的 `type` 成员，流后是 `RUN_ERROR.code`，而后者在 OpenAPI 里根本没有位置。它只能靠一条契约测试守：断言词表是单一常量来源、两条路径都从它取值。这条测试不是加分项，是这条决定唯一的执行机制。
- **本项目几乎不会返回 401。** [ADR-0015](./0015-upstream-errors-pass-through-unclassified.md) 已定密钥有效性无法提前校验（除非每次运行多发一次探测请求去买一个更漂亮的错误码），而流一旦开始 HTTP 状态码就已经发出去了。所以用户填错密钥，拿到的是 **200 + 一个 `RUN_ERROR` 事件**。这个反直觉的结果记在这里，否则会被当成 bug 提。
- 工具供应商密钥(Tavily / Jina)**不进契约**，只走服务端。「两层密钥来源」那条规则从头到尾说的是模型接入层，工具侧从未被覆盖。现状 `app.py:120` 没有 Tavily key 直接 400，零配置跑不起来。让访客先去注册 Tavily 才能问第一个问题，是在零配置体验前面立一道墙，换来的只是省下站长自己的搜索额度——而那正是「只追踪不限制」明确放弃的东西。模型密钥可填是因为用户可能想用自己的模型，工具没有这个诉求。
- 现状那四个 `X-*-Key` header 整块退场（#13 已定用户自定义走请求体不走 header)。
