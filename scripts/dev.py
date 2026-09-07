#!/usr/bin/env python3
"""ChatAgents 跨平台开发命令入口。"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"

# 后端监听端口。容器内（Dockerfile）、compose 映射的容器侧、前端 dev 代理默认值
# 都是它，且与 uvicorn 自身的默认端口一致——即便忘了 --port 也不会错配。
BACKEND_PORT = "8000"


def executable(name: str) -> str:
    candidates = [f"{name}.cmd", f"{name}.exe", name] if os.name == "nt" else [name]
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise RuntimeError(f"找不到命令：{name}")


def run(command: Sequence[str], *, cwd: Path = ROOT) -> None:
    resolved = [executable(command[0]), *command[1:]]
    print(f"\n$ {' '.join(command)}", flush=True)
    subprocess.run(resolved, cwd=cwd, check=True)


def uv(*args: str) -> None:
    run(["uv", "run", "--project", "backend", *args])


def setup() -> None:
    run(["uv", "sync", "--project", "backend", "--locked"])
    run(["npm", "ci"], cwd=FRONTEND)


def db() -> None:
    run(["docker", "compose", "up", "-d", "postgresql"])
    uv("python", "-m", "alembic", "upgrade", "head")


def serve() -> None:
    """本地直起后端。密钥由包初始化时的 `load_dotenv` 从仓库根 `.env` 读入。"""

    uv(
        "python",
        "-m",
        "uvicorn",
        "chat_agents.main:app",
        "--app-dir",
        "backend/src",
        "--reload",
        "--port",
        BACKEND_PORT,
    )


def web() -> None:
    """本地直起前端 dev server；代理目标由 vite 默认值指向同一个端口。"""

    run(["npm", "run", "dev"], cwd=FRONTEND)


def test() -> None:
    uv("pytest", "backend/tests")


def contract() -> None:
    uv("pytest", "backend/tests/contract_test.py", "-m", "contract", "--maxfail=1")


def lint() -> None:
    uv(
        "ruff",
        "check",
        "--config=backend/pyproject.toml",
        "backend",
        "scripts/dev.py",
        "scripts/check-docs-drift.py",
    )
    uv(
        "ruff",
        "format",
        "--check",
        "--config=backend/pyproject.toml",
        "backend",
        "scripts/dev.py",
        "scripts/check-docs-drift.py",
    )
    uv("mypy", "--config-file=backend/pyproject.toml", "backend")
    uv("lint-imports", "--config", "backend/pyproject.toml", "--no-cache")
    run(["npm", "run", "lint"], cwd=FRONTEND)


def typecheck() -> None:
    run(["npm", "run", "typecheck"], cwd=FRONTEND)


def build() -> None:
    run(["npm", "run", "build"], cwd=FRONTEND)


def docs() -> None:
    uv("python", "scripts/check-docs-drift.py")
    run(["bash", "scripts/check-readme-ci-commands.sh"])


def guards() -> None:
    """检查器自身的反向测试——主动注入违规，确认每道门禁真的会红（ADR-0034）。"""

    run(["bash", "scripts/test-import-contracts.sh"])
    run(["bash", "scripts/test-check-docs-drift.sh"])
    run(["bash", "scripts/test-block-dangerous-hook.sh"])


def check() -> None:
    for task in (test, contract, lint, typecheck, build, docs, guards):
        task()


TASKS = {
    "setup": setup,
    "db": db,
    "serve": serve,
    "web": web,
    "test": test,
    "contract": contract,
    "lint": lint,
    "typecheck": typecheck,
    "build": build,
    "docs": docs,
    "guards": guards,
    "check": check,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task", choices=TASKS)
    args = parser.parse_args()
    try:
        TASKS[args.task]()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"\n开发命令失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
