# 后端按能力模块分层，不按技术层

`app.py` 一个文件 592 行，其中 `stream_agent` 一个函数 356 行：密钥提取、LLM 构造、提示词选择、agent 构建、250 行内联流式解析、`finally` 里的会话落盘全在里面。后果不是"不好看"，是**没有任何一块可以脱离 FastAPI 单独测试**。

**决定：按能力模块切分，模块内四层。** 判据是可测试性，不是像不像大厂。

```
backend/src/chat_agents/
├── main.py          # FastAPI 装配、lifespan、middleware、异常映射。唯一的组装处
├── config.py        # pydantic-settings：环境变量 + YAML 端点配置文件
├── database.py      # engine / session_factory / Base / app 与 obs 两 schema
├── exceptions.py    # ChatAgentsError 根类
│
├── conversation/    # 会话与消息
├── agent/           # ReAct Loop、AgentState、提示词、工具执行器
├── llm/             # 端点档案、ModelPort、三协议适配器、模型发现
├── tools/           # web_search / web_reader
└── observability/   # 跨度、trace 查询、用量聚合
```

模块内四层：`router.py`（HTTP ↔ 领域类型，不含业务）→ `service.py`（规则、编排、事务边界）→ `repository.py`（查询，不含规则、不开事务）→ `models.py`（ORM）。

## 为什么不按技术层切

`api/` + `services/` + `repositories/` 是更常见的起手式，但它在这个项目里有一处硬伤：[ADR-0002](./0002-business-and-observability-share-a-database.md) 要求业务模块不得 import 观测模块，而**那是一条模块边界，不是层边界**。按技术层切，`services/` 里同时住着会话服务与跨度写入器、`repositories/` 里同时住着消息表与跨度表——这条纪律在目录上完全看不见，只能靠 code review 盯。按能力切，它退化成一条 import 规则，CI 可强制。

依赖方向因此是单向的：

```
llm/            零依赖
tools/          零依赖
conversation/  ─→ llm            （只为 ModelMessage 类型）
agent/         ─→ llm, tools, conversation
observability/ ─→ agent, conversation, llm      ← ADR-0002 允许的方向
main.py        ─→ 全部
```

`llm/` 对整个项目零依赖，因此三协议契约测试可以完全独立跑，不需要数据库、不需要 FastAPI。

模块名 `llm/` 而非 `models/` 是刻意的：`models` 在 Python web 生态里约定俗成指 ORM，占用它会让每个新读者误解一次；而 `llm/` 一眼说明这个项目是什么。ORM 因此保住 `<module>/models.py` 这个业界通行的位置。

## repository 层保留

一度考虑省掉——理由是"repository 的卖点是测试时换内存实现，而 ADR-0002 已定 CI 用真库"。**这条理由不成立**：CI 走 repository 打到真库，数据一样是真的。

真正的判据是查询复杂度，而这个项目有两处复杂查询：**用量聚合**（按模型、按[模型角色](../../CONTEXT.md)、按时间窗聚合并剔除 `partial`）与**消息 ↔ 运行的圈定**（ADR-0002 禁了消息表上的 `run_id`，只能靠 `trigger_message_id` + `last_message_seq` 跨 schema 反查）。后者尤其说明问题：那段逻辑写在哪儿，哪儿就得懂一条不显然的建模约束，散落各处等于每个人重新理解一遍。

还有一条独立理由：**软删除**。ADR-0002 定了会话删除是软删、查询默认过滤，若 `deleted_at IS NULL` 散在各处的 inline 查询里，迟早有人漏写。repository 是那个不可绕过的落点。

四条护栏防止它长成过度设计：

1. **不定义抽象基类或 Protocol。** 只有一个实现，抽象是纯负担。
2. **通用取数方法（`get_session` / `list_messages`）尽管有，用例方法只留给复杂查询，但不要泛化查询构造器**（`find(**filters)`）。后者让软删除过滤守不住、查询无法建索引、类型全丢，且本质上是在包一层 SQLAlchemy 已经提供的东西。
3. **只放数据访问。** 悬空工具调用的修复、截断策略、标题生成全归 `service.py`。
4. **不开事务、不 commit**，只收 session。

全项目约 13 个 repository 方法，其中只有 2 个是用例专用的复杂查询。

## Session 生命周期分两套

| 端点 | 策略 |
|---|---|
| 会话 CRUD | 常规 `Depends(get_db)` 请求级 session |
| 流式运行路径 | **不用请求级 session**，每次写入自己开短事务 |

FastAPI 0.118.0 起 `yield` 依赖的收尾在响应发送之后执行，所以请求级 session **能**在整个流式响应期间保持打开——但那正是问题所在。一次运行含多次模型调用与工具往返，几十秒起步，请求级 session 意味着这几十秒死死占住连接池一条连接；demo 公开、并发不可控，被拖死的是那些毫秒级的 CRUD 请求。

短事务同时让 ADR-0002 的纪律变成代码的形状：业务写入与观测写入各自 `async with session_factory()`，**物理上不可能同事务提交**。这一条不再需要人记住。

## 其他被否决的方案

**引入 DI 容器**（dishka 一类）。`app.dependency_overrides` 已经解决了测试替换，容器在这个体量下是纯负担。只用 FastAPI 原生 `Depends` + `Annotated`；全局单例 `get_session_manager()` 删除。

**`evals/` 提到仓库根**。evals 的五层里 L1–L4 全部 import `chat_agents`，独立成第二个 Python 项目只是把 import 问题换成打包问题。落在 `backend/tests/evals/`，用 pytest marker（`-m "not eval"` 默认不跑付费层）区分运行时机——用目录解决运行时机问题是拿错工具。

## 后果

**异常层次只有五个类**：`AuthenticationFailed` / `ModelNotFound` / `UpstreamUnavailable` / `ProtocolError` / `SessionNotFound`，判据是"调用方是否需要区分处置"，不是"失败有多少种"。领域异常不继承 `HTTPException`，映射在 `main.py` 一处。两处裸 `except:` 禁掉。

**日志与 trace 分工**：凡是"一次运行内部发生了什么"归跨度，日志只记跨运行的系统事件。现状每个流式事件打一条 INFO 且**日志里含模型输出的文本内容**，整块删除。流式路径的日志量从每 token 一条降到一次运行 0~1 条。日志带运行标识，与 trace 对得上。

**密钥的暴露面收敛成三行**：`SecretStr` 挡住误打印，唯一解密处是三个适配器里拼 HTTP header 的那一行。代价是这依赖序列化的默认行为而非结构性隔离，因此"扫 `obs.spans` 的 `attributes` 不含密钥"这条 CI 断言是**必做项**，不是锦上添花。
