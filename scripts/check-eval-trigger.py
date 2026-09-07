#!/usr/bin/env python3
"""比较模型输入版本 hash，供评测 CI 判断是否需要运行。"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_ROOT = Path(os.environ.get("CHATAGENTS_SOURCE_ROOT", _REPO_ROOT))
sys.path.insert(0, str(_SOURCE_ROOT / "backend"))
sys.path.insert(0, str(_SOURCE_ROOT / "backend" / "src"))
# CI helper 本身来自当前 checkout；base revision 不一定已包含它的测试模块。
sys.path.insert(0, str(_REPO_ROOT / "backend"))

# ``chat_agents`` 与 ``tests.evals.ci`` 都解析自 ``_SOURCE_ROOT``——``--seed``
# 时那是 base revision。因此下面的 import 全部惰性放进函数体：引导期的 base
# 还没有模型输入版本机制，在模块顶层 import 会让 ``--seed`` 直接崩在
# ModuleNotFoundError 上。
if TYPE_CHECKING:
    from tests.evals.ci import ModelInputHashes


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--seed",
        action="store_true",
        help="将当前 checkout 的模型输入版本写入数据库，作为本次 CI 的临时基线",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="比较当前 checkout 与数据库最新版本行的 content_hash",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="将 GitHub Actions name=value 输出追加到指定文件",
    )
    return parser


def _is_missing_source_module(error: ModuleNotFoundError) -> bool:
    """区分「base revision 没有这个模块」与「环境真的坏了」。"""

    return (error.name or "").startswith("chat_agents")


async def _seed() -> None:
    from chat_agents.agent.versioning import sync_model_input_versions
    from chat_agents.database import session_factory

    async with session_factory() as session:
        async with session.begin():
            await sync_model_input_versions(session)


async def _check() -> tuple[ModelInputHashes, tuple[str, ...]]:
    from chat_agents.database import session_factory
    from tests.evals.ci import (
        current_model_input_hashes,
        latest_model_input_hashes,
        model_input_changes,
    )

    current = current_model_input_hashes()
    async with session_factory() as session:
        baseline = await latest_model_input_hashes(session)
    changes = model_input_changes(current, baseline)
    return baseline, tuple(change.label for change in changes)


def _write_outputs(
    path: Path | None,
    *,
    changed: bool,
    labels: tuple[str, ...],
    baseline_missing: bool,
) -> None:
    values = {
        "eval_changed": str(changed).lower(),
        "eval_changed_inputs": ",".join(labels),
        "eval_baseline_missing": str(baseline_missing).lower(),
    }
    if path is None:
        for name, value in values.items():
            print(f"{name}={value}")
        return
    with path.open("a", encoding="utf-8") as output:
        _append_outputs(output, values)


def _append_outputs(output: TextIO, values: dict[str, str]) -> None:
    for name, value in values.items():
        output.write(f"{name}={value}\n")


def main() -> int:
    args = _parser().parse_args()
    if args.seed:
        try:
            asyncio.run(_seed())
        except ModuleNotFoundError as error:
            if not _is_missing_source_module(error):
                raise
            # 引导期：base revision 还没有模型输入版本机制，没有基线可播种。
            # 留空即可——``--check`` 会把空基线报成 eval_baseline_missing，
            # 并把全部当前输入判为变更，这正是无基线时该有的保守结论。
            print(
                f"base revision 缺少 {error.name}，跳过基线播种",
                file=sys.stderr,
            )
        return 0

    baseline, labels = asyncio.run(_check())
    _write_outputs(
        args.output,
        changed=bool(labels),
        labels=labels,
        baseline_missing=not baseline.prompts and not baseline.tool_schemas,
    )
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    raise SystemExit(main())
