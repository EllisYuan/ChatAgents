# 应用配置进仓库，机器配置归面板

服务器上装着宝塔面板，它在管 `agent.ellisyuan.com` 的 Nginx 站点、TLS 证书与自动续期。[#19](https://github.com/EllisYuan/ChatAgents/issues/19) 同时要求「Nginx 配置纳入版本控制」——现状那份配置只以 `docs/nginx.conf.example` 的形式躺在 README 旁边，线上跑的是什么没人知道。

两者直接冲突：宝塔在面板里点保存会覆盖手改的内容，而仓库里的文件宝塔不认识。

**决定：按「这是机器的属性还是应用的属性」切开。**

| 归宝塔 | 归仓库 |
|---|---|
| TLS 参数、证书路径、证书自动续期、监听端口 | `location` 路由、`proxy_buffering off`、超时、静态资源的 `root` 与 `try_files` |

仓库那份是 `deploy/nginx/site.conf`，靠宝塔站点配置里一行 `include /www/chatagents/repo/deploy/nginx/site.conf;` 挂进去。`docs/nginx.conf.example` 删除。

## 判据

**换一台服务器还成立的，是应用的属性。** `/api/` 转发到哪个端口、SSE 那段要不要关缓冲、`/s/<uuid>` 这类前端路由要回 `index.html`——这些跟着代码走，改错了应用就坏。

**只对这台机器成立的，是机器的属性。** 证书放在哪、监听 443 还是别的、续期怎么跑——这些跟着机器走，而宝塔已经在做，抢过来等于自己重做一遍 Let's Encrypt 自动化。

## 这条判据不只管 Nginx

同一把尺子在本票上量了三次：

- **容器日志上限**（`max-size` / `max-file`）写进 `compose.yaml`，不改宿主 `/etc/docker/daemon.json`。日志会不会写满磁盘是这个应用的属性，随仓库走、换台机器照样生效；改 daemon.json 是机器属性，换机器就漏。
- **YAML 端点档案烘进镜像**，不做 bind-mount。它决定「有哪些端点档案、各自什么协议」（[ADR-0014](./0014-the-model-is-chosen-by-the-user-never-by-the-system.md) 定了协议是档案的属性），是应用行为的一部分。挂载出去等于让线上出现一份没人 review、CI 没跑过、和镜像版本对不上的行为定义——正是[#11](https://github.com/EllisYuan/ChatAgents/issues/11)「同版本号同发布」要消灭的东西。
- **`.env` 留在服务器上**，放在 git clone 目录之外（`/www/chatagents/.env`，`chmod 600`），CD 永不写它。密钥是机器的属性；让 CD 写它就得先把密钥放进 GitHub Secrets 再落盘，多一处泄露面换零收益。

## 一处例外要写明

静态资源的 `root` 指向 `/www/chatagents/frontend/current`，那是一个**宿主上的绝对路径**——它是机器属性，却出现在仓库文件里。这是刻意的：换机器时它是唯一需要改的一行，好过为了纯粹而把整段 `location` 拆成两半。

## 后果

- 仓库里那份 Nginx 配置是**不完整的**——它没有 `server` 块、没有 `listen`、没有证书。单独看会觉得残缺，它本来就只是一个 `include` 片段。
- 改 Nginx 配置要 `git push` + `deploy.sh`，不能在宝塔面板里直接改。**在面板里改会被下一次部署覆盖**（`git checkout` 会还原它）。
- `nginx -t` 与 reload 仍归宝塔那半边，部署脚本改完 include 文件后要触发一次 reload。
