# 上游契约测试不做门禁

本项目有两套契约测试，名字只差两个字，管的完全不是同一件事：

- **契约测试**——验「我们的后端有没有违反自己的 OpenAPI 契约」。Schemathesis 进程内直打 FastAPI，确定性，**阻断合并**。
- **上游契约测试**——验「中转站给我们的三个协议还合不合我们的假设」。打真实的 `api.ellisyuan.com`，非确定性。

**决定：上游契约测试定时跑，失败自动开 issue，不阻断任何合并。**

## 为什么不当门禁

**它的失败十有八九不是本次 PR 的错。**

[#15](https://github.com/EllisYuan/ChatAgents/issues/15) 实测已经列出了这条路上的全部噪声源：中转站换上游、模型下架、清单漂移、限流，还有那个被转译污染的状态码语义——**429 是欠费、502 是模型标识写错**，同一原因跨协议两个码。

任何一条都会让这套测试变红，而它们与「你这次改了什么」零相关。放进 PR 门禁，等于让一个你控制不了的外部系统随时卡住合并。结局是可预测的：有人加 `continue-on-error`，然后它就废了。

定时跑 + 失败开 issue，保住了它真正的价值——**及早发现上游漂移**，而不是当门禁。

## 断言只针对形状

[#15](https://github.com/EllisYuan/ChatAgents/issues/15) 交办的这条同样是硬约束：清单与可用性会漂移，断言**只能针对形状不能针对具体标识**。断言「返回的每个模型对象有 `id` 与 `owned_by`」可以；断言「清单里有 `claude-sonnet-4-6`」不行——那是在给一个别人控制的清单写快照。

同理，解析器须容忍规范外字段（`reasoning_content` / `native_finish_reason` / `caller` / `stop_details`）与缺失的 `created`。其中 `reasoning_content` 明确为**读到也不消费**（[#31](https://github.com/EllisYuan/ChatAgents/issues/31)）。

## 一个不归 CI 的例外

[#31](https://github.com/EllisYuan/ChatAgents/issues/31) 留下的待验证事实里，**「thinking block 原样回传会不会被中转站改坏而 400」是阻塞性的**：它若为真，`anthropic_messages` 在这台中转站上根本跑不了 ReAct。

这条不是 CI 的事，是执行阶段第一天的一次性验证任务。**明确标为不归 CI**——藏进 nightly 意味着它可能三个月后才被人看见，而那时整条协议路径已经建在一个错误假设上了。

## 后果

- 上游契约测试用 `upstream` marker，默认不跑，nightly 与手动触发跑。
- 与打自己 API 的契约测试**分开排期**（[#12](https://github.com/EllisYuan/ChatAgents/issues/12) 交办）。两者管的不是同一件事，混在一个 job 里会让前者的确定性被后者的抖动污染。
- 它覆盖 [#31](https://github.com/EllisYuan/ChatAgents/issues/31) 交办的「thinking block 原样回传」——那是 `anthropic_messages` 上唯一会 400 的结构性错误。
