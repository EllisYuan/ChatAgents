#!/usr/bin/env python3
"""比较模型输入版本 hash，供评测 CI 判断是否需要运行。"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import TextIO

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SOURCE_ROOT = Path(os.environ.get("CHATAGENTS_SOURCE_ROOT", _REPO_ROOT))
sys.path.insert(0, str(_SOURCE_ROOT / "backend"))
sys.path.insert(0, str(_SOURCE_ROOT / "backend" / "src"))
# CI helper 本身来自当前 checkout；base revision 不一定已包含它的测试模块。
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from chat_agents.agent.versioning import sync_model_input_versions
from chat_agents.database import session_factory
from tests.evals.ci import (
    ModelInputHashes,
    current_model_input_hashes,
    latest_model_input_hashes,
    model_input_changes,
)


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


async def _seed() -> None:
    async with session_factory() as session:
        async with session.begin():
            await sync_model_input_versions(session)


async def _check() -> tuple[ModelInputHashes, tuple[str, ...]]:
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
        asyncio.run(_seed())
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
