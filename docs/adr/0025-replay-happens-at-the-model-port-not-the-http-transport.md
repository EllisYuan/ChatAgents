# 回放注入点在 ModelPort，不在 HTTP transport

零网络的回放测试要在某一层把真实上游换成录制物。这一层选在哪里，是本项目测试架构最重的一个决定。

**决定：回放注入点是 `ModelPort` 边界。测试喂进去的是录制好的运行事件序列，不是录制好的 HTTP 响应。**

## 被推翻的前提

[#5](https://github.com/EllisYuan/ChatAgents/issues/5) 与 [#7](https://github.com/EllisYuan/ChatAgents/issues/7) 的 L2 方案建立在 `httpx.MockTransport` 上——在 HTTP transport 层拦截，按 chunk 吐回录好的 SSE 文本。两份报告都把它当作既定事实。

2026-08-14 实查推翻了这个前提所依赖的生态假设：

| 事实 | 证据 |
|---|---|
| `httpx` 停在 0.28.1（2024-12-06），20 个月无发版 | PyPI |
| 但仓库没死，master 最新提交 2026-02-23 | GitHub |
| `httpx2` 出现——Pydantic 接手的续作，2.10.0（2026-08-09），作者仍署 Tom Christie | PyPI / GitHub |
| `openai` 3.0.0（2026-08-12）依赖 `httpx2>=2.7.0,<3`，且「`httpx` 不再自动安装」 | PyPI / release notes |
| `anthropic` 0.122.0（2026-08-13）仍在 `httpx<1,>=0.25.0` | PyPI |

[#2](https://github.com/EllisYuan/ChatAgents/issues/2) 定了本项目**同时**装两个官方 client。于是：一个进程里 `httpx` 与 `httpx2` 并存，而 `MockTransport` 是**两个不同的类**。「一套 mock fixture 打两个协议」这个隐含前提当场破了。

沿着 transport 层走下去，代价不是「写两遍」——是**录制格式、chunk 切分、异常注入三处各维护一份**，而它们测的是同一件事。

## 为什么这一层是对的

不是为了绕开 httpx 分叉——绕开它只是红利。真正的理由是**回放要保护的东西在 `ModelPort` 之上**。

[#13](https://github.com/EllisYuan/ChatAgents/issues/13) 定了 `AgentRunner` 必须纯：不碰 DB、不碰 HTTP、不知道 SSE。回放存在的意义正是让这个纯 Loop 零网络零数据库跑完。而 `ModelPort` 是 `llm/` 对外的唯一出入口（[ADR-0007](0007-backend-is-split-by-capability-not-by-layer.md) 定了 `llm/` 对全项目零依赖），在它的边界上换实现，测到的正好是「Loop 拿到这串事件会怎么走」——一步不多，一步不少。

在 transport 层回放，则要连带把两个 SDK 的解析逻辑一起重跑一遍才能到达 Loop。那部分确实也需要测，但它是**另一件事**，见下。

副作用是这个决定让整条测试架构对 `httpx` / `httpx2` 分叉免疫：`openai` 升不升 3.0 变成纯依赖问题，不再是测试架构问题。项目跟进 `openai>=3`，不主动停在存量栈上。

## 已知代价

**SSE 解析代码本身不被回放层覆盖。** 注入点在解析器上方，那串字节怎么变成事件，回放测不到。

补法是一层单独的、窄的 transport 级测试，只测解析器：anthropic 侧用 `httpx.MockTransport`、openai 侧用 `httpx2.MockTransport`，两边各十几行。它是本项目唯一需要区分这两个库的地方，且刻意保持这个范围。

**超时与 backpressure 行为同样不被回放层覆盖**，归上面那层窄测试。

## 后果

- 录制物是 `ModelPort` 的输出序列——文本增量、工具调用、usage、thinking block。一次运行一个 JSON 文件，存 `backend/tests/fixtures/replay/`，可人读、可手改、diff 友好。
- **不录 chunk 时序。** [#5](https://github.com/EllisYuan/ChatAgents/issues/5) 拿 pacing 丢失骂 `vcrpy` 是对的，但那是 transport 层语境；注入点上移之后，chunk 间隔是注入点下方的属性，「按真实间隔 yield」测不到任何东西，只会让每次 CI 白等几十秒。
- 录制靠 `--record` pytest 参数打真实上游生成，录完人工过一遍再提交。
- [#25](https://github.com/EllisYuan/ChatAgents/issues/25) 那条要求仍然成立且更要紧：**录制内容必须包含每次响应的 `input_tokens`**。缺了它掩蔽窗口位置不可复现，「同输入产出逐字节相同的事件流」当场破——**且它会静默地破**，回放照样跑，只是断言的东西悄悄变了。
- ~~前端那条 Playwright 冒烟共用同一批录制物喂假 SSE 端点。这是注入点上移的意外红利。~~ **这条红利作废**：同一张票随后定了[前端弱测试](https://github.com/EllisYuan/ChatAgents/issues/17)——无 Vitest / RTL / Playwright，前端 CI 只有 lint 与 `tsc --noEmit`。录制物仍然只有后端在用。
