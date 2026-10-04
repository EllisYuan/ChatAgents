#!/usr/bin/env python3
"""在独立的 PostgreSQL 容器上执行确定性检查。"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT = f"chatagents-test-{uuid.uuid4().hex[:12]}"
PORT = os.environ.get("CHATAGENTS_TEST_DB_PORT", "55432")
DATABASE_URL = f"postgresql+psycopg://root:Agent%40Dev_1@127.0.0.1:{PORT}/chat_agents"
COMPOSE = ["docker", "compose", "-p", PROJECT, "-f", "compose.yaml", "-f", "compose.test.yaml"]


def main() -> int:
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    env["CHATAGENTS_TEST_DB_PORT"] = PORT
    env["DATABASE_URL"] = DATABASE_URL
    env["POSTGRES_DB"] = "chat_agents"
    env["POSTGRES_USER"] = "root"
    env["POSTGRES_PASSWORD"] = "Agent@Dev_1"
    env["POSTGRES_PASSWORD_URLENCODED"] = "Agent%40Dev_1"
    if os.name == "nt":
        git = shutil.which("git")
        bash = Path(git).resolve().parents[1] / "bin" / "bash.exe" if git else None
        if bash is None or not bash.is_file():
            raise SystemExit("测试检查需要 Git Bash；请安装 Git for Windows")
        env["PATH"] = f"{bash.parent}{os.pathsep}{env['PATH']}"
    result = 1
    try:
        subprocess.run(
            [*COMPOSE, "up", "-d", "--wait", "--wait-timeout", "90", "postgresql"],
            cwd=ROOT,
            env=env,
            check=True,
        )
        result = subprocess.run(
            ["uv", "run", "--project", "backend", "python", "scripts/dev.py", "check"],
            cwd=ROOT,
            env=env,
            check=False,
        ).returncode
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"测试环境启动失败：{exc}", file=sys.stderr)
    except KeyboardInterrupt:
        print("测试已中断，正在清理测试 PostgreSQL", file=sys.stderr)
        result = 130
    finally:
        try:
            stopped = subprocess.run(
                [*COMPOSE, "down", "-v", "--remove-orphans"], cwd=ROOT, env=env
            )
            if stopped.returncode != 0:
                print(f"测试 PostgreSQL 清理失败，请检查 {PROJECT} Compose 项目", file=sys.stderr)
                result = result or stopped.returncode
        except OSError as exc:
            print(f"测试 PostgreSQL 清理失败：{exc}", file=sys.stderr)
            result = result or 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
