# 往返载荷的寿命是一次运行

[ADR-0017](./0017-native-reasoning-is-two-things.md) 把[往返载荷](../../CONTEXT.md)放进了[消息](../../CONTEXT.md)表，留下一个没答的问题：每轮重建模型输入序列时，回放多久以前的？

Anthropic 官方把回传要求分了三档：

> * **Required:** within a tool-use turn, pass thinking blocks back.
> * **Recommended:** across turns, pass everything back.
> * **Allowed:** outside tool use, omit prior turns' thinking.

而同一份文档明说 "**A tool-use loop is one assistant turn**"。本项目一次[运行](../../CONTEXT.md)恰好就是一个 assistant turn——一条用户消息触发的 ReAct 全过程。**所以强制只覆盖运行内，跨运行只是建议。**

**决定：重建时只回放本次运行产生的往返载荷，更早运行的一律不带；运行终结时把它们就地清空。**

## 取 Required 不取 Recommended，因为它消掉三处麻烦

**切模型。** 官方要求换模型时必须剥离前几轮的 `thinking` 与 `redacted_thinking`——"Thinking blocks are tied to the model that produced them"，别的模型不报错，但被忽略的块照样算输入 token。而本项目用户随时换模型（[ADR-0014](./0014-the-model-is-chosen-by-the-user-never-by-the-system.md)），任何访客可在他人会话续聊（[ADR-0013](./0013-the-session-list-shows-business-facts-only.md)）。运行内换不了模型（ADR-0014 定失败也不换模型），跨运行本来就不带——于是剥离规则从一条要在运行时判断的逻辑，降级成结构性事实。

**消息表不必记「这条是哪个模型产的」。** 若跨运行回放，重建就必须知道每条助手消息的产出模型才能决定剥不剥。而模型标识只活在 `obs.span` 的真列里，业务去读它正撞 [ADR-0002](./0002-business-and-observability-share-a-database.md) 那条「业务不得 import 观测」。这条约束是本决定顺带解掉的，不是它的目的，但它比目的本身更难绕开。

**账单与体积。** Claude Opus 4.5 及之后的模型**默认把前几轮 thinking 留在上下文里并按输入 token 计费**；`signature` 在 Claude 4 之后「significantly longer」，而 ReAct 每一步的每条助手消息都拖着一个。本站公开无鉴权、只追踪不限制，这笔账没有上限。

代价是跨轮的推理连续性，也就是官方 Recommended 那一档想要的东西。本项目每轮是独立提问的聊天，不是长任务续跑，这个收益兑现不了多少。

## 清空的判据是「读者消失」，不是「时间到了」

跨运行不回放之后，更早运行的往返载荷**永不再被读**：evals 的 L2 回放喂给 Runner 的是录好的 fixture 而不是库行（[ADR-0007](./0007-backend-is-split-by-capability-not-by-layer.md)），而它本身加密不可读、零调试价值。

所以它**不进** [ADR-0003](./0003-span-table-follows-phoenix.md) 那套按起始时刻分级的老化——那套是给「有价值但会过时」的调试细节准备的。这一列只有一个读者，读者一消失数据就该走。清空是运行终态写入的一部分，不需要后台任务，也不需要一条新的老化规则。

**清空必须挂在运行的终态上，含失败与客户端断连就地停。** ADR-0007 定的断连就地停会稳定制造永不正常收尾的运行；若清空只挂在成功路径上，那些运行的往返载荷就是永不清理的孤儿。这与该 ADR 已经处理的悬空工具调用是同一个坑的两个出口。

## 后果

- 消息表出现第一个**会被就地置空**的字段。它不是软删除（行还在、语义未变），也不是老化（判据不是时刻）；实现时必须写明，否则下一个读到的人会把它当成数据丢失并试图「修好」。
- 截断——重建出的模型输入序列如何裁剪——多一条硬约束：**不得部分丢弃一条助手消息内的 thinking 块**。官方原文 "you can't rearrange, edit, or partially drop them"，要么整条消息留、要么整条走。这与 ADR-0007 已定的悬空工具调用读时修复落在同一处逻辑里。
