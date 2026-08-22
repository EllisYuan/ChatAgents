#!/usr/bin/env python3
"""运行 CI 评测批次；旧版与新版在同一次 CI 内分别执行。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "backend"))
sys.path.insert(0, str(_REPO_ROOT / "backend" / "src"))

from tests.evals.ci import RELEASE_RETENTION_WINDOWS, validate_ci_configuration


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run",
        choices=("old", "new", "both"),
        default="both",
        help="选择基线、新版，或按顺序运行两者",
    )
    parser.add_argument("--retention-window", type=int)
    return parser


def _validate_environment(retention_window: int | None) -> None:
    judge_variable = "EVAL_RELEASE_JUDGE_MODEL" if retention_window is not None else "EVAL_JUDGE_MODEL"
    if not os.environ.get(judge_variable):
        raise ValueError(f"{judge_variable} 未配置，不能产生可追溯的评测结果")
    try:
        cases_per_effort = int(os.environ.get("EVAL_CASES_PER_EFFORT", ""))
        total_cases = int(os.environ.get("EVAL_TOTAL_CASES", ""))
    except ValueError as exc:
        raise ValueError("EVAL_CASES_PER_EFFORT 与 EVAL_TOTAL_CASES 必须是整数") from exc
    validate_ci_configuration(
        cases_per_effort=cases_per_effort,
        total_cases=total_cases,
        retention_window=retention_window,
    )


def _pytest_command(run_name: str, retention_window: int | None) -> int:
    command = [sys.executable, "-m", "pytest", "-m", "eval", "backend/tests/evals"]
    if retention_window is not None:
        command.extend(["--eval-retention-window", str(retention_window)])
    environment = os.environ.copy()
    environment["EVAL_RUN"] = run_name
    result = subprocess.run(command, cwd=_REPO_ROOT, env=environment, check=False)
    return result.returncode


def _write_report(run_name: str, retention_window: int | None) -> None:
    report_dir = _REPO_ROOT / ".eval-reports"
    report_dir.mkdir(exist_ok=True)
    judge_variable = "EVAL_RELEASE_JUDGE_MODEL" if retention_window is not None else "EVAL_JUDGE_MODEL"
    judge_fingerprint = hashlib.sha256(os.environ[judge_variable].encode()).hexdigest()[:12]
    report = {
        "run": run_name,
        "judge_snapshot": f"sha256:{judge_fingerprint}",
        "cases_per_effort": int(os.environ["EVAL_CASES_PER_EFFORT"]),
        "case_count": int(os.environ["EVAL_TOTAL_CASES"]),
        "retention_window": retention_window,
        "status": "completed",
    }
    path = report_dir / f"{run_name}-{retention_window or 'pr'}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    args = _parser().parse_args()
    if args.retention_window is not None and args.retention_window not in RELEASE_RETENTION_WINDOWS:
        raise SystemExit(f"未知保留窗口: {args.retention_window}")
    _validate_environment(args.retention_window)
    runs = ("old", "new") if args.run == "both" else (args.run,)
    for run_name in runs:
        if _pytest_command(run_name, args.retention_window):
            return 1
        _write_report(run_name, args.retention_window)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
