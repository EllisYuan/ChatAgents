# 测试与评测是两套体系

[#5](https://github.com/EllisYuan/ChatAgents/issues/5) 把 L1 静态规则、L2 回放、L3 Mock 工具、L4 LLM-as-Judge、L5 人工金标编成一条金字塔。这个编号方便讨论，但它把两件性质不同的事混成了一件。

**决定：全项目测试分层是平实的 unit / contract / replay / integration 四类。评测单独一套，住在 `backend/tests/evals/`。L1–L5 编号降格，只在评测内部继续用。**

## 为什么必须分开

**门禁语义不同，而这是不可调和的。**

测试是二值的：红或绿，红了阻断合并。评测是**连续值且有抖动的**——判官模型本身有方差，分数掉 3% 算不算回归，没有一个不拍脑袋的答案。

拿一个会抖的信号做阻断门禁，第一次误报之后就没人再信它，第二次就有人加 `continue-on-error`，第三次它被整个删掉。这不是假设，这是所有把 eval 当门禁的项目的实际归宿。

金字塔编号掩盖了这个差异：L1 到 L5 看起来是同一件事的五个强度档，实际上 L1/L2 是**普通测试**（纯逻辑断言、录制回放，确定性、毫秒级），L4/L5 才是真评测（要判官、要花钱、有抖动）。它们之间不是强度差异，是类别差异。

## 已知代价

「五层金字塔」这个说法在 [#5](https://github.com/EllisYuan/ChatAgents/issues/5) 报告里很显眼，作品集叙事上也更抓眼球。降格它意味着放弃一个现成的漂亮图。

接受。一张把两类东西画在同一个坡上的图，代价是读者以为它们该用同一套规则对待——而本项目恰恰要在这里做区分。

## 后果

- 评测用 pytest marker 而非目录控制运行时机（[#13](https://github.com/EllisYuan/ChatAgents/issues/13) 交办）：`addopts = -m "not eval"`，`eval` 是付费层总闸。**目录负责组织代码，marker 负责运行时机，两者不互相代劳。**
- 评测在 CI 里只警告不阻断，包括 [#16](https://github.com/EllisYuan/ChatAgents/issues/16) 要求的提示词/工具集变更触发的新旧双跑。
- 判官模型型号存环境变量、CI secret 注入，**不硬编码**（与 [ADR-0016](0016-the-model-list-is-discovered-and-persisted.md) 的「不硬编码模型清单」同一条规矩，测试代码不例外），也**不进 [ADR-0011](0011-model-input-configuration-is-versioned-and-persisted.md) 那套版本化体系**——判官不是模型输入，塞进那张表会污染它的语义。
- 每次评测产出必须记下当次用的判官快照标识。换了判官历史分数就不可比，不留痕则 [#24](https://github.com/EllisYuan/ChatAgents/issues/24) 的新旧双跑无从判断可比性。
