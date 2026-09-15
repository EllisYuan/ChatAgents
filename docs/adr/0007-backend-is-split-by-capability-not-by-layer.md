# 后端按能力模块分层，不按技术层

**决定：后端架构按能力模块切分，模块内四层。** 判据是可测试性，不是像不像大厂。

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

`api/` + `services/` + `repositories/` 是常见的技术分层方式，但它无法表达本项目最重要的一条边界：根据 [ADR-0002](./0002-business-and-observability-share-a-database.md)，业务模块不得依赖观测模块。这个约束区分的是**能力模块**，不是技术层；如果按技术层组织，会话服务与跨度写入器都会落在 `services/`，消息查询与跨度查询也都会落在 `repositories/`，目录本身无法看出两者不能互相依赖。

因此，后端按能力模块组织：`conversation/`、`agent/`、`llm/`、`tools/` 和 `observability/` 各自拥有自己的 `router.py`、`service.py`、`repository.py` 与 `models.py`（适用时）。模块之间的边界由 import 方向表达，并由 Import Linter 在 pre-commit 和 CI 中强制执行（见 [ADR-0034](./0034-invariants-are-enforced-not-documented.md)）。

### 当前的模块依赖

以下是当前实现中能力模块之间的**直接 import 边**；箭头表示“左侧模块 import 右侧模块”，不表示运行时调用顺序，也不表示传递依赖。

```text
llm/           ─→ 共享叶子
tools/         ─→ 共享叶子
agent/         ─→ llm/, tools/
conversation/  ─→ agent/, llm/
observability/ ─→ agent/, llm/
transport/     ─→ agent/, llm/
eval_summary/  ─→ llm/
```

`main.py` 是唯一的组装入口，直接连接各个需要暴露或编排的模块；它不直接 import `tools/`，tools 由 `agent/` 使用。能力模块还可以依赖基础设施和共享叶子，例如：

- `db/`、`database.py`：持久化基础设施；
- `validation.py`、`token_estimation.py`、`model_catalog.py`、`exceptions.py`：无业务方向的共享叶子。

这些依赖不属于能力模块之间的边界关系，因此不放进上面的主图。

### 这条方向要保护什么

这里要保护的不是“模块之间完全没有依赖”，而是依赖不能反向穿越能力边界。尤其是：

- `llm/` 不得 import `agent/`、`conversation/`、`observability/`、`tools/` 或 `transport/`；
- `tools/` 不得 import `agent/`、`conversation/`、`llm/` 或 `observability/`；
- 业务模块和传输模块不得依赖 `observability/`。

这样，`llm/` 和 `tools/` 才能保持为独立的共享叶子。三协议契约测试可以在不启动数据库和 FastAPI 的情况下运行，tools 也不需要反向依赖 Agent 或具体的观测实现。

`conversation/ → agent/` 和 `observability/ → agent/` 是有意保留的正向依赖。前者由 `conversation/streaming.py` 中的 `persist()` 消费 `agent/events` 的领域事件类型；后者由观测模块消费 Agent 运行事件并写入 trace。Agent 只负责产出事件，不需要知道消息持久化或观测实现。

这段描述以当前代码为准；早期草案中的依赖方向曾与实现不一致，后续按实测代码修正了 ADR，而没有为了匹配旧文字搬迁领域类型。

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

## Database Session 生命周期分两套

| 端点 | 策略 |
|---|---|
| 会话 CRUD | 常规 `Depends(get_db)` 请求级 session |
| 流式运行路径 | **不用请求级 session**，每次写入自己开短事务 |

FastAPI 0.118.0 起 `yield` 依赖的收尾在响应发送之后执行，所以请求级 session **能**在整个流式响应期间保持打开——但那正是问题所在。一次运行含多次模型调用与工具往返，几十秒起步，请求级 session 意味着这几十秒死死占住连接池一条连接；demo 公开、并发不可控，被拖死的是那些毫秒级的 CRUD 请求。

短事务同时让 ADR-0002 的纪律变成代码的形状：业务写入与观测写入各自 `async with session_factory()`，**物理上不可能同事务提交**。这一条不再需要人记住。

## 后果

**异常层次只有五个类**：`AuthenticationFailed` / `ModelNotFound` / `UpstreamUnavailable` / `ProtocolError` / `SessionNotFound`，判据是"调用方是否需要区分处置"，不是"失败有多少种"。领域异常不继承 `HTTPException`，映射在 `main.py` 一处。两处裸 `except:` 禁掉。

**日志与 trace 分工**：凡是"一次运行内部发生了什么"归跨度，日志只记跨运行的系统事件。现状每个流式事件打一条 INFO 且**日志里含模型输出的文本内容**，整块删除。流式路径的日志量从每 token 一条降到一次运行 0~1 条。日志带运行标识，与 trace 对得上。

**密钥的暴露面收敛成三行**：`SecretStr` 挡住误打印，唯一解密处是三个适配器里拼 HTTP header 的那一行。代价是这依赖序列化的默认行为而非结构性隔离，因此"扫 `obs.spans` 的 `attributes` 不含密钥"这条 CI 断言是**必做项**，不是锦上添花。
