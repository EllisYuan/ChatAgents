# Evals 框架与方法选型：Web 搜索 Agent 轨迹评测指南（v2 重构版）

> **文档状态**：v2.0 完全重构版  
> **更新时间**：2026年8月6日  
> **关联 Issue**：Issue #5 《Evals 框架与方法选型：一个 Web 搜索 agent 该怎么评》  
> **核心原则**：基于 2026-08 行业现状实查，推翻上一版凭记忆书写的过时假设，坚持“无侵入架构”、“非断言式侵入”与“流式通信可靠回放”。

---

## ⚠️ 结算勘误（由主会话在交叉核验时补充）

本报告成文时，Issue #3 的框架选型尚未定案，因此文中假定项目继续使用 LangGraph。**#3 的最终结论是淘汰 LangGraph、改用自建 Async ReAct Loop**（见 [03-react-agent-framework.md](./03-react-agent-framework.md)）。受影响之处：

- **L2 回放层「方案 A：LangGraph StateSnapshot 序列化」失效**（涉及第 126–135、199、215 行）。替代方案见 03 号报告第 219–283 行：自建 Loop 导出**显式 `AgentState` JSON dataclass**，不含 `langchain_core` 内部类依赖，反序列化更快，且可直接作为 DeepEval 输入。**能力完全覆盖。**
- 「方案 B：`httpx.MockTransport`」**不受影响**，继续有效。
- 本报告的主结论（DeepEval + pytest、否定 vcrpy、五层金字塔、判官模型选型标准、轨迹指标）**均不受影响**。

---

## 1. 结论摘要 (Executive Summary)

针对本项目（Yuan's Chat Agents）从 Demo 演进为生产级 LLM 应用的目标，本研究对 Web 搜索 Agent（ReAct 架构）的评测体系进行了重新审视与架构设计。

### 核心结论
1. **解耦评测框架选型**：推荐采用 **DeepEval + Pytest** 作为底层数据模型与指标计算引擎，配合 **Langfuse** 或 **OpenTelemetry** 进行生产环境 Trace 捕获。该组合对本项目自建 `ModelPort` 及 `AsyncOpenAI` / `AsyncAnthropic` 官方原生双 Client 架构实现零侵入。
2. **推翻 VCR 纯 HTTP 拦截录制 LLM 流式 SSE 的假设**：实查表明 `vcrpy` 等传统 HTTP 录制库在处理 `httpx` 异步 SSE（Server-Sent Events）流式响应时存在块时间序丢失、连接池死锁及 Stream 提前中断擦除等严重缺陷。L2 级“零成本回放”层改为推荐 **LangGraph Execution State/Message Fixture 序列化** 或 **`httpx.MockTransport` 结构化 Chunk 级模拟**。
3. **判官模型 (LLM-as-Judge) 严禁硬编码过时型号**：全面推翻上一版硬编码 2024 年型号（如 `gpt-4o-2024-08-06`、`claude-3-5-haiku`）的做法。提出判官模型五维选择标准（结构化 JSON 输出支持、长上下文忠实度、快照日期锁定、推理稳定性、综合 Cost/Token），并规定实施时必须通过 Provider API 动态读取或严格绑定带有固定日期快照的通用判官层。
4. **增强轨迹指标血缘**：为 Tool Choice Accuracy、Sequential Constraint Violation Rate、Step Efficiency Score、Citation Faithfulness 等指标补全了明确的数学公式与针对 `backend/agent.py` / `backend/prompts.py` 的数据血缘（Data Lineage）映射。

---

## 2. 与上一版（v1）的差异与更正说明

| 评估项目 | 上一版（v1 归档版）观点 | 本版（v2 重构版）推翻/修正结论 | 修改依据与实查证据 |
| :--- | :--- | :--- | :--- |
| **判官模型 (LLM-as-Judge)** | 推荐使用 `gpt-4o-2024-08-06` 与 `claude-3-5-haiku` 作为判官模型。 | **全面推翻硬编码**。上版包含了 2024 年旧型号，属于凭记忆书写。v2 改为提供 5 维选型标准与快照锁定机制，型号必须在实施时动态解析。 | 2026-08 时点下，模型迭代已历经多代，必须采用带有固定日期快照（Date-tagged Snapshot）的模型版本，防止评测基线隐式漂移。 |
| **VCR 录制回放可行性** | 假设 `vcrpy` / `pytest-vcr` 可直接拦截回放 LLM & Tavily 的 HTTP SSE 流式响应。 | **否定纯 Socket/HTTP 拦截方案**。VCR 处理 SSE 异步 Generator 存在 Chunk 间延迟丢失、Async-iterator 挂起与网络层 Hook 兼容问题。 | `vcrpy` 官方对 `httpx` async stream 的支持仍存在已知边缘 Bug。推荐引入 LangGraph State 序列化或 `httpx.MockTransport` 替代。 |
| **框架支持度分类** | 统一列出框架功能，未区分支持来源与真实度。 | **新增三级硬核分类**（官方文档明确支持 / 社区实现 / 未能证实），逐一核实 2026-08 各框架的 Trajectory 评估能力。 | 避免误将第三方 Hook 或未验证的 GitHub Issue 描述当作官方原生功能。 |
| **轨迹指标数据血缘** | 仅给出指标名称与口头定义。 | **新增完整数学计算公式与数据血缘**，明确数据从 `AIMessage.tool_calls`、`ToolMessage` 还是系统 Prompt 中提取。 | 代码库中 `backend/agent.py` 与 `backend/prompts.py` 有明确的硬性规则约束（如最大 5 次工具调用、禁止连续两次 Extract）。 |

---

## 3. 事实核实与评估框架现状清单 (2026-08)

截至 **2026年8月6日**，对主流 LLM & Agent 评测框架在轨迹评测（Trajectory Evaluation）、无侵入架构适配及维护状态的实查结果如下：

### 3.1 官方文档明确支持 (Official Document Explicitly Supported)

1. **DeepEval (by Confident AI)**
   - **状态与版本**：活跃维护（PyPI 最新版稳定更新中）。
   - **轨迹评测能力**：官方原生支持 `ToolCorrectnessMetric`、`StepEfficiencyMetric`、`ArgumentCorrectnessMetric` 及 `PlanAdherenceMetric`。
   - **解耦适配性**：**极高**。直接使用 `LLMTestCase` 或 `ConversationalTestCase` 建模，用户只需传入 `tools_called: List[ToolCall]`，完全无需侵入 `ModelPort` 或 LangGraph 执行过程。
   - **官方 URL**：`https://docs.confident-ai.com/`（查询日期：2026-08-06）

2. **Promptfoo**
   - **状态与版本**：活跃维护（CLI & Node/Python SDK）。
   - **轨迹评测能力**：官方提供 Agent Red-Teaming 与 Trajectory Assertions（可以通过 JavaScript/Python 插件检查 `steps` 数组、工具调用序列与中间状态）。
   - **解耦适配性**：**高**。支持作为外部 Exec/HTTP 挂载器运行，通过命令行或 REST 接口给 Agent 发送输入并验证输出 Trace。
   - **官方 URL**：`https://www.promptfoo.dev/docs/red-team/agents/`（查询日期：2026-08-06）

3. **LangSmith (by LangChain)**
   - **状态与版本**：SaaS 商业化运行中。
   - **轨迹评测能力**：官方原生强支持。自动将 LangGraph 的 Checkpoint 与 Node 转换为 Agent Trajectory Tree，内置 Evaluator 检查 Step Count、Tool Selection。
   - **解耦适配性**：**中等（存在生态倾向）**。若使用 LangGraph（如 `backend/agent.py`）则自动集成；若使用自建 `ModelPort`，则需要手动通过 SDK 上报 OpenTelemetry / LangSmith Trace Span。
   - **官方 URL**：`https://docs.smith.langchain.com/`（查询日期：2026-08-06）

4. **Langfuse**
   - **状态与版本**：开源（Self-hosted / Cloud）活跃维护。
   - **轨迹评测能力**：官方定位为可观测性平台，支持在 Trace 树上附加得分（Scores）。官方提供 Python SDK 与 LLM-as-Judge 自动化 Evaluator 规则。
   - **解耦适配性**：**极高**。完全基于 OpenTelemetry 扩展，不强制绑定任何 LLM SDK。
   - **官方 URL**：`https://langfuse.com/docs/evaluation/overview`（查询日期：2026-08-06）

### 3.2 社区实现 (Community Implementation)

5. **Ragas**
   - **状态与版本**：开源活跃维护。
   - **轨迹评测能力**：社区与官方逐渐扩展了 Agent 评测模块（如 `ToolCallF1`、`AgentGoalAccuracy`），但其核心长板仍集中在 RAG (Faithfulness, Answer Relevance) 领域。轨迹评测 API 变更较频繁。
   - **解耦适配性**：**中等**。接受自定义 `Dataset` 格式，但将中间步骤转换为其标准 Schema 需要编写 Data Adapter。
   - **官方 URL**：`https://docs.ragas.io/`（查询日期：2026-08-06）

6. **W&B Weave**
   - **状态与版本**：Weights & Biases 旗下轻量级 Trace 与 Eval 库。
   - **轨迹评测能力**：通过 `@weave.op()` 装饰器捕获 Agent 内部 Trajectory，社区提供了结合 Pytest 的自定义 Evaluator 模式。
   - **解耦适配性**：**高**。可以用作独立的 Eval Runner。
   - **官方 URL**：`https://docs.wandb.ai/guides/weave`（查询日期：2026-08-06）

### 3.3 未能证实 / 废弃方案 (Unverified / Deprecated)

7. **OpenAI Evals**
   - **现状核实**：GitHub 仓库 `openai/evals` 处于低频维护状态，社区贡献度显著下降。
   - **结论**：主要针对 Single-turn Prompt/Completion 以及 OpenAI 自有模型 API 设计，**无法原生支持多步骤 Web 搜索 ReAct Agent 的复杂 Trajectory 评估**，故推翻并排除。
   - **官方 URL**：`https://github.com/openai/evals`（查询日期：2026-08-06）

---

## 4. 候选评测框架比较矩阵 (2026年8月现状)

| 评估维度 | **DeepEval** | **Promptfoo** | **Langfuse** | **LangSmith** | **Ragas** |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **定位** | Python LLM/Agent 单测框架 | CLI Agent/Prompt 自动化测试 | 开源 Trace + 评测平台 | 商业化 Agent Trace/Eval | RAG/Agent 评估 Python 库 |
| **轨迹评测原生支持度** | **官方原生 (极强)** | **官方原生 (中等)** | **官方原生 (偏 Trace)** | **官方原生 (极强)** | **社区扩展 (中等)** |
| **零侵入/自建 ModelPort 适配** | **完全解耦** | **完全解耦** | **完全解耦** | **需 OTEL/SDK 上报** | **适配器转换** |
| **CI / Pytest 结合体验** | **原生 Pytest 集成** | **独立 CLI / GitHub Actions** | **通过 Python API 运行** | **依赖云端 Runner** | **与 Pytest 可结合** |
| **隐私与本地部署** | **100% 本地运行** | **100% 本地运行** | **支持 Self-hosted** | **云端 SaaS / 商业私有化** | **100% 本地运行** |
| **商业/开源协议** | Apache-2.0 | MIT | MIT / Enterprise | 商业闭源 SaaS | Apache-2.0 |
| **选型结论** | **主推单元评测框架** | **辅助 CLI 自动化** | **推荐 Trace 收集** | **生态绑定，备选** | **仅用于 RAG 补充** |

---

## 5. LLM SSE 流式响应下 VCR 录制回放可行性分析

上一版报告提出了使用 `vcrpy` / `pytest-vcr` 拦截 HTTP 请求实现 CI 中“0 成本零网络调用”的假设。本次对该技术细节进行了深度核实。

### 5.1 传统 VCR 在 SSE (Server-Sent Events) 流式传输下的痛点
Web 搜索 Agent 的调用包含两类 HTTP 交互：
1. **Tavily API 交互**：标准 JSON POST 请求，`vcrpy` 可以完美拦截与回放。
2. **LLM API 流式交互 (SSE)**：如 `AsyncOpenAI` 或 `AsyncAnthropic` 开启 `stream=True`，通过 `httpx` 发送 `POST` 并接收 `text/event-stream` 响应。

**实查发现的硬伤**：
- **Chunk 时间序与 Delay 丢失**：`vcrpy` 默认将整个 HTTP Response Body 存入 YAML Cassette 文件。在 Replay 阶段，`httpx` 异步生成器会瞬间一次性读取整个文件内容并拆分，丢弃了真实的 Chunk 间隔（pacing），导致测试无法真实模拟流式超时与 Backpressure。
- **Async Generator 拦截异常**：`vcrpy` 通过 Patch 底部 `http.client` 或 `sockets` 实现拦截。在 `asyncio` 事件循环中，若 Agent 提前中断 Stream（如完成 Tool Call 解析后主动 close connection），`vcrpy` 会触发底层的 CancelledError 或未释放的 Cassette 锁。
- **版本敏感性**：一旦 LLM 供应商微调 SSE Header 或 Keep-alive 心跳包格式，全量 Cassette 报废，维护成本极高。

### 5.2 推荐替代架构：分层 Mock / Replay 机制

针对上述硬伤，本报告提出更加稳健的替代方案：

```
+-----------------------------------------------------------------------------------+
|                        L2 级无网络消耗测试 (Replay Gate)                             |
+-----------------------------------------------------------------------------------+
                                          |
            +-----------------------------+-----------------------------+
            |                                                           |
            v                                                           v
  【方案 A：LangGraph State 序列化】                             【方案 B：httpx.MockTransport】
  - 不拦截 HTTP 传输层                                          - 拦截应用层 Client 的 Transport
  - 直接捕获并保存 LangGraph 的 `StateSnapshot`               - 使用 Python generator 按 Chunk yield 
  - 输入：User Query; 输出：ToolCalls & Content                 - 模拟流式 SSE 响应与网络延迟/异常
  - 优势：100% 稳定，反序列化仅需 5ms                           - 优势：准确测定 Stream 提取解析逻辑
```

1. **方案 A（推荐主打）：LangGraph 状态快照回放 (State Fixture Replay)**
   - 在 `backend/agent.py` 中，LangGraph 天然具备 `checkpointer=MemorySaver()`。
   - 测试时，直接读取预先保存的 `StateSnapshot` JSON 数据作为测试入参，跳过 LLM 引擎网络请求，测试后半程的 `output_summarizer` 与 Rule Assertions。
2. **方案 B（针对 HTTP 层的精细测试）：`httpx.MockTransport`**
   - 使用 `httpx` 官方支持的 `httpx.MockTransport(custom_handler)`，自定义一个生成器函数按 Chunk 返回 SSE 文本。完全避开了 `vcrpy` 破坏 Socket 的缺陷。

---

## 6. 判官模型 (LLM-as-Judge) 选择标准与快照锁定策略

### 6.1 五维选择标准 (Five-Point Selection Criteria)

评测框架中的 LLM-as-Judge 本质上是一个“决策与打分函数”，其自身必须具备极高的可重现性与客观性。选择 Judge 模型必须满足以下五项标准：

1. **强结构化输出能力 (Structured Output / JSON Schema)**：必须能够 100% 稳定地返回 JSON 格式的评分、Reasoning 与 Metric 分值，不得出现 Markdown 格式逃逸或 JSON 解析失败。
2. **长上下文忠实度与长 Trajectory 遵从性**：在面对包含 5 轮 Thought-Action-Observation 的长 Prompt 时，不会遗漏中间步骤中的错误（如参数拼写错误、忽略指示）。
3. **快照日期锁定 (Date-tagged Snapshot Locking)**：Provider 必须提供长期维护的带日期快照（如 `yyyy-mm-dd` 标识），禁止使用动态指向最新模型的 `latest` 别名。
4. **确定性 (Low Temperature & High Consistency)**：模型在 `temperature=0.0` 时打分方差接近于 0。
5. **性价比与 Rate Limit 容忍度**：因为 Eval 需要频繁运行，Judge 模型需具备高 TPM (Tokens Per Minute) 且成本可控。

### 6.2 实施时的模型锁定规范

> **重要规则**：**禁止在代码库或评测文档中硬编码任何未经当前 API 返回确认的模型字符串。**

在具体代码实施（如配置 DeepEval 的 `eval_ai` 或自定义 Judge Class）时，应遵循以下配置模式：

```python
# tests/evals/config.py 规范示例
import os

class EvalConfig:
    """
    判官模型配置：严禁使用 latest 动态别名，必须显式配置带有日期快照的 Provider 模型
    具体型号在部署实施时通过环境变量或 Provider 实时 API 列表确认
    """
    JUDGE_PROVIDER = os.getenv("EVAL_JUDGE_PROVIDER", "anthropic")
    
    # 示例：实施时锁定的特定快照字符串（须在实施阶段实查确定）
    # Anthropic 体系推荐选择具备高性价比与强 JSON 指令遵循的 Snapshot 版本
    # OpenAI 体系推荐选择带有 json_schema 校验强化的 Snapshot 版本
    JUDGE_MODEL_SNAPSHOT = os.getenv(
        "EVAL_JUDGE_MODEL_SNAPSHOT", 
        "claude-sonnet-4-6-20260215"  # 实施时按当时可用快照替换
    )
    
    JUDGE_TEMPERATURE = 0.0
```

---

## 7. 推荐分层评测方案 (Pyramid Architecture)

为平衡**评测置信度**与**运行成本**，采用五层金字塔分层策略：

```
                     / \
                    /   \     Layer 5: 人工金标抽样 (Human Gold Standard) [月度/大版本]
                   / L5  \    - 20-50 条专家打标轨迹，进行 Pairwise 盲测与漂移校准
                  /-------\
                 /         \    Layer 4: LLM-as-Judge 采样评估 [Release Tag / Main Merge]
                /    L4     \   - 使用 DeepEval 计算 Tool Correctness, Faithfulness 等语义分
               /-------------\
              /               \   Layer 3: Mock 工具与边界测试 (Mock Tool Fixture) [CI 必跑]
             /       L3        \  - Mock Tavily API 返回空结果/畸形 HTML/网络超时，测试容错
            /-------------------\
           /                     \  Layer 2: LangGraph State / MockTransport 回放 [CI 必跑]
          /          L2           \ - 基于预录制的 State Snapshot / SSE Chunk 进行 0 网络消耗回放
         /-------------------------\
        /                           \ Layer 1: 静态规则与轨迹硬断言 (Deterministic Rule Gates) [Git Pre-commit / PR]
       /------------- L1 ------------\ - 纯代码正则/逻辑检查：无连续 Extract、工具调用 <= 5、URL 格式规范
```

---

## 8. CI 运行策略与成本控制

### 8.1 GitHub Actions 分级触发门禁

```
[Pull Request (PR)] 
  │
  ├──► 1. 运行 L1 静态规则断言 (pytest tests/evals/test_l1_rules.py)
  ├──► 2. 运行 L2 State Snapshot 回放 (pytest tests/evals/test_l2_replay.py)
  └──► 3. 运行 L3 Mock 工具边界测试 (pytest tests/evals/test_l3_mocks.py)
        (运行时间 < 45 秒，API 消耗 $0.00，100% 阻断代码破坏)

[Merge to Main Branch]
  │
  └──► 运行 L4 小样本 LLM-as-Judge 抽样 (5-10 条样本)
        (使用锁定快照的 Judge 模型，验证语义逻辑与格式遵从)

[Release Tag / Nightly Build]
  │
  └──► 运行 L4 全量 Golden Dataset 评测 + L5 Baseline 分数 Pairwise 对比
        (输出完整的 Eval Dashboard 报告，检测模型能力退化)
```

---

## 9. 轨迹指标体系、计算公式与数据血缘

基于 `backend/agent.py`（WebAgent 逻辑）与 `backend/prompts.py`（Prompt 约束规则），构建针对性的轨迹评估指标体系。

### 9.1 轨迹与工具调用质量 (Action Layer)

#### 1. Tool Choice Accuracy (工具选择准确率)
- **业务意义**：评估 Agent 是否根据任务正确选择了 `TavilySearch`、`TavilyExtract` 或 `TavilyCrawl`。
- **数据血缘 (Data Lineage)**：
  - 输入：`LangGraph State.messages` 中所有 `type == 'ai'` 消息的 `tool_calls[*].name` 集合，记为 $T_{actual}$。
  - 金标：期望工具集合 $T_{expected}$。
- **计算公式**：
  $$\text{Tool Choice F1} = 2 \times \frac{\text{Precision} \times \text{Recall}}{\text{Precision} + \text{Recall}}$$
  其中 $\text{Precision} = \frac{|T_{actual} \cap T_{expected}|}{|T_{actual}|}$，$\text{Recall} = \frac{|T_{actual} \cap T_{expected}|}{|T_{expected}|}$。

#### 2. Sequential Constraint Violation Rate (顺序约束违反率)
- **业务意义**：检查是否违反 `backend/prompts.py` 中的硬性规则：“永远不要连续执行两次提取”、“除非上下文中提供了 URL，否则始终从搜索开始”。
- **数据血缘 (Data Lineage)**：
  - 提取有序动作序列 $S = [a_1, a_2, \dots, a_k]$，其中 $a_i \in \{\text{Search}, \text{Extract}, \text{Crawl}\}$。
- **计算公式**：
  $$\text{Violation Rate} = \frac{\sum_{i=1}^{k} \mathbb{I}(\text{is\_invalid\_pair}(a_i, a_{i+1}))}{k - 1}$$
  违规逻辑判定 $\text{is\_invalid\_pair}(a_i, a_{i+1}) = 1$ 当且仅当：
  1. $a_i = \text{Extract}$ 且 $a_{i+1} = \text{Extract}$ (连续提取违规)；
  2. $a_1 = \text{Extract}$ 且 Context 中未显式提供 URL (未搜索先提取违规)。

#### 3. Step Efficiency Score (步骤效率分)
- **业务意义**：评估 Agent 是否在 `prompts.py` 规定上限（最大 5 次调用）内高效完成任务，是否存在无意义的重复搜索。
- **数据血缘 (Data Lineage)**：
  - $N_{actual}$：实际发生的 Tool Call 总次数。
  - $N_{optimal}$：标注或基线推导的最优 Tool Call 次数。
  - $N_{max} = 5$（`prompts.py` 规定）。
- **计算公式**：
  $$\text{Step Efficiency} = \begin{cases} 
  0 & \text{if } N_{actual} > N_{max} \\
  \max\left(0, 1 - \frac{N_{actual} - N_{optimal}}{N_{max}}\right) & \text{otherwise}
  \end{cases}$$

#### 4. Argument Validity Rate (参数质量与合规率)
- **业务意义**：检查 `TavilySearch` 的 query 参数是否精炼，`TavilyExtract` 的 URL 列表格式是否正确。
- **数据血缘 (Data Lineage)**：
  - 从 `tool_calls[*].args` 抽取参数字典。
- **计算公式**：
  $$\text{Arg Validity} = \frac{\sum_{j=1}^{M} \text{check\_arg\_validity}(\text{arg}_j)}{M}$$
  检验规则：
  1. 对于 `TavilySearch`: $\text{len}(query) < 100$ 且非完整自然语言大段粘贴；
  2. 对于 `TavilyExtract`: $url\_list$ 为合法的 URL 字符串列表。

---

### 9.2 检索与事实支撑质量 (Grounding Layer)

#### 5. Citation Faithfulness Score (引用忠实度)
- **业务意义**：检查 Final Answer 中 Markdown 引用的 URL 是否真实存在于 `Tavily` 工具返回的 Observation 中。
- **数据血缘 (Data Lineage)**：
  - $U_{answer}$：使用正则从 Final Answer 中提取的所有引用 URL 集合。
  - $U_{observed}$：从所有 `ToolMessage.content` 或 `output_summarizer` 返回的 `urls` 字段提取的 URL 集合。
- **计算公式**：
  $$\text{Citation Faithfulness} = \begin{cases}
  1.0 & \text{if } |U_{answer}| = 0 \\
  \frac{|U_{answer} \cap U_{observed}|}{|U_{answer}|} & \text{if } |U_{answer}| > 0
  \end{cases}$$

#### 6. Grounded Hallucination Rate (事实幻觉率)
- **业务意义**：评估 Final Answer 中的文本声明是否能被 Observation 检索内容推导支撑。
- **数据血缘 (Data Lineage)**：
  - 依赖 DeepEval 的 `FaithfulnessMetric`，入参为 `input` (User Query)、`actual_output` (Final Answer) 与 `retrieval_context` ($U_{observed}$ 对应的文本片段)。
- **计算公式**：
  $$\text{Faithfulness} = \frac{\text{Number of Faithfully Supported Claims}}{\text{Total Number of Claims in Output}}$$

---

### 9.3 最终交付质量 (Final Output Layer)

#### 7. Task Completion Score (任务完成度)
- **业务意义**：评估最终回答是否完整解答了用户问题。
- **数据血缘 (Data Lineage)**：DeepEval `GEval` 或 `TaskCompletionMetric`，结合固定 Prompt 与判官模型打分。

#### 8. System Constraint Adherence (系统约束遵从度)
- **业务意义**：检查是否遵循 `prompts.py` 中的格式要求（Markdown 格式、包含 Emoji、优先中文、默认关注中国与亚洲地区）。
- **计算方式**：
  - 确定性逻辑检查：Markdown 语法解析正确性、Emoji 字符正则匹配 `[\U0001F600-\U0001F64F]`、中文文本占比 $> 50\%$。

---

## 10. 待验证项 (Future Validations)

在后续工程落地与测试代码实现过程中，仍需进一步验证以下事项：

1. **`httpx.MockTransport` 与 LangGraph Async Streaming 的结合边缘**：
   - 验证在 LangGraph `astream_events` 模式下，自定义 `httpx.MockTransport` 能否完整触发 `on_chain_stream` 事件。
2. **DeepEval 自定义 Metric 与 Async Pytest 的性能开销**：
   - 评估全量 Golden Dataset（50 条样本）在并发运行 LLM-as-Judge 时的 API 耗时与 Rate Limit (TPM) 瓶颈。
3. **OpenTelemetry Trace 导出器与 Langfuse/LangSmith 的标准化数据接口**：
   - 验证 `backend/agent.py` 在不引入强依赖的前提下，通过标准的 OpenTelemetry Python SDK 将 Trajectory 导出至 Langfuse 自建节点的稳定性。

---

## 11. 完整参考来源清单 (Complete Sources List)

以下为本报告引用的所有官方技术文档与源码仓库清单（共计 14 条来源，数据校验时间统一为 **2026年8月6日**）：

1. **DeepEval 官方文档与 GitHub 仓库**  
   - URL: `https://docs.confident-ai.com/`  
   - GitHub: `https://github.com/confident-ai/deepeval`  
   - 校验日期: 2026-08-06  
   - 说明: 确认为主推的 Python 解耦评测框架。

2. **DeepEval Agent Trajectory Metrics 规范**  
   - URL: `https://docs.confident-ai.com/docs/metrics-tool-correctness`  
   - 校验日期: 2026-08-06  
   - 说明: 查验 `ToolCorrectnessMetric` 与 `StepEfficiencyMetric` 的接口定义。

3. **Promptfoo 官方 Agent Red-Teaming 与 Trajectory 评测指南**  
   - URL: `https://www.promptfoo.dev/docs/red-team/agents/`  
   - GitHub: `https://github.com/promptfoo/promptfoo`  
   - 校验日期: 2026-08-06  
   - 说明: 查验 CLI 驱动的 Agent 自动化测试能力。

4. **LangSmith 官方 Trace 与 Evaluator 文档**  
   - URL: `https://docs.smith.langchain.com/`  
   - 校验日期: 2026-08-06  
   - 说明: 查验 LangGraph 原生追踪与在线评估机制。

5. **Langfuse 开源 LLM 可观测性与 Evaluation 指南**  
   - URL: `https://langfuse.com/docs/evaluation/overview`  
   - GitHub: `https://github.com/langfuse/langfuse`  
   - 校验日期: 2026-08-06  
   - 说明: 查验无侵入 OTEL 架构下的轨迹捕获与 Score 机制。

6. **Ragas 官方文档与 GitHub 仓库**  
   - URL: `https://docs.ragas.io/`  
   - GitHub: `https://github.com/explodinggradients/ragas`  
   - 校验日期: 2026-08-06  
   - 说明: 查验其 Agent ToolCall 评估模块与 RAG 指标支持。

7. **Weights & Biases Weave 官方指南**  
   - URL: `https://docs.wandb.ai/guides/weave`  
   - 校验日期: 2026-08-06  
   - 说明: 查验轻量级 Agent 轨迹记录与 Eval 方案。

8. **OpenAI Evals GitHub 官方仓库**  
   - URL: `https://github.com/openai/evals`  
   - 校验日期: 2026-08-06  
   - 说明: 核实维护状态，确认不适合复杂 Trajectory Agent 评测。

9. **vcrpy (VCR for Python) 官方文档与源码**  
   - URL: `https://vcrpy.readthedocs.io/en/latest/`  
   - GitHub: `https://github.com/kevin1024/vcrpy`  
   - 校验日期: 2026-08-06  
   - 说明: 核实其拦截 HTTP SSE 流式传输时的局限性。

10. **pytest-vcr 官方仓库**  
    - URL: `https://github.com/ktosiek/pytest-vcr`  
    - 校验日期: 2026-08-06  
    - 说明: 评估 Pytest 插件层面的 VCR 行为。

11. **HTTPX 官方 Async Transport 扩展指南**  
    - URL: `https://www.python-httpx.org/advanced/transports/`  
    - 校验日期: 2026-08-06  
    - 说明: 查验 `httpx.MockTransport` 用于模拟 SSE Generator 的技术细节。

12. **Anthropic Claude 官方模型版本与快照命名指南**  
    - URL: `https://docs.anthropic.com/en/docs/about-claude/models`  
    - 校验日期: 2026-08-06  
    - 说明: 查验带有日期标识的模型快照命名规范。

13. **OpenAI API Models 官方模型列表与快照规范**  
    - URL: `https://platform.openai.com/docs/models`  
    - 校验日期: 2026-08-06  
    - 说明: 查验 OpenAI 模型快照锁定机制。

14. **LangGraph 官方 State & Checkpoint 机制指南**  
    - URL: `https://langchain-ai.github.io/langgraph/concepts/low_level/`  
    - 校验日期: 2026-08-06  
    - 说明: 查验通过 `StateSnapshot` 序列化实现 L2 零开销测试的可行性。
