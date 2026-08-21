# 🤖 Yuan's  ChatAgents
<div align="center">

**一个集成了 Web 搜索、内容提取和深度思考能力的智能体助手**

![Python](https://img.shields.io/badge/Python-3.11--3.12-blue.svg)
![React](https://img.shields.io/badge/React-19+-61DAFB.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109+-green.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

[English](./README_EN.md) | **简体中文**

</div>

---

## 📖 项目简介

这是一个能够联网搜索的智能聊天机器人：

1. **智能聊天机器人**（基于 React + LLM）
2. **Tavily Web 智能体**（基于 AgentRunner + Tavily）

通过 React + FastAPI + AgentRunner + Tavily 架构，为 LLM 提供强大的 Web 搜索、内容提取和深度思考能力。

## ✨ 功能特性

### 🎯 核心功能
- **💬 交互式聊天界面**：基于 React，支持会话、流式回复和模型选择
- **🔍 实时 Web 搜索**：通过 Tavily 联网搜索最新信息
- **🕷️ 网站深度爬取**：深度爬取网站嵌套链接
- **📄 网页内容提取**：提取网页关键内容, 节省Token消耗
- **🧠 深度思考模式**：支持复杂查询的深度推理
- **⚡ 快速响应模式**：适合简单问题的快速回答
- **💭 对话记忆**：基于 FastAPI 与 PostgreSQL 的会话历史管理

### 🛠️ 高级特性
- **🔑 灵活的 API 密钥管理**：支持 Claude、Tavily 等多个 API
- **🎨 多模型支持**：支持 Claude (Haiku/Sonnet/Opus)、OpenAI(mini/nano/5.1)，预留 I/Groq 接口
- **📊 工具调用可视化**：实时展示Serch/Extract/Crawl过程
- **🎯 智能体类型切换**：快速模式 与 深度思考模式
- **💾 会话管理**：支持多会话，保留对话历史
- **🐳 Docker 支持**：一键容器化部署

## 🏗️ 架构设计

![Untitled-2025-12-21-0038](https://img.geekie.site/i/adImg/2025/12/21/022423.png)

### 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| **前端** | React + Vite | 现代化 TypeScript 单页应用 |
| **后端** | FastAPI | 高性能异步 API 框架 |
| **智能体** | AgentRunner | 自建异步智能体运行时 |
| **LLM** | Claude OpenAI | 主要语言模型 |
| **工具** | Tavily | Web 搜索/提取/爬取 |
| **其他** | Docker, python-dotenv | 容器化与配置管理 |

## 🚀 快速开始

### 环境要求

- **Python**: 3.11–3.12
- **API 密钥**:
  - [Anthropic Claude API](https://console.anthropic.com/)
  - [Tavily API](https://tavily.com/)

### 安装步骤

#### 1. 克隆仓库

```bash
git clone <your-repo-url>
cd intelligent-chatbot
```

#### 2. 安装依赖

安装 [uv](https://docs.astral.sh/uv/) 后，在仓库根目录执行：

```bash
uv sync --project backend
```

首次运行测试前，启动本地 PostgreSQL：

```bash
docker compose up -d postgres
```

#### 3. 配置环境变量

```bash
# 复制示例配置文件
cp .env.sample .env

# 编辑 .env 文件，填入你的 API 密钥
# ANTHROPIC_API_KEY=sk-ant-api-your-key-here
# TAVILY_API_KEY=tvly-your-key-here
```

#### 4. 启动应用

**方法 A：分别启动（推荐开发）**

```bash
# 终端 1：启动后端
uv run --project backend python -m uvicorn chat_agents.main:app --app-dir backend/src --reload

# 终端 2：启动 React 前端
npm --prefix frontend run dev
```

**方法 B：使用 Docker Compose 启动数据库和后端**

```bash
docker compose up -d --build

# 另一个终端启动 React 前端
npm --prefix frontend run dev
```

#### 5. 访问应用

- **前端**: http://localhost:5173
- **Docker 后端 API**: http://localhost:19180
- **Docker API 文档**: http://localhost:19180/docs
- **本地直接启动后端时**: http://localhost:8080

### 🚢 生产环境部署（宿主 nginx + Docker 后端）

**链路**：`浏览器 → 宿主 nginx（宝塔，TLS）┬ / → 直接读磁盘（前端静态产物）`
`                                       └ /api/ → 127.0.0.1:19180 → backend 容器`

前端不进容器：静态产物由宿主 nginx 直接读磁盘伺服，`/api/` 只穿这一层 nginx 直连后端。原因见下方「SSE 只能穿一层 nginx」。

#### 一次性服务器准备（人做，CD 做不了）

1. 建站 `agent.ellisyuan.com` + 申请证书（宝塔面板操作）
2. `git clone` 仓库到 `/www/chatagents/repo`
3. 在 clone 目录**之外**写 `/www/chatagents/.env`（含 `POSTGRES_*`、`ANTHROPIC_API_KEY` 等），`chmod 600`——CD 只读它，绝不写它
4. 宝塔站点配置里加一行：
   ```nginx
   include /www/chatagents/repo/deploy/nginx/site.conf;
   ```
5. 配置 GitHub Actions 的 SSH 部署密钥与服务器 IP 白名单

> **⚠️ 在宝塔面板里直接改 Nginx 配置会被下一次部署覆盖。** `deploy/nginx/site.conf` 随 `git checkout <tag>` 换版，面板里的手改内容不会被保留。要改路由、超时、`try_files` 这类应用属性的配置，改仓库里的 `deploy/nginx/site.conf` 再发布；只有 TLS、证书路径、监听端口这类机器属性才在面板里改。详见 [ADR-0032](./docs/adr/0032-app-config-lives-in-the-repo-machine-config-does-not.md)。

#### 发布 / 回滚

```bash
./scripts/deploy.sh v1.4.2
```

换一个 tag 重跑就是回滚，不依赖 CI 是否可用。脚本会拉取 `ghcr.io` 镜像、跑 `compose.yaml` + `compose.prod.yaml`、从 GitHub Release 下载前端产物解到 `/www/chatagents/frontend/<tag>` 并把 `current` 软链接指过去。前置条件见脚本头部注释。

#### SSE 只能穿一层 nginx（结构性要求）

`X-Accel-Buffering` 属于 `X-Accel-*` 一族，只在离用户最近的那一层生效——被第一层吃掉就不会向下传。如果 `/api/` 串两层 nginx（例如又经过容器内一层），就会有一层照常缓冲，**且失效是静默的**：流式响应不报错，只是攒一坨再吐，本地单层环境永远复现不出来。解法不是两层都配 `proxy_buffering off`，而是让 `/api/` 只穿一层——这也是前端不进容器的原因之一。

#### 部署后必做：curl -N 实测

这是「SSE 被静默攒批」唯一的检出手段，且不归 CI（CI 环境没有真实 nginx）：

```bash
curl -N https://agent.ellisyuan.com/api/runs -X POST \
  -H "Content-Type: application/json" -d '{"session_id":"...", "message":"你好"}'
# 应逐条打印事件，而不是卡住不动然后一次性吐出一大坨
```

同时验证：

```bash
curl https://agent.ellisyuan.com/health
# 应返回 {"status":"ok","version":"v1.4.2"}（版本号来自当次部署的 git tag）

curl -I https://agent.ellisyuan.com/s/00000000-0000-0000-0000-000000000000
# 刷新前端路由不应 404——依赖 deploy/nginx/site.conf 里的 try_files
```

## 📖 使用指南

### 基本使用

1. **配置 API 密钥**
   - 在 `.env` 文件中配置 Claude、OpenAI 和 Tavily API 密钥
   - 前端通过后端 API 使用这些配置，不在浏览器中保存密钥

2. **开始对话**
   - 在 React 前端创建或选择会话
   - 输入问题并发送，实时接收流式回复
   - 通过模型选择和高级选项调整请求

3. **查看执行过程**
   - 在 trace 面板中查看模型调用、工具调用和耗时
   - Tavily 工具支持搜索、网页内容提取和深度爬取
   - 会话列表保留历史会话，便于继续工作

### 高级功能

#### 工具调用展示

智能体会根据问题自动选择合适的工具：

- **🔍 web_search**: 搜索相关网页
- **📄 web_reader**: 读取网页和 PDF 内容

每个工具调用都会在 UI 中实时展示：
- 工具名称和类型
- 输入参数
- 输出摘要和来源链接

#### 会话管理

- 每个会话有唯一 ID
- 支持对话历史记忆
- 点击"新建会话"开始新对话

## 🔧 配置说明

### 环境变量

| 变量名 | 说明 | 必需 | 默认值 |
|--------|------|------|--------|
| `ANTHROPIC_API_KEY` | Claude API 密钥 | ✅ | - |
| `TAVILY_API_KEY` | Tavily API 密钥 | ✅ | - |
| `OPENAI_API_KEY` | OpenAI API 密钥 | ✅ | - |
| `GROQ_API_KEY` | Groq API 密钥（未来） | ❌ | - |
| `PORT` | 后端端口 | ✅ | 8080 |

### 智能体配置

后端配置集中在 `backend/config/endpoints.yaml` 和环境变量中；模型清单与高级选项由后端 API 提供，React 前端据此渲染选择控件。开发时可通过 `VITE_BACKEND_ORIGIN` 覆盖前端代理的后端地址。

## 📁 项目结构

```
intelligent-chatbot/
├── backend/
│   ├── src/chat_agents/        # FastAPI、AgentRunner 与领域模块
│   ├── tests/                  # 后端测试
│   ├── config/endpoints.yaml   # endpoint 配置
│   ├── pyproject.toml          # Python 项目元数据
│   └── uv.lock                 # 锁定依赖
├── frontend/                   # React + Vite 单页应用
│   ├── src/                    # 页面、组件与 API 客户端
│   └── public/                 # 静态资源
├── docs/                       # 文档与 ADR
├── deploy/                     # Nginx 与发布配置
├── compose.yaml                # 本地 Docker Compose 配置
├── .env                       # 环境变量（本地）
├── .env.sample                # 环境变量示例
├── .gitignore                 # Git 忽略文件
├── scripts/                   # 开发与发布脚本
├── README.md                 # 项目文档（中文）
└── README_EN.md              # 项目文档（英文）
```

## 🎯 功能演示

### 示例对话 1：简单问答（快速模式）

**用户**: 什么是人工智能？

**智能体**:
- 无需工具调用
- 直接基于基础知识回答
- 响应时间 < 3 秒

### 示例对话 2：实时搜索（快速模式）

**用户**: 当前最新的 AI 技术趋势是什么？

**智能体**:
1. 🔍 调用 `web_search`（topic=news, time_range=month）
2. 📊 展示搜索结果
3. 💬 生成带引用的答案

### 示例对话 3：深度研究（深度思考模式）

**用户**: 分析一下不同 Agent framework 的区别，并给出使用建议

**智能体**:
1. 🔍 搜索相关官方文档
2. 📄 提取关键页面内容
3. 🔍 交叉搜索更多资料
4. 📄 提取对比信息
5. 🧠 深度分析并生成详细报告

## 🐛 常见问题与故障排查

### 部署问题

#### 1. 刷新 `/s/<uuid>` 返回 404

**原因**：`deploy/nginx/site.conf` 里的 `try_files` 没生效——要么宝塔站点配置漏了 `include` 那一行，要么 `root` 指向的目录不是当前发布版本。

**排查**：
```bash
# 确认 include 生效
nginx -T | grep -A3 "location /"

# 确认软链接指向本次发布的 tag
readlink -f /www/chatagents/frontend/current
```

#### 2. `/api/` 返回 404 或路径被截断

**原因**：`proxy_pass` 末尾多了一条斜杠，把 `/api/` 前缀截断了。

**错误配置**：
```nginx
location /api/ {
    proxy_pass http://127.0.0.1:19180/;  # ❌ 末尾的斜杠导致路径被截断
}
```

**正确配置**（`deploy/nginx/site.conf` 里已是这样）：
```nginx
location /api/ {
    proxy_pass http://127.0.0.1:19180;  # ✓ 末尾无斜杠，保留完整路径
}
```

**验证**：
```bash
curl http://127.0.0.1:19180/api/sessions   # 后端直连
curl https://agent.ellisyuan.com/api/sessions  # 经 nginx 代理，应返回相同结果
```

#### 3. 流式回复攒一坨才吐出来（SSE 被静默缓冲）

**原因**：`/api/` 串了不止一层 nginx，或某一层缺了 `proxy_buffering off`。`X-Accel-Buffering` 只在离用户最近的那一层生效，失效不报错——见上文「SSE 只能穿一层 nginx」。

**解决方案**：确认 `/api/` 只经过宿主这一层 nginx（不要再套一层容器内 nginx），且 `deploy/nginx/site.conf` 里的 `proxy_buffering off` 没被面板手改覆盖掉。用 `curl -N` 实测确认逐条到达。

### 本地开发问题

#### 4. 后端服务无法启动

**问题**: `ConnectionRefusedError` 或端口被占用

**解决方案**:
```bash
# 检查端口占用
netstat -ano | findstr :8080  # Windows
lsof -i :8080                 # macOS/Linux

# 杀死占用进程（Linux/macOS）
kill -9 $(lsof -t -i:8080)

# 或修改端口（.env 文件）
PORT=8081
```

#### 5. API 密钥错误

**问题**: `401 Unauthorized` 或 "API 密钥验证失败"

**解决方案**:
- 检查 API 密钥格式：
  - Claude: `sk-ant-api-...`
  - Tavily: `tvly-...`
  - OpenAI: `sk-proj-...`
- 确认密钥未过期且有足够配额
- 检查 `.env` 文件是否正确加载
- Docker 用户：确认 `compose.yaml` 中的环境变量映射

```bash
# 测试环境变量加载
python -c "from dotenv import load_dotenv; import os; load_dotenv(); print(os.getenv('ANTHROPIC_API_KEY'))"
```

### 运行时问题

#### 6. 工具调用失败或超时

**问题**: Tavily 搜索/提取工具返回错误

**解决方案**:
- 检查网络连接（特别是防火墙/代理）
- 确认 Tavily API 配额充足
- 检查后端日志：`docker compose logs backend -f`
- 降低并发请求数量或增加超时时间

#### 7. 流式响应中断

**问题**: AI 回复中途停止或不完整

**解决方案**:
- 检查 LLM API 配额和速率限制
- 增加 Nginx 超时设置（如使用反向代理）
- 检查后端日志查看错误堆栈
- 尝试切换模型（如从 Opus 降级到 Sonnet）

### 数据问题

#### 8. 会话历史丢失

**问题**：重启容器后对话记录消失

**原因**：PostgreSQL 使用的 named volume 被删除，或迁移服务未成功执行。

**解决方案**：

`compose.yaml` 已通过 `postgres-data` 持久化 PostgreSQL 数据。正常重启不要使用 `docker compose down -v`：

```bash
docker compose down
docker compose up -d --build
```

备份数据库：

```bash
docker compose exec postgres pg_dump -U postgres -d chat_agents > chat_agents.sql
```

恢复数据库前先确认服务已停止，再按 PostgreSQL 工具的恢复流程导入 `chat_agents.sql`。

### 性能问题

#### 9. 响应速度慢

**优化建议**：
1. 使用更快的模型（Haiku > Sonnet > Opus）
2. 减少搜索结果数量（快速模式：3 条，深度模式：5 条）
3. 限制爬取页面数量
4. 使用 CDN 加速静态资源
5. 增加服务器资源（CPU/内存）

### 日志查看

```bash
# Docker 日志
docker compose logs backend --tail 100 -f
docker compose logs postgres --tail 100 -f

# Nginx 日志
sudo tail -f /var/log/nginx/chatbot.access.log
sudo tail -f /var/log/nginx/chatbot.error.log

# 查看所有容器状态
docker ps -a
docker compose ps
```

更多问题请先查看 backend 与数据库容器的日志。

## 🔮 未来计划

- [ ] 支持更多 LLM 提供商（Groq, etc.）
- [ ] 添加文件上传和分析功能
- [ ] 实现对话导出（Markdown/PDF）
- [ ] 优化流式响应性能

## 🤝 贡献

欢迎贡献！请随时提交 Issue 或 Pull Request。

### 提交前本地自检

```bash ci-command
uv sync --project backend --locked
uv run --project backend pytest backend/tests
uv run --project backend ruff check --config=backend/pyproject.toml backend
uv run --project backend ruff format --check --config=backend/pyproject.toml backend
uv run --project backend mypy --config-file=backend/pyproject.toml backend
```

### 贡献流程

1. Fork 本仓库
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建 Pull Request

## 📄 许可证

本项目采用 [MIT 许可证](LICENSE) 开源。

## 👤 作者

**Yuan**

- 📝 博客: [https://blog.geekie.site](https://blog.geekie.site)
- 📧 邮箱: [yuan.sn@outlook.com](mailto:yuan.sn@outlook.com)
- 🔗 GitHub: [EllisYuan](https://github.com/EllisYuan)

## 🙏 致谢

本项目基于以下开源项目构建：

- [FastAPI](https://fastapi.tiangolo.com/) - 高性能 API 框架
- [LangChain](https://www.langchain.com/) - LLM 应用框架
- [Anthropic Claude](https://www.anthropic.com/) - 强大的语言模型
- [Tavily](https://tavily.com/) - AI 优化的搜索 API



---

<div align="center">

**⭐ 如果这个项目对你有帮助，请给它一个星标！**

Made with ❤️ by Yuan

</div>
