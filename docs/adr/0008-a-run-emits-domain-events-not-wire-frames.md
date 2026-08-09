# 一次运行只产出领域事件，不产出线格式

现状 `stream_agent` 里 250 行内联流式处理，同时干着四件事：解析模型输出、拼 SSE 帧、累积完整回答、在 `finally` 里落盘会话。四件事纠缠在一个生成器里，改任何一件都要读懂其余三件。

**决定：[运行](../../CONTEXT.md)的唯一产物是[运行事件](../../CONTEXT.md)流。** `AgentRunner` 是纯的——收一份消息序列与[端点档案](../../CONTEXT.md)，吐一串领域事件，**不碰数据库、不碰 HTTP、不知道 SSE 存在**。

```python
class AgentRunner:
    async def run(self, messages: list[ModelMessage],
                  main: EndpointProfile, tool: EndpointProfile
                  ) -> AsyncIterator[RunEvent]: ...
```

落库与编码由包装器承担，组装发生在 `main.py` 一处：

```python
encode_sse(              # 传输层：领域事件 → 线格式
    observe(             # observability/：落跨度，独立事务，失败只记日志
        persist(         # conversation/：落消息，业务事务，失败要报错
            runner.run(messages, main_profile, tool_profile))))
```

## 为什么 Loop 不能直接产 SSE

因为一次运行的产物有**三个下游**：前端、跨度写入、消息落库，加上评测回放是第四个。Loop 直接产 SSE 只剩两条路，两条都是死的。

**让下游解析 SSE**——跨度写入器要从 `data: {...}` 里反解出结构再落库。荒谬。

**Loop 自己扇出**，直接调跨度写入器与消息服务——这直接违反 [ADR-0002](./0002-business-and-observability-share-a-database.md) 的"业务不得 import 观测"，而那条之所以存在，是因为它下面还挂着"观测写入走独立事务、失败只记日志"。Loop 里写一行 `await span_writer.write(...)`，这条纪律就退化成调用方自觉。

领域事件流正是那个不靠自觉的机制：Loop 不知道有没有人在听，观测订阅者自己开自己的事务、自己吞自己的异常。

## 为什么不用依赖倒置

本来准备让 `agent/` 定义一个 `RunObserver` Protocol、由 `observability/` 实现、`main.py` 注入。**不需要**——ADR-0002 允许的依赖方向恰恰是 `obs → app`，所以让 observability 直接包装事件流即可。`agent/` 里没有任何一行知道观测存在，也没有 Protocol、没有注册表、没有容器。

[ADR-0004](./0004-tools-are-capabilities-providers-are-implementations.md) 说"跨度记录归[工具执行器](../../CONTEXT.md)"与此不冲突：执行器仍是发出工具事件的唯一入口，责任集中点没有变化，只是它发出的是事件而非跨度。层级标识由 agent 生成并随事件带出，observability 负责把它映射成跨度树。

## 为什么 Runner 必须是纯的

因为评测的 L2 回放层要在没有网络、没有数据库的情况下跑完整个 Loop。Runner 纯的话，一条 eval case 就是"喂一份 JSON 序列进去、断言吐出来的事件流"；Runner 自己读库的话，每条 case 都得先在库里摆好一个会话。

代价是 Runner 不能在运行中途决定"我想多读点历史"。这不是损失——输入序列本来就该在开跑前确定，运行中途改记忆是 [ADR-0001](./0001-messages-are-the-single-source-of-truth.md) 明确推翻的 checkpointer 那套。

因此**"从消息表重建模型输入序列"归 `conversation/service.py`**，不归 agent。

## 事件粒度分两级

`ModelEvent`（`llm/` 产出）是**一次模型调用**内部的事件；`RunEvent`（`agent/` 产出）是**一次运行**的事件，一次运行含多次模型调用与多次工具往返。ReAct 的多轮结构正好活在两者的差里。

两级看似重复（都有 `TextDelta`），但 `ToolStarted` / `ToolFinished` / `RunCompleted` / `RunFailed` 在模型调用层面根本不存在。重复的只有一个字段名，不是一套平行体系。不做 1:1 机械转发。

## 客户端断连：就地停

`sse-starlette` 在客户端断连时取消整个生成器任务，想让生产者跑完得自己脱离它的 task group。**不这么做**——断连本身就是诚实的观测事实，[用量三态](../../CONTEXT.md)已为它准备好语义（`PARTIAL`），运行加一个中止状态即可。一次被掐断的运行，trace 显示它被掐断了，比伪造一个"跑完了"更符合本项目的观测哲学。demo 公开无防刷，反复开关标签页就能持续烧钱的方案也不该选。

**配套：消息与跨度增量落库，不攒到最后一把写。** 若落盘在生成器的 `finally` 里，被取消时收尾代码本身就在被拆的 task group 中，得靠 `asyncio.shield` 硬保，脆且难测。改成每个跨度闭合即写、每次模型调用完成即写消息，取消就只损失最后一个未闭合的跨度。这本就是 ADR-0002 选 PostgreSQL 而非 SQLite 的理由——"流式期间是持续写入"。

## 悬空的工具调用在读时修复

运行若在"模型吐出工具调用"与"工具返回结果"之间断掉，消息表里就留下一个没有配对结果的工具调用。下一轮重建序列喂给模型时，**Anthropic 与 OpenAI 都会直接报错**——两家都要求每个工具调用必须有配对结果，Anthropic 还要求结果必须紧跟在下一条消息里。这不是观测残缺，是下一轮对话直接挂掉。而且服务器重启、进程被杀一样制造悬空，躲不掉。

**决定：消息表如实留下那个没有结果的调用，重建函数在投影时补上合成结果**，用协议原生的错误标记（Anthropic 的 `is_error`）加一句事实描述。

**不写"请重新调用"一类指令性文案。** 消息表是事实来源，掺入行为诱导会让后来读表的人（包括评测回放）以为真有人这么说过；有协议原生字段就不该用自然语言下指令；而且替模型决定该不该重试，恰恰放弃了 ReAct 的价值——工具本身挂了或参数不合法时，重试只是再错一次。

修复放在读时而非断连时，是因为它零写入路径改动（不需要 `asyncio.shield`）、一处覆盖所有成因，且与 ADR-0001 已确立的手法一致——那份 ADR 已定"UI 的折叠中间步骤由查询时过滤实现，而不是靠不存"。

## 后果

**错误按"流是否已开始"分成两类。** 流式响应发出第一个字节后 HTTP 状态码就定死是 200，之后再出错也改不了。因此：流开始前的失败（档案校验、模型标识校验、会话存在性）走正常 HTTP 状态码；流开始后的失败走 `RunFailed` 事件。由此得到一条纪律——**所有能提前做的校验必须在返回流式响应之前做完**，因为流里的失败前端处理起来麻烦得多，且 200 的响应在监控上看着是成功的。

**[模型角色](../../CONTEXT.md)的两个档案都必须解析出结果。** [ADR-0005](./0005-long-documents-use-progressive-disclosure.md) 废除二级摘要后，`tool` 角色当前没有调用者，但它仍是配置契约的一等公民：服务端预设与用户自定义两层都必须能指定，解析结果不为空，零配置下跟随主模型。配一条测试断言这一点，否则一条没有调用者的路径迟早悄悄坏掉。
