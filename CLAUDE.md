# ChatAgents — Agent 入口地图

ChatAgents 是一个以 LLM 应用工程为核心的 ReAct Agent：多模型协议适配、Tool Calling、Context Engineering、Agent Evals、Trace 与 AG-UI over SSE。

本文件只做导航，不复述代码、配置或 CI 已能直接给出的事实。详细规则按任务渐进式加载。

## 开始工作

```bash
uv run --project backend python scripts/dev.py setup  # 安装锁定依赖
uv run --project backend python scripts/dev.py db     # 启动 PostgreSQL 并升级 schema
uv run --project backend python scripts/dev.py check  # 完整确定性验证
```

单项命令见 `python scripts/dev.py --help`。`scripts/dev.py` 是 Windows/Linux/macOS 共用的执行真源；根 `Makefile` 只是 Unix 环境的薄封装。

## 仓库地图

- `backend/src/chat_agents/` — Python/FastAPI 后端，按能力模块组织
- `frontend/` — React 前端
- `CONTEXT.md` — 统一语言；命名领域概念前先读
- `docs/adr/` — 架构决策与被否决方案
- `PROGRESS.md` — 跨会话执行状态、后续事项与阻塞
- `README.md` — 面向开发者的系统说明、启动、部署与故障排查
- `.claude/rules/` — 按文件路径加载的局部约束

## Agent 工作入口

### Issue tracker

需求与讨论在 `EllisYuan/ChatAgents` 的 GitHub Issues，通过 `gh` CLI 管理。流程见 `docs/agents/issue-tracker.md`。

### Triage labels

五类规范标签及映射见 `docs/agents/triage-labels.md`。

### Domain docs

本仓库是 single-context：一个根 `CONTEXT.md` + 一组 `docs/adr/`。消费方式见 `docs/agents/domain.md`。

## 全局不变量

- 术语以 `CONTEXT.md` 为准；显式列入 `_Avoid_` 的同义词不再引入。
- 新设计不得静默推翻 ADR；冲突时明确指出并更新或 supersede 原决定。
- 后端能力模块的依赖方向由 Import Linter 强制，不能靠换 import 路径绕过。
- README 中标记为 generated 的结构与计数由 `scripts/check-docs-drift.py` 维护，手工编辑后会被 CI 拒绝。
- 测试是阻断门禁；带方差的 Agent Evals 只发警告。两者边界见 ADR-0026。
- 代码、文档与验证应作为同一逻辑变更提交；完成标准是 `scripts/dev.py check` 通过。
