# 迁移只做加性变更

回滚是这个项目唯一的可用性保障——[#19](https://github.com/EllisYuan/ChatAgents/issues/19) 定了不做蓝绿、不做滚动更新、允许换版时中断，判据是「demo 挂了能多快恢复」而非「换版中不中断」。而回滚的形态是 `deploy.sh` 换一个旧 tag 重跑：拉旧镜像、`up -d`。

**问题在于 schema 不跟着回去。** `alembic downgrade` 不进部署流程（自动降级会在一次失败部署的慌乱中删掉真实数据），所以回滚之后是**旧代码对着新 schema**。

**决定：迁移只做加性变更。加列、加表、加索引可以；删列、删表、改类型、加 NOT NULL 约束不行——要删的东西留到下一个版本，确认不再回滚后再删。**

## 为什么这样就够了

旧代码不读新列，所以「加列」型迁移下回滚能跑通。这是拿一条写迁移时的规矩，换掉了「实现并测试双向迁移」的全部成本——对单人 demo 来说是极便宜的交易。

反过来若允许破坏性迁移，回滚就得连 schema 一起回，而 `downgrade` 脚本是全项目**最不可能被测到**的代码：只在出事时执行一次，且执行时没人有心情调试它。

## 删除怎么办

分两个版本做：

1. **v1.4.0** —— 新代码不再读某列，但列还在。
2. **v1.5.0** —— 确认 v1.4.0 稳定、不会回滚了，这一版的迁移删掉它。

代价是 schema 里会短暂存在没人读的列。这是明码标价的。

## 后果

- 迁移由独立的 `migrate` service 执行（同后端镜像、不同 command），用 compose 的 `service_completed_successfully` 挡在 `backend` 前。迁移失败则 `backend` 压根不创建，`docker compose ps` 一眼可辨——这是选独立 service 而非写进 entrypoint 的理由。**不是**多副本并发迁移，本项目单副本，那条常见理由在这里不成立。
- 迁移与应用版本绑在一起出厂（[#11](https://github.com/EllisYuan/ChatAgents/issues/11) 的「同版本号同发布」），所以一个 tag 对应一个确定的 schema 状态。
- [#17](https://github.com/EllisYuan/ChatAgents/issues/17) 已定 CI 要跑一条「从空库 `upgrade head` 到最新」的集成测试。它验的是迁移链能走通，**不验回滚**——本决定正是回滚不需要被验的原因。
