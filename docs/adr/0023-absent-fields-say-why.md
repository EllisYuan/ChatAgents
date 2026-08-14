# 没有值的字段要说明为什么没有

五张票各自交办了一种「这个字段是空的」，而它们的含义完全不同：

| 出处 | 空的含义 |
|---|---|
| [#9](https://github.com/EllisYuan/ChatAgents/issues/9) | 用量不完整或不可用——**且明令不得表示为 0** |
| [#31](https://github.com/EllisYuan/ChatAgents/issues/31) | 显示摘要**已老化**（曾经有，被 [ADR-0003](./0003-span-table-follows-phoenix.md) 的分级老化清掉了） |
| [#31](https://github.com/EllisYuan/ChatAgents/issues/31) | **Chat Completions 恒无推理**——这个协议下永远不会有 |
| [#31](https://github.com/EllisYuan/ChatAgents/issues/31) | 往返载荷在运行终态就地清空 |
| [#15](https://github.com/EllisYuan/ChatAgents/issues/15) | 模型清单是 `fallback`，不是发现来的 |

#31 说得很直白：契约要能表达「已老化」，否则前端无法把它与「从来没有」区分开。若五处都用 `null`，前端只能靠猜——而猜错的表现是把「过期了」显示成「出错了」，那正是 #18 交办里点名要避免的。

**决定：凡是「可能没有值」的字段，都配一个说明为什么没有的状态字段，取值来自共用词表；而结构性不存在的字段不配状态，根本不出现在响应里。**

## 两类「没有」

**结构性不存在** —— 对这个协议、这个口径、这次调用而言永远不会有。典型是 Chat Completions 下的推理 token（[#31](https://github.com/EllisYuan/ChatAgents/issues/31) 定了这个协议一概不采）、以及成本（[ADR-0003](./0003-span-table-follows-phoenix.md) 定了不落库）。

这类字段**根本不出现在响应里**。摆一个恒为 `null` 的字段是在骗人：读者会以为「这次没取到，下次可能有」，而事实是这条路径上它永远不会有。字段的缺席本身就是信息。

**曾经存在但已消失** —— 显示摘要被老化清空、往返载荷被就地置空、用量因流式中断而不完整。

这类字段**出现、值可为 `null`、并配一个状态**说明原因。

## 这不是新发明

`CONTEXT.md` 里已有「用量三态」：`complete` 为实测、`partial` 为流式中断后的估算、`unavailable` 为无从得知，且缺失一律不以 0 表示。

**本决定只是把它推广成通则**，用量三态成为它的第一个实例。这样前端面对空值时永远有话可问，不必按字段各记一套规矩。

术语定为**可用性状态**而非「观测量状态」：`source=discovered|fallback` 说的是模型清单，那在 `app` schema 里，不是观测量——范围比观测面宽。

## 取值统一小写

现有取值大小写不一致：`CONTEXT.md` 的用量三态写作大写 `COMPLETE`，而 [ADR-0016](./0016-the-model-list-is-discovered-and-persisted.md) 的 `source=discovered|fallback`、[ADR-0012](./0012-the-auxiliary-model-never-writes-to-the-message-table.md) 的 `main`/`auxiliary`、[ADR-0004](./0004-tools-are-capabilities-providers-are-implementations.md) 的努力档位四档全是小写。

**统一小写**，`CONTEXT.md` 那条术语就地改。四处里三处已经是小写，且那三处都不好动——努力档位的小写是跟 Claude 的 effort 档位对齐的（#15 实查确认同名同序），`main`/`auxiliary` 是 ADR-0012 的产物。改一处比改三处便宜。

这是线上字面量不是叙述用词，大小写混用会直接变成前端的 bug。

## trace 查询接口：八项交办分两层

累积到本票的字段有八项：提示词版本标识、工具集版本标识、保留窗口值、推理 token、显示摘要、`role`、`usage_status`、system 消息的占位符字面量。

**它们不在同一个层级上**。三个版本类字段与保留窗口是**整次运行**的属性；`role` / `usage_status` / 推理 token 是**单个跨度**的属性；显示摘要挂在产出它的那次模型调用上。全平铺进一个响应体，读者无法分辨哪个是运行级、哪个是跨度级。

**响应体按跨度树的自然结构分两层**：

- **运行级** —— 提示词版本标识、工具集版本标识、本次运行生效的保留窗口值（三个版本类字段并列）、运行终态。
- **跨度级** —— `role`、模型标识、双向 token、`usage_status`、推理 token、显示摘要。

显示摘要按本决定的通则：字段在、值可为 `null`、配状态（`available` / `aged_out`）。推理 token 是永久真列，缺失记 `null`；但 `openai_chat_completions` 的跨度里这个字段**不出现**——那是结构性不存在，不是缺失。**协议决定有没有推理**这件事因此不需要额外字段告诉前端，字段的有无就说明了。

**system 消息在跨度的输入序列里永远是占位符字面量**（`{system_prompt@<version_id>}`）。[ADR-0010](./0010-the-system-prompt-is-run-configuration-not-conversation-memory.md) 定了全文不经接口下发，契约里这个字段的类型就是字符串，但它**永远是指代不是内容**——记在这里，否则将来有人觉得「这里应该给全文」而顺手塞进去，那条「用户不可见」的决定就被绕过了。

## 后果

- `CONTEXT.md` 的「用量三态」取值改小写，并新增「可用性状态」术语。
- 前端处理空值的分支由字段驱动：字段不存在 → 不渲染那一块；字段为 `null` → 读状态决定显示什么。
- `GET /api/models` 的两种「空」也归本通则，且它们是两回事：**清单为空**是发现失败（用户手填标识），**档案 `unavailable`** 是 env 缺失（这份档案压根不进选单）。两个状态各有各的字段，不可合并。
- 模型清单**平铺返回，每项带 `owned_by`，前端自己分组**。ADR-0016 定了显示原始模型标识不做美化，分组同理是**呈现决策**不是数据结构——#18 随时可能改成按别的维度分或干脆不分，那时不该回来改契约。分组结构在 TS 里是 `Record<string, Model[]>`，键是任意字符串，类型上也比数组弱。
