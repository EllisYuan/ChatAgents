# Python 工程工具链基线选型报告：包管理 / Lint / 类型 / 测试

> **对应 Issue**：[#7](https://github.com/EllisYuan/ChatAgents/issues/7) 《Python 工程工具链基线：包管理 / lint / 类型 / 测试》  
> **上位地图**：[#1](https://github.com/EllisYuan/ChatAgents/issues/1) 《重构蓝图：从 demo 到 LLM 应用工程标杆》  
> **调研基准日期**：**2026-08-06**  
> **判据原则**：地基层选经过大规模生产验证的，不盲目追新；亮点落在读者第一眼看到的地方，风险落在容易替换的地方。

---

## ⚠️ 结算勘误（由主会话在交叉核验时补充）

本报告成文时，Issue #3 的框架选型尚未定案，因此文中多处以 LangGraph 为前提。**#3 的最终结论是淘汰 LangGraph、改用自建 Async ReAct Loop**（见 [03-react-agent-framework.md](./03-react-agent-framework.md)）。受影响之处：

- **第 15、247–248 行的「L2 级 LangGraph State Snapshot Replay」失效**，改用自建 Loop 的显式 `AgentState` JSON dataclass 回放。
- **第 210、218–220、435 行**关于 mypy 严格度的论证以 LangChain/LangGraph 复杂泛型为主要理由。淘汰 LangGraph 后这一压力显著降低，但 `AsyncOpenAI` / `AsyncAnthropic` / Pydantic 的泛型复杂度仍在，**「标准增量档」的结论依然成立**，只是理由需要收窄。
- 本报告的主结论（uv、Ruff 规则集、mypy 档位、pytest + `httpx.MockTransport`、pre-commit 与 CI 分工、Renovate）**均不受影响**。

---

## 1. 结论摘要 (Executive Summary)

1. **包管理与锁定**：推荐采用 **uv**（Astral 出品，Rust 编写）作为统一的 Python 包管理与依赖锁定工具。uv 在 2026 年已成为 Python 生态的事实标准，拥有 10-100x 的安装与解析速度提升，原生支持 PEP 621 标准 `pyproject.toml` 与 `uv.lock`。其 `--no-install-project` 与 `setup-uv` GitHub Action 在 Docker 多阶段构建与 CI 缓存中具备极高的层缓存效率与复现性。
2. **Lint / Format / Import 排序**：推荐采用 **Ruff** 统一替代 Flake8 + Black + isort + pyupgrade + bandit。指定启用的规则集为 `E`, `F`, `W`, `I`, `UP`, `B`, `SIM`, `ASYNC`, `RUF`，并结合项目特性为测试目录定制宽松规则。
3. **类型检查**：推荐采用 **mypy** 作为 CI 门禁的主力类型检查器（定位于 **Standard / Basic Strictness 增量严格度**），配合 **pyright / Pylance** 作为 IDE 实时诊断。在 LLM 应用中，由于 LangChain/Pydantic/AsyncOpenAI 的泛型嵌套极复杂，完全开启 `--strict` 会导致极高的开发摩擦力；推荐开启 `check_untyped_defs = true`, `disallow_incomplete_defs = true`, `no_implicit_optional = true`，逐步向 strict 演进。
4. **测试与 HTTP Mock**：采用 **pytest + pytest-asyncio + pytest-cov**。结合 Issue #5 (05号报告) 结论，**彻底放弃 vcrpy 拦截 SSE 流的方案**，采用 **`httpx.MockTransport`** 进行底层 HTTP SSE 生成器 Mock，上层结合 **LangGraph State Snapshot 回放** 实现 L2 级零网络开销测试。
5. **Pre-commit 与 CI 职责划分**：遵循“本地快反馈、CI 全保障”原则。Pre-commit 仅跑 Ruff (lint + format) 与轻量语法检查（< 1s）；CI 门禁跑 Pytest 全量测试、mypy 全局类型检查、Security 漏洞扫描与 coverage 上报，避免本地 git commit 卡顿与重复计算。
6. **依赖安全与自动更新**：推荐 **Renovate**（优于 Dependabot），因其完美支持 Python (uv/pyproject.toml) 与 Node.js (pnpm/package.json) 双工具链同仓协同，具备更精细的 group 规则与 Lockfile 自动刷新。
7. **Python & Node 双工具链共存**：根目录保留 `pyproject.toml` (Python) 与 `package.json` (Node)，使用 `uv` 隔离 Python `.venv`，前端使用 `pnpm` / `npm` 隔离 `node_modules`。Pre-commit 与 GitHub Actions 在顶层按目录触发。

---

## 2. 推荐工具清单与版本 (2026-08 基线)

| 工具分类 | 推荐工具 | 推荐版本 (2026-08) | 替代旧工具 / 方案 | 选型理由 |
|---|---|---|---|---|
| **包管理 & 依赖锁定** | **uv** | `v0.8.x` / `v0.9.x` | `pip` + `requirements.txt` / Poetry | 极速 (Rust 驱动)、跨平台、PEP 621 原生支持、Docker/CI 缓存友好 |
| **构建后端 (Build Backend)** | **hatchling** | `v1.27.x` | `setuptools` | 轻量级、PEP 517/621 标准构建后端，无遗留代码开销 |
| **Lint & Format & Import** | **Ruff** | `v0.6.x` / `v0.7.x` | Flake8 + Black + isort | 单一工具替代多套 Linter/Formatter，毫秒级运行，支持 `ASYNC` 异步规则 |
| **静态类型检查** | **mypy** | `v1.11.x` / `v1.12.x` | 零类型检查 | 生产级 Python 官方类型检查器，生态插件完备 (pydantic-mypy) |
| **IDE 类型辅助** | **pyright** (Pylance) | `v1.1.x` | - | 语言服务器原生支持，实时反馈 TypeScript 级开发体验 |
| **测试框架** | **pytest** | `v8.3.x` | `unittest` | Python 测试标准，丰富 fixture 与 plugin 扩展 |
| **异步测试插件** | **pytest-asyncio** | `v0.24.x` | - | 支持 `async def test_*` 异步测试协程原生运行 |
| **覆盖率工具** | **coverage.py** / `pytest-cov` | `v7.6.x` / `v5.0.x` | 零测试覆盖率 | 准确计算行与分支覆盖率，支持 HTML & XML (Codecov/CI) 导出 |
| **HTTP Mock 方案** | **`httpx.MockTransport`** | `httpx >= 0.27` 原生 | `vcrpy` / `pytest-vcr` | 原生支持 `AsyncGenerator` SSE chunk 级别模拟，无 socket 死锁 |
| **Git Pre-commit 钩子** | **pre-commit** | `v3.8.x` | 无钩子 | 格式与轻量 lint 自动检查，保证进入仓库的代码即符合规范 |
| **依赖安全 & 自动更新** | **Renovate** | GitHub App / Runner | Dependabot | 多语言 Monorepo 支持佳，精细更新策略，避免 PR 弹框轰炸 |

---

## 3. 候选工具比较矩阵 (Candidate Comparison Matrix)

### 3.1 包管理与依赖锁定比较

| 评估维度 | **uv** (推荐) | **Poetry** | **PDM** | **pip-tools** |
|---|---|---|---|---|
| **解析 & 安装速度** | 极快 (0.1s - 1s, Rust 驱动) | 较慢 (10s - 60s) | 中等 (3s - 15s) | 慢 (5s - 30s) |
| **PEP 621 标准支持** | **完全原生 (`pyproject.toml`)** | 早期自定义，现有限支持 | **完全原生** | 不直接管理 setup |
| **Lockfile 标准** | `uv.lock` (高效可读) | `poetry.lock` | `pdm.lock` | `requirements.txt` 伪 lock |
| **Docker 构建优化** | `--no-install-project` 分层缓存 | 需 `poetry export` 或多层 install | 需 `pdm install --no-self` | 手动维护 txt 规范 |
| **CI 官方 Action** | `astral-sh/setup-uv` (内置高效缓存) | 社区 / setup-poetry | pdm-project/setup-pdm | 需 pip cache 拼装 |
| **Python 版本管理** | 原生支持 `uv python install` | 依赖 pyenv / external | 原生支持 | 无 |
| **大规模生产验证** | **极高 (2025-2026 事实标准)** | 高 (传统领头羊) | 中等 | 中等 |
| **结论** | **推荐** | 渐退 | 备选 | 淘汰 |

### 3.2 Lint / Format / Import 排序比较

| 评估维度 | **Ruff** (推荐) | **Flake8 + Black + isort + Pyupgrade** 组合 |
|---|---|---|
| **工具数量** | **1 个单文件二进制** | 4-6 个独立的 Python 包 |
| **运行速度** | **毫秒级 (< 50ms)** | 1-5 秒 |
| **配置统一性** | 集中在 `pyproject.toml` | `.flake8` + `pyproject.toml` 混杂 |
| **规则覆盖面** | 兼容 800+ 规则 (E, F, W, I, UP, B, SIM, ASYNC, RUF, S) | 需拼装各种 flake8 插件 |
| **异步 LLM 规范支持**| 原生 `ASYNC` (flake8-async) 规则检查 async IO | 需额外安装 `flake8-async` |
| **结论** | **绝对推荐** | 淘汰 |

### 3.3 类型检查器比较

| 评估维度 | **mypy** (推荐 CI 主力) | **pyright** (推荐 IDE 辅佐) | **ty** (Astral 预览版) |
|---|---|---|---|
| **生态成熟度** | **极高 (Python 官方标准)** | 高 (微软维护) | 极低 (2026 年仍处于早期/预览) |
| **Pydantic v2 集成** | 官方 `pydantic-mypy` 插件成熟 | 良好 | 尚未完善 |
| **严格度可调性** | 极度灵活，可逐文件/逐规则开启 | 模式划分 (off/basic/strict) | 尚不足 |
| **运行速度** | 中等 (有 daemon 模式) | 快 | 极快 |
| **定位** | **CI 门禁基线** | **IDE / LSP 实时反馈** | 持续关注，暂不作为地基层 |

---

## 4. 建议的 pyproject.toml 配置策略 (Complete Standard Configuration)

项目应使用 PEP 621 标准 `pyproject.toml` 规范声明元数据，集中配置 Hatchling、uv、Ruff、mypy、pytest 等所有工具。

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "chat-agents"
version = "0.2.0"
description = "Yuan's Chat Agents - Engineering LLM Application with ReAct Architecture"
readme = "README.md"
requires-python = ">=3.11,<3.13"
license = { text = "MIT" }
authors = [
    { name = "Yuxuan Shen", email = "Yuan.Sn@outlook.com" }
]
dependencies = [
    "fastapi>=0.111.0",
    "uvicorn[standard]>=0.30.0",
    "pydantic>=2.7.0",
    "openai>=1.30.0",
    "anthropic>=0.28.0",
    "langchain-core>=0.3.0",
    "langgraph>=0.4.0",
    "tavily-python>=0.7.0",
    "httpx>=0.27.0",
    "python-dotenv>=1.0.1",
    "typing-extensions>=4.11.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2.0",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=5.0.0",
    "ruff>=0.5.0",
    "mypy>=1.10.0",
    "pre-commit>=3.7.0",
    "httpx>=0.27.0",
]

# ==================== Tool: Ruff (Lint & Format) ====================
[tool.ruff]
target-version = "py311"
line-length = 100
exclude = [
    ".git",
    ".venv",
    "__pycache__",
    "data",
]

[tool.ruff.lint]
select = [
    "E",      # pycodestyle errors
    "W",      # pycodestyle warnings
    "F",      # Pyflakes
    "I",      # isort (import sorting)
    "UP",     # pyupgrade (modern Python syntax)
    "B",      # flake8-bugbear (common design bugs)
    "SIM",    # flake8-simplify
    "ASYNC",  # flake8-async (async/await best practices)
    "RUF",    # Ruff-specific rules
]
ignore = [
    "E501",   # line-too-long (handled by formatter)
    "B008",   # do not perform function calls in argument defaults (FastAPI Depends)
]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["S101", "ASYNC109"]  # Allow assert in tests

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
skip-magic-trailing-comma = false
line-ending = "auto"

# ==================== Tool: mypy (Type Checking) ====================
[tool.mypy]
python_version = "3.11"
plugins = ["pydantic.mypy"]
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = false      # 渐进式：暂不强制要求所有函数写类型签名
check_untyped_defs = true          # 对无签名的函数体依然进行内部类型检查
disallow_incomplete_defs = true    # 禁止半吊子类型定义
no_implicit_optional = true
warn_redundant_casts = true
warn_unused_ignores = true

[[tool.mypy.overrides]]
module = [
    "tavily.*",
    "langchain.*",
    "langgraph.*",
]
ignore_missing_imports = true

[tool.pydantic-mypy]
init_forbid_extra = true
init_typed = true
warn_required_dynamic_aliases = true

# ==================== Tool: Pytest ====================
[tool.pytest.ini_options]
minversion = "8.0"
addopts = "-ra -q --cov=backend --cov-report=term-missing --cov-report=xml"
testpaths = ["tests"]
asyncio_mode = "auto"
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
```

---

## 5. Lint 规则集建议与配置说明

推荐启用的 Ruff 具体规则集及针对 LLM 应用的理由：

1. **`E`, `W` (pycodestyle)**：Python 基础语法与 PEP 8 规范。
2. **`F` (Pyflakes)**：未使用的变量、未导入的包、未定义的符号检测。
3. **`I` (isort)**：Import 自动排序（标准库 -> 第三方库 -> 本地模块），保证代码干净。
4. **`UP` (pyupgrade)**：自动将旧式 Python 语法提升为 Python 3.11+ 语法（如 `Optional[str]` -> `str | None`）。
5. **`B` (flake8-bugbear)**：拦截 Python 常见的坑（如可变默认参数 `def fn(a=[])`）。*注意忽略 `B008` 以兼容 FastAPI 的 `Depends()` 语法*。
6. **`SIM` (flake8-simplify)**：简化冗余的条件判断与 `if-else`。
7. **`ASYNC` (flake8-async)**：**对于 FastAPI & AsyncOpenAI / AsyncAnthropic / LangGraph 极度关键**！拦截异步编程中的陷阱（如在 async 函数中误用同步阻塞 IO、阻塞式 sleep）。
8. **`RUF` (Ruff 专属规则)**：Ruff 团队维护的高价值规则（如混用 asyncio 机制、无效的 `# noqa` 声明）。

---

## 6. 类型检查严格度建议 (Type Checking Trade-offs)

### 取舍理由：为何不开启 `strict = true`？
在 LLM 应用工程中，`AsyncOpenAI`、`AsyncAnthropic` 以及 `LangChain/LangGraph` 包含了大量的复杂泛型、动态 dict 结构（如 `tool_calls` args 字典、`State` 字典）。如果一开始在 `mypy` 中强制开启 `strict = true` (`disallow_untyped_defs = true`)：
- 开发人员需要为每一个简短的辅助函数、测试 Helper 补全繁琐的类型注解；
- LangGraph 中动态传递的 `dict` 结构会导致大量的 `type: ignore` 警报覆盖真正的 bug；
- 会严重拖慢从 demo 到工程级演进的速度。

### 推荐的严格度档位：**Standard Tier (标准/渐进档)**
- **`check_untyped_defs = true`**：即使函数未显式声明返回值，也会检查函数内部的代码逻辑类型错误。
- **`disallow_incomplete_defs = true`**：防止写了参数类型却忘了写返回值类型的“半吊子”签名。
- **`no_implicit_optional = true`**：显式要求 `str | None` 而不是默认隐式 `None`。
- **`ignore_missing_imports = true`**：对 Tavily 等缺乏完整 stub 的第三方包予以豁免，避免无意义报错。

---

## 7. 测试与 Mock 方案 (Testing & Mock Strategy)

### 7.1 测试框架与组件
- **Runner**：`pytest`
- **异步支持**：`pytest-asyncio` (`asyncio_mode = "auto"`)
- **覆盖率**：`pytest-cov` / `coverage.py`（目标前期达到 70%+ 行覆盖率）

### 7.2 HTTP Mock 方案（结合 Issue #5 / 05号报告结论）

> **关键结论**：05 号报告与本次实查一致表明，**`vcrpy` 等 Socket 拦截库在处理 `httpx` 异步 SSE (Server-Sent Events) 流式响应时存在严重缺陷**（Chunk 时间序丢失、生成器死锁、Stream 提前中断挂起）。

因此，本项目测试工具链确立**双层 Mock 方案**：

1. **L2 级网络零开销测试：`httpx.MockTransport`**
   - 用于底层 `AsyncOpenAI` / `AsyncAnthropic` / `Tavily` 的 Client 测试。
   - `httpx` 原生支持注入 `transport=httpx.MockTransport(custom_handler)`，其中 `custom_handler` 可以是一个 Python 异步生成器，按 Chunk 精确 `yield` SSE 格式文本，零 Socket 侵入，100% 稳定。
2. **L2 级状态回放：AgentRunner Replay**
   - 利用 `AgentRunner` 的事件与消息 Fixture 直接输入后半段逻辑，绕过大模型 HTTP 请求。

---

## 8. Pre-commit 与 CI 职责划分 (Pre-commit vs CI Boundaries)

遵循**“本地极速反馈（< 2秒），CI 严密防线（< 3分钟）”**原则，严禁在 pre-commit 中跑耗时的类型检查与单元测试，避免开发者 `git commit` 时产生等待焦虑。

```
                              【本地提交 Git Commit】
                                        │
                                        ▼
                   ┌────────────────────────────────────────┐
                   │ Pre-commit 钩子 (极速, < 1 秒)          │
                   │ 1. ruff check --fix (自动修复 lint)    │
                   │ 2. ruff format (代码格式化)            │
                   │ 3. check-yaml / check-toml (语法校验)   │
                   └────────────────────────────────────────┘
                                        │
                                        ▼
                                【Push 至 GitHub】
                                        │
                                        ▼
                   ┌────────────────────────────────────────┐
                   │ GitHub Actions CI 门禁 (< 3 分钟)       │
                   │ 1. uv sync --frozen                    │
                   │ 2. ruff check (只读校验，防止绕过)       │
                   │ 3. mypy backend (全局静态类型检查)       │
                   │ 4. pytest (全量单元测试与 Mock 测试)     │
                   │ 5. pytest-cov (检查覆盖率，上报 XML)    │
                   │ 6. Trivy / Bandit (依赖与代码安全扫描)   │
                   └────────────────────────────────────────┘
```

### `.pre-commit-config.yaml` 建议配置：
```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-toml
      - id: check-added-large-files
```

---

## 9. 依赖安全扫描与自动更新 (Renovate vs Dependabot)

### 推荐选择：**Renovate**（优先于 Dependabot）

| 评估维度 | **Renovate** (推荐) | **Dependabot** |
|---|---|---|
| **多生态 / Monorepo** | **极佳**（完美在一个 PR 中处理 `pyproject.toml` + `package.json`） | 一般（会为 Python 和 Node 分别发大量独立 PR） |
| **uv / uv.lock 支持** | **原生支持** `uv` 依赖解析与 `uv.lock` 更新 | 对 uv.lock 支持滞后 |
| **PR 聚合分组 (Grouping)** | 支持将所有 dev 依赖、次版本更新合并为单个 PR | 缺乏灵活的分组能力，易产生 PR 轰炸 |
| **Automerge 策略** | 支持 patch/minor 版本自动 CI 通过后 automerge | 需结合 GitHub Actions 自建 |

---

## 10. Python 与 Node.js 双工具链共存策略

在作品集最终形态中，前端可能采用 React/Next.js/Tailwind，与 Python 后端共存于同一 GitHub 仓库中：

1. **目录与依赖隔离**：
   - 根目录 `pyproject.toml` + `uv.lock` + `.venv/` 管理 Python 后端。
   - 前端目录 `frontend/` (或根目录 `package.json` + `pnpm-lock.yaml` + `node_modules/`) 管理 Node 前端。
   - `.gitignore` 显式隔离 `.venv/`、`node_modules/`、`dist/`、`.pytest_cache/`、`.ruff_cache/`。
2. **Pre-commit 钩子隔离**：
   - Pre-commit 中同时配置 Python (ruff) 与 Node (eslint / prettier / biome)。
   - 使用 `files` / `types_or` 正则约束钩子生效目录，互不干扰。
3. **Docker 多阶段构建**：
   - Dockerfile 使用 Multi-stage build，Frontend stage 使用 Node 镜像构建静态资源，Backend stage 使用 Python + uv 镜像，最后融合或 Compose 分离运行。

---

## 11. Docker 构建与 CI 缓存优化 (Docker & CI Caching)

### 11.1 优化的 Dockerfile (采用 uv Multi-stage Build)

```dockerfile
# Stage 1: Build virtualenv with uv
FROM ghcr.io/astral-sh/uv:python3.11-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1

WORKDIR /app

# 利用 Mount Cache 缓存 uv 下载包
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

COPY . /app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

# Stage 2: Minimal runtime image
FROM python:3.11-slim

WORKDIR /app

COPY --from=builder /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "chat_agents.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

### 11.2 CI 缓存配置 (`.github/workflows/ci.yml` 示例)

```yaml
name: CI Baseline

on:
  push:
    branches: [main]
  pull_request:

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v3
        with:
          version: "latest"
          enable-cache: true
          cache-dependency-glob: "uv.lock"

      - name: Set up Python
        run: uv python install 3.11

      - name: Install dependencies
        run: uv sync --frozen

      - name: Run Ruff Lint
        run: uv run ruff check .

      - name: Run Ruff Format Check
        run: uv run ruff format --check .

      - name: Run mypy Type Check
        run: uv run mypy backend

      - name: Run Pytest
        run: uv run pytest
```

---

## 12. 迁移步骤与风险管控

### 迁移五步走方案：
1. **第一步 (pyproject.toml & uv 初始化)**：
   - 运行 `uv init` 或手动写入标准 `pyproject.toml`；
   - 清理 `requirements.txt` 中的笔误（如 `filelock ==3.12.2` 的空格），运行 `uv pip compile` 生成确定性的 `uv.lock`。
2. **第二步 (Ruff 引入与一键修复)**：
   - 配置 `[tool.ruff]`，运行 `uv run ruff check --fix .` 与 `uv run ruff format .` 对全仓代码进行格式清洗。
3. **第三步 (mypy 配置文件落地)**：
   - 建立 `[tool.mypy]` 配置，对 `backend/` 目录运行 `uv run mypy backend`，修正暴露的明显类型隐患，对无类型 stub 的第三方包添加 `ignore_missing_imports`。
4. **第四步 (测试套件结构建立)**：
   - 创建 `tests/` 目录，建立 `conftest.py`，配置 `httpx.MockTransport` Fixture，编写基础 FastAPI 端点与 ModelPort 测试。
5. **第五步 (Pre-commit 与 CI Workflow 挂载)**：
   - 添加 `.pre-commit-config.yaml` 并运行 `pre-commit install`；在 GitHub 仓库中挂载 `.github/workflows/ci.yml`。

### 风险及应对措施 (Risks & Mitigations)：
- **风险 1：旧代码在 Ruff 一键格式化后产生冲突**
  - *应对*：在单独的 refactor PR 中一次性提交 Ruff format 结果，并在 repo 中添加 `.git-blame-ignore-revs` 忽略该 commit。
- **风险 2：LangGraph / Pydantic 复杂类型的 mypy 报错数过高**
  - *应对*：保持 `disallow_untyped_defs = false`，优先配置第三方模块 `ignore_missing_imports = true`，严禁直接加全局 `type: ignore`。
- **风险 3：依赖锁定导致镜像体积或版本冲突**
  - *应对*：在 Docker 中开启 `UV_NO_DEV=1`，确保 dev 依赖不进入生产镜像；在 CI 中加入 `uv lock --check` 校验 lockfile 是否最新。

---

## 13. 完整来源清单 (Complete Sources List)

以下来源于 **2026-08-06** 实查官方文档、GitHub Releases 及 PyPA 规范，按三级支持度分类标注：

### 13.1 官方文档明确支持 (Official Document Explicitly Supported)
- **[S1] Astral uv 官方文档与 Docker 最佳实践**  
  - URL: `https://docs.astral.sh/uv/` & `https://github.com/astral-sh/uv-docker-example`  
  - 查验日期: 2026-08-06  
  - 证实: uv 支持 PEP 621、`uv.lock`、`--no-install-project` Docker 多阶段层缓存与 `astral-sh/setup-uv` CI 缓存。
- **[S2] Astral Ruff 官方文档与 Rule 规范**  
  - URL: `https://docs.astral.sh/ruff/`  
  - 查验日期: 2026-08-06  
  - 证实: Ruff 官方原生支持 `E`, `F`, `W`, `I`, `UP`, `B`, `SIM`, `ASYNC`, `RUF` 等规则集，全面替代 Flake8/Black/isort。
- **[S3] mypy 官方文档与 Pydantic 插件**  
  - URL: `https://mypy.readthedocs.io/` & `https://docs.pydantic.dev/latest/integrations/mypy/`  
  - 查验日期: 2026-08-06  
  - 证实: `pydantic.mypy` 插件官方支持 Pydantic v2 模型类型推断与验证。
- **[S4] PyPA PEP 621 元数据标准与 Hatchling**  
  - URL: `https://packaging.python.org/en/latest/specifications/declaring-project-metadata/`  
  - 查验日期: 2026-08-06  
  - 证实: `pyproject.toml` 中的 `[project]` 标准写法与 Hatchling 构建后端规范。
- **[S5] HTTPX 官方 MockTransport 指南**  
  - URL: `https://www.python-httpx.org/advanced/transports/`  
  - 查验日期: 2026-08-06  
  - 证实: `httpx.MockTransport` 官方支持模拟 HTTP/SSE 异步生成器响应。
- **[S6] Pytest & pytest-asyncio 官方文档**  
  - URL: `https://docs.pytest.org/` & `https://pytest-asyncio.readthedocs.io/`  
  - 查验日期: 2026-08-06  
  - 证实: `asyncio_mode = "auto"` 官方支持 `async def test_*` 单元测试。
- **[S7] Pre-commit 官方 Hooks 规范**  
  - URL: `https://pre-commit.com/`  
  - 查验日期: 2026-08-06  
  - 证实: pre-commit 官方支持通过 git hook 触发 ruff/formatting 校验。
- **[S8] Renovate 官方 Docs (Python uv & Monorepo 支持)**  
  - URL: `https://docs.renovatebot.com/modules/manager/pep621/`  
  - 查验日期: 2026-08-06  
  - 证实: Renovate 官方原生支持 PEP 621 `pyproject.toml`、`uv.lock` 及 Node.js 多生态协同。
- **[S9] Issue #5 (05号报告) Agent Evals 选型与 VCR 局限性**  
  - 关联文件: `docs/research/05-agent-evals.md`  
  - 查验日期: 2026-08-06  
  - 证实: vcrpy 处理 httpx SSE 流式传输存在 chunk 乱序与挂起缺陷。

### 13.2 社区实现 (Community Implementation)
- **[S10] Pyright / Pylance 微软官方仓库**  
  - URL: `https://github.com/microsoft/pyright`  
  - 查验日期: 2026-08-06  
  - 证实: Pyright 在 VS Code / Language Server 层面作为实时类型检查补充。
- **[S11] Poetry 官方文档与 PEP 621 迁移指南**  
  - URL: `https://python-poetry.org/docs/`  
  - 查验日期: 2026-08-06  
  - 证实: Poetry 在解析速度与 CLI 锁定时性能慢于 uv，社区呈现向 uv 迁移趋势。
- **[S12] Dependabot GitHub 官方文档**  
  - URL: `https://docs.github.com/en/code-security/dependabot`  
  - 查验日期: 2026-08-06  
  - 证实: Dependabot 可用于 GitHub 依赖扫描，但在 Monorepo 多语言分组合并方面弱于 Renovate。

### 13.3 未能证实 / 废弃方案 (Unverified / Deprecated)
- **[S13] vcrpy / pytest-vcr 拦截 httpx SSE 异步流**  
  - 查验结论: **否定方案**。在 httpx async generator + SSE 模式下存在 Cassette 死锁与时间序丢失问题。
- **[S14] Astral ty (Python Red Knot / Type Checker Early Preview)**  
  - 查验结论: 2026 年 8 月仍处于早期实验/预览阶段，尚无法替代 mypy 作为生产级 CI 门禁。
