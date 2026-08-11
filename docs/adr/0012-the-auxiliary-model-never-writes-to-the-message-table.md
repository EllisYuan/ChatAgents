# 辅助模型永远不写消息表

[ADR-0005](./0005-long-documents-use-progressive-disclosure.md) 废除二级摘要之后，[模型角色](../../CONTEXT.md)里的 `tool` 就没有调用者了。[ADR-0008](./0008-a-run-emits-domain-events-not-wire-frames.md) 为此配了一条测试断言，防止"一条没有调用者的路径悄悄坏掉"。会话标题生成给了它第一个真实调用者，于是这个角色的名字与判据必须一次定清楚。

**决定：该角色更名 `auxiliary`，判据是它的输出永远不进入消息表。**

## 为什么不叫 `tool`

因为工具路径上一次模型调用都没有。[ADR-0004](./0004-tools-are-capabilities-providers-are-implementations.md) 把工具锁成 `web_search`(Tavily) 与 `web_reader`(Jina) 两个外部 HTTP 服务，[ADR-0005](./0005-long-documents-use-progressive-disclosure.md) 的渐进披露是**本地按标题切分**，二级摘要整块废除，`include_answer` 与 `include_raw_content` 关闭。从模型发出工具调用到结果回到它手里，中间没有任何模型参与。

一个跟工具毫无关系的角色叫 `tool`，代价是读 `role=tool` 跨度的人会以为那是工具调用的跨度——而 trace 面板正是本项目要给人看的东西。

## 为什么也不叫 `task`

Open WebUI 用 `TASK_MODEL` / `TASK_MODEL_EXTERNAL` 指代这类模型，是聊天 UI 产品里最通行的叫法。本项目不能用，因为它在这里撞车两次：

- **agent 词汇内部**：「任务」已经指用户交给 agent 的活。`CONTEXT.md` 给「运行」写的 `_Avoid_` 列表（请求、轮次、turn、执行）就是在防这类混淆，再引入一个「任务模型」是自己拆自己的台。Open WebUI 没这个问题，因为它是聊天界面而不是 agent 框架。
- **ML 文献**：`task-specific model` 指为单一任务微调过的窄模型，意思与"随便配什么模型都行的槽位"相反。

顺带一个旁证：Open WebUI 的 [#12351](https://github.com/open-webui/open-webui/issues/12351) 正在要求把「工具用的模型」从 `TASK_MODEL` 里拆出来——一个笼子装太多杂活，最后还是要分。本项目结构上避开了这一步（工具不调模型），不必重走。

## 判据是输出去向，不是模型大小

业界谈这个槽位时习惯说"用个更小更快的模型省钱"。那是**用法**，不是**定义**——本项目允许把它配成任何模型，判据必须与型号无关：

| | `main` | `auxiliary` |
|---|---|---|
| 输出进不进消息表 | **进** | **永不进**，产物落别处 |
| 在不在 ReAct 循环里 | 在，反复调工具 | 单次 request/response，无工具、无循环 |
| 用户读不读它的输出 | 那就是回答本身 | 系统自用的元数据 |
| 失败后果 | 运行失败 | 降级回落，运行照常 |

第一条是结构性的，其余三条是它的推论。[ADR-0001](./0001-messages-are-the-single-source-of-truth.md) 定了消息表是对话记忆的唯一事实来源；`main` 写它，`auxiliary` 碰不到它。两者因此不是"大模型与小模型"，是两类根本不同的调用——把判据写成大小快慢，等于把一条可检查的结构约束换成一句品味描述。

## 第一个调用者：会话标题生成

时机取 `immediate`——与回答**并行**发起，只吃用户首条消息。LibreChat 的 `titleTiming` 默认就是它，`final`（等完整回答）已被标为 legacy；Open WebUI 则是回答后的后台任务。

但选它的决定性理由在观测这边，不在跟风。标题跨度要挂在某个[运行](../../CONTEXT.md)上，而 `final` 的标题生成发生在运行收尾之后：要么往一个已经写好 `ended_at` 的 run 里补挂跨度，要么给 `obs.run` 加 `kind` 字段让标题自成一个 run——两条都是为了迁就时机而弄脏数据模型。`immediate` 让它天然落在运行的生命周期内，就是主运行下的一条兄弟跨度，与 [ADR-0004](./0004-tools-are-capabilities-providers-are-implementations.md) 已定的"并发工具调用呈现为时间轴上的兄弟跨度"同形。

**因此「运行」的定义放宽为"ReAct 推理及与之并行的辅助调用"**，而不是只有 ReAct 那一段。

生成失败时回落到截断首条用户消息前 30 字，并如实记一条错误跨度。业界两家在这里都是"log 一下，就没有标题"——那在每用户私有的列表里无所谓，在一个全局公开的列表里就是一条没有标识的记录。按 [ADR-0006](./0006-tool-failures-split-into-external-and-programmatic.md) 的二分，这是外部失败，不中止运行。

## 只有一个槽位，不按用途分裂

LibreChat 走的是另一条路：不设通用角色，按用途分字段（`titleModel`、`titleEndpoint`）。本项目不采纳——配置面每多一个用途就多一个键，而前端高级选项已经要同时承载"用户密钥还是服务端预设"这一维，再叠一维会把界面变吵。

**全系统自始至终只有两个模型槽位：`main` 与 `auxiliary`。** 将来若出现第二个辅助调用者（查询改写、结果重排、结构化抽取），它复用同一个槽位；那三项目前一个都没决定要做，现在不为它们预留任何东西。

## 后果

- `obs.span` 的物化真列 `role` 取值为 `main` / `auxiliary`；用量按角色分别归属。
- [ADR-0008](./0008-a-run-emits-domain-events-not-wire-frames.md) 末尾那条断言改为断言 `auxiliary` 解析出的模型标识非空且零配置下等于 `main`——它现在守的不再是一条空路径，而是标题生成的必经之路。
- 配置键 `auxiliaryModel`，YAML 端点文件与前端高级选项同名。**它只是一个模型标识，不是一份独立的端点档案**——两个角色共用同一个协议、base URL 与鉴权（见 [ADR-0014](./0014-the-model-is-chosen-by-the-user-never-by-the-system.md)）。
- 零配置下 `auxiliary` 跟随主模型，意味着一个 30 字的标题可能由 reasoning 模型生成，账单不小。**这个成本不隐藏**——它在 trace 里按角色单独列账。隐形辅助调用吃掉的钱是 LLM 应用里真实存在的黑洞，本项目的立场是把它照出来，而不是藏起来或替用户做主关掉它。
