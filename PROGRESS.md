# 当前进展

本文件只记录跨会话仍需要知道的执行状态；长期设计决定在 `docs/adr/`，需求与讨论在 GitHub Issues。

## 最近完成

- README 架构与工程说明按当前实现重写（当前分支 `docs/readme-rewrite-73`）。
- ADR-0007 的能力模块依赖方向按代码实测更正（issue #78）。
- eval-trigger 的 base revision 兼容路径修复（issue #79）。
- Agent Evals、模型输入版本化、OpenAPI 契约传递和前后端质量门禁已接入 CI。
- issue #93：首条用户消息与 fallback 随主入口保存；标题改由独立会话 HTTP 调用（`POST /api/sessions/{session_id}/title`）生成，主 ReAct 运行不再等待或统计标题，决定见 ADR-0036。标题 trace 写入与只读查询接口保留，仅移除会话列表详情按钮；其他页面的展示入口后续另行设计。旧运行下的历史标题跨度保留、不删除不重算。
- issue #94：主回答停止、完成或失败不取消标题；切换会话或离开页面取消独立标题请求，服务端通过 HTTP 断连终止模型调用并回收资源。取消与结果或事务提交竞争时保留真实已完成结果、已提交标题和已获得用量；断连后不补发。

## 进行中

- 建立仓库级 harness：入口地图、路径规则、架构边界与文档防腐检查。
- 将 harness 的工程成果回写到项目说明与简历。

## 后续事项

- issue #76：工具重试在运行事件与跨度层均不可见；`RunToolContext` 的 `span_recorder` 至今是 `NullSpanRecorder`，attempt 级跨度整条空转。
- issue #77：掩蔽事实已落 `obs.run.attributes`，缺的是 REST 契约（`RunDetail`/`SpanView`）不暴露，前端无从渲染。
- issue #84 / #87 / #89：前端幽灵消息、主 system prompt 未注入生产入口、中断后 assistant 内容不落库。#86 的标题收尾问题由 #93 的独立会话调用替代。
- issue #88 是压缩机制的现状盘点，长期参考，不作为待办。

## 阻塞

当前没有已知阻塞。开始工作前仍应以 `gh issue list` 与当前分支的 `git log` 复核本页，因为 issue 状态是外部系统中唯一仍会变化的部分。
