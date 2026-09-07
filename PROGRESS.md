# 当前进展

本文件只记录跨会话仍需要知道的执行状态；长期设计决定在 `docs/adr/`，需求与讨论在 GitHub Issues。

## 最近完成

- README 架构与工程说明按当前实现重写（当前分支 `docs/readme-rewrite-73`）。
- ADR-0007 的能力模块依赖方向按代码实测更正（issue #78）。
- eval-trigger 的 base revision 兼容路径修复（issue #79）。
- Agent Evals、模型输入版本化、OpenAPI 契约传递和前后端质量门禁已接入 CI。

## 进行中

- 建立仓库级 harness：入口地图、路径规则、架构边界与文档防腐检查。
- 将 harness 的工程成果回写到项目说明与简历。

## 后续事项

- issue #76：工具重试在运行事件与跨度层均不可见。
- issue #77：观察掩蔽状态缺少前端可消费的数据源。
- issue #78 / #79 的代码已在当前分支落地，GitHub issue 仍待确认并关闭。

## 阻塞

当前没有已知阻塞。开始工作前仍应以 `gh issue list` 与当前分支的 `git log` 复核本页，因为 issue 状态是外部系统中唯一仍会变化的部分。
