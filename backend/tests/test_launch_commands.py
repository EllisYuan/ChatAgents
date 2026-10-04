"""仓库根目录快捷命令的转发契约。"""

from __future__ import annotations

import ast
import runpy
import subprocess
import sys
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import chatagents_launch  # noqa: E402


def test_root_scripts_delegate_to_environment_entrypoints() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = project["project"]["scripts"]
    assert scripts == {
        "dev-backend": "chatagents_launch:dev_backend",
        "dev-frontend": "chatagents_launch:dev_frontend",
        "test": "chatagents_launch:test",
        "prod-deploy": "chatagents_launch:prod_deploy",
    }
    with patch.object(chatagents_launch, "_run") as run:
        chatagents_launch.dev_backend()
        chatagents_launch.dev_frontend()
        chatagents_launch.test()
    assert [call.args[0] for call in run.call_args_list] == [
        ["uv", "run", "--project", "backend", "python", "backend/dev.py"],
        ["uv", "run", "--no-project", "python", "frontend/dev.py"],
        ["uv", "run", "--project", "backend", "python", "scripts/test_env.py"],
    ]


def test_environment_entries_use_existing_dev_commands() -> None:
    for entry in ("backend/dev.py", "frontend/dev.py"):
        tree = ast.parse((ROOT / entry).read_text(encoding="utf-8"))
        assert any(
            isinstance(node, ast.Constant) and node.value == "scripts/dev.py"
            for node in ast.walk(tree)
        )


def test_db_command_uses_backend_alembic_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dev = runpy.run_path(str(ROOT / "scripts/dev.py"))
    monkeypatch.chdir(tmp_path)
    with (
        patch("shutil.which", side_effect=lambda name: name),
        patch("subprocess.run") as run,
    ):
        dev["db"]()
    docker, migration = run.call_args_list
    assert docker.args[0][1:] == ["compose", "up", "-d", "postgresql"]
    assert migration.args[0][1:] == [
        "run",
        "--project",
        "backend",
        "python",
        "-m",
        "alembic",
        "-c",
        "backend/alembic.ini",
        "upgrade",
        "head",
    ]
    assert docker.kwargs == {"cwd": ROOT, "check": True}
    assert migration.kwargs == {"cwd": ROOT, "check": True}


def test_production_entry_rejects_invalid_tag_before_deploy() -> None:
    with (
        patch.object(sys, "argv", ["prod-deploy", "../main"]),
        patch.object(chatagents_launch, "_run") as run,
    ):
        try:
            chatagents_launch.prod_deploy()
        except SystemExit as exc:
            assert "用法" in str(exc)
        else:
            raise AssertionError("应拒绝无效 tag")
        run.assert_not_called()


def test_launcher_does_not_leak_root_venv_into_backend() -> None:
    with (
        patch("chatagents_launch.shutil.which", return_value="uv"),
        patch(
            "chatagents_launch.subprocess.run", return_value=subprocess.CompletedProcess([], 0)
        ) as run,
        patch.dict("chatagents_launch.os.environ", {"VIRTUAL_ENV": "root/.venv"}),
    ):
        chatagents_launch.dev_backend()
    assert "VIRTUAL_ENV" not in run.call_args.kwargs["env"]
