# git tag 是版本号的唯一真相

一次发布出厂三样东西：一个后端镜像、一份前端静态产物、一份 compose 与 nginx 配置。[#11](https://github.com/EllisYuan/ChatAgents/issues/11) 定了它们**同版本号、同一次发布**，那就得有一个地方说了算这个号是多少。

**决定：版本号只由 git tag 决定，`pyproject.toml` 的 `version` 永久钉死 `0.0.0`。** 构建时 `ARG APP_VERSION` 把 tag 打进镜像，后端经 `/health` 暴露，前端经 Vite 的 `define` 进 `import.meta.env`。

## 为什么不让包版本跟着走

[#7 的勘误](https://github.com/EllisYuan/ChatAgents/issues/7)确认了 build backend 是 `uv_build`，它**不支持 VCS 驱动的包版本**（那是 hatchling 的强项）。所以 `pyproject.toml` 里那个字段只能是一个静态字符串，剩下两条路都不行：

- **每次发版顺手改它** —— 发版就多一个 commit，而那个 commit 的唯一内容是一个数字，还得赶在打 tag 之前。
- **偶尔想起来改它** —— 忘一次就有两个版本共用一个号。[ADR-0011](./0011-model-input-configuration-is-versioned-and-persisted.md) 拒绝人手版本号正是这个理由：会因忘记改而两版共用一个标识。

这个包**永不发布到 PyPI**，分发名 `chat-agents` 只是 src layout 的一个必填项。既然没有消费者读它，让它保持一个显然无意义的值，好过让它保持一个看起来有意义、实际会撒谎的值。

## 这条会被当成 bug

将来有人看到 `pyproject.toml` 写着 `0.0.0`、而线上 `/health` 返回 `v1.4.2`，第一反应一定是「这里漏改了」，然后去「修好」它。**`0.0.0` 是故意的，改它就是把撒谎的可能性重新引进来。**

## 后果

- `/health` 是版本号的唯一出口，也是[唯一的健康检查端点](./0032-app-config-lives-in-the-repo-machine-config-does-not.md)（现状那个与它内容完全相同的 `/` 一并删除）。
- 前端版本号是**构建时**注入的，所以前端产物也必须收这个 `ARG`——同一个 tag、两处注入。
- 本地开发时 `APP_VERSION` 未设，取值 `dev`。它不是一个需要伪造成真版本号的场景。
