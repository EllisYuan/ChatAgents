"""仓库根目录的开发、测试与发布命令入口。"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run(command: list[str]) -> None:
    executable = shutil.which(command[0])
    if executable is None:
        raise SystemExit(f"找不到命令：{command[0]}")
    child_env = os.environ.copy()
    child_env.pop("VIRTUAL_ENV", None)
    try:
        subprocess.run([executable, *command[1:]], cwd=ROOT, env=child_env, check=True)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc


def dev_backend() -> None:
    _run(["uv", "run", "--project", "backend", "python", "backend/dev.py"])


def dev_frontend() -> None:
    _run(["uv", "run", "--no-project", "python", "frontend/dev.py"])


def test() -> None:
    _run(["uv", "run", "--project", "backend", "python", "scripts/test_env.py"])


def prod_deploy() -> None:
    if len(sys.argv) != 2 or not re.fullmatch(
        r"v[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", sys.argv[1]
    ):
        raise SystemExit("用法：uv run prod-deploy <tag>（例如 v1.4.2）")
    if os.name == "nt":
        raise SystemExit("生产部署只能在已配置的 Linux 服务器上运行")
    if subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, check=True, capture_output=True
    ).stdout:
        raise SystemExit("工作区存在未提交的更改；部署脚本会 checkout tag，请先处理工作区")
    _run(["bash", "scripts/deploy.sh", sys.argv[1]])
