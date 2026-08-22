# 评测骨架

这里是独立于门禁测试的评测体系（ADR-0026）。目录只负责组织代码，运行时机由 `eval` marker 决定。

```bash
# 默认测试：不运行 eval / upstream；db 仍会运行
uv run --project backend pytest backend/tests

# 显式运行评测
uv run --project backend pytest -m eval backend/tests/evals
```

## CI 挂钩

PR 上的 `eval-trigger` job 在临时 Postgres 中先播种 base revision 的模型输入版本，再只读比较当前 checkout 与版本表最新行的 `content_hash`。它不按文件路径判断，因此变量拼装逻辑的改动也会触发评测；无关改动不会启动付费评测 job。

发生提示词或工具集变更时，`eval` job 在同一次 CI 内用同一批数据跑旧版与新版，不读取历史分数作为基线。四个努力档位各取 8 条，共 32 条；判官型号由 `EVAL_JUDGE_MODEL` 注入。评测 job 使用 `continue-on-error`，只提供警告，不阻断合并。

在 PR 上添加 `skip-eval` 标签可以跳过付费评测。release tag 或手动 workflow 的 release 输入会运行保留窗口 `N ∈ {1,2,3,5,8}` 的网格扫描，并使用 `EVAL_RELEASE_JUDGE_MODEL`；该扫描不参与 PR 门禁。

## 数据流

1. `EvalDataset` 读取场景，并仅按「提示词版本 × 工具集版本 × 努力档位」分组。查询文本不参与分组。
2. `FrozenVendorFixtureStore` 按 `scenario_id` 打开夹具，把 `web_search` 的 Tavily Port 和 `web_reader` 的 Jina Port 替换成冻结实现。`ModelPort` 不替换，因此被评测的模型保持在线。
3. `evaluate_batch` 消费每条场景的 `RunEvent`，计算五个确定性指标，并通过 `JudgePort` 获取事实幻觉率和任务完成度。
4. 每条 `EvalCaseResult` 都带 `judge_snapshot`；批次结果同时列出本批次出现过的全部判官快照。

## 数据集格式

具体场景内容与校准值不属于 #60。后续数据集遵循以下形状：

```json
{
  "cases": [
    {
      "scenario_id": "fresh-news",
      "query": "今天发生了什么？",
      "prompt_version_id": "system@...",
      "tool_schema_version_id": "tools-medium@...",
      "effort": "medium",
      "should_use_tools": true,
      "expected_answer": null
    }
  ]
}
```

同一个 `scenario_id` 可以出现在不同三轴分组中，但不能在同一分组内重复。

## Tavily / Jina 夹具格式

夹具的顶层键是数据集场景 ID，不是模型生成的查询字符串。同一场景下不同措辞、不同次数的 Tavily 调用都读取该场景冻结的结果集合；Jina 正文按 URL 读取。

```json
{
  "scenarios": {
    "fresh-news": {
      "tavily_results": [
        {
          "title": "来源标题",
          "url": "https://example.test/a",
          "content": "搜索摘要",
          "score": 0.9
        }
      ],
      "jina_responses": {
        "https://example.test/a": "# 正文\n\n冻结内容"
      }
    }
  }
}
```

## 七个指标

确定性指标：

- `argument_compliance`：工具调用参数通过当次工具 JSON Schema 的比例。
- `system_constraint_adherence`：实际迭代数对软步数预算的遵从度。
- `tool_trigger_rate`：需要联网时触发工具、不需要联网时保持不触发的比例。
- `trajectory_efficiency`：硬上限触达、重复读取同一 URL、搜索后未继续读取的比例三个子信号的均值。
- `citation_faithfulness`：回答引用 URL 与实际工具观察 URL 的交集占回答引用的比例。

判官指标：

- `factual_hallucination_rate`
- `task_completion`

不存在工具误选率。显示摘要事件和标题生成结果不进入 `EvalTrace`，因此也不进入任何指标。

## 判官

`ModelPortJudge` 复用项目现有的 `ModelPort`，不绑定特定供应商 SDK。型号不写死在代码中：常规评测由 CI secret `EVAL_JUDGE_MODEL` 注入 `gpt-4.1-mini-2025-04-14`，release 金标准抽检由 `EVAL_RELEASE_JUDGE_MODEL` 注入 `claude-opus-4-5-20251101`。判官返回的快照标识必须写入每条评测结果。
