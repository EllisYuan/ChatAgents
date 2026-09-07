"""站点展示面的评测产出读取（issue #66）。

读两类文件，均由评测产出流程写入本目录，本模块不参与评测执行本身：

- ``site-summary.json``：一次批量评测的完整产出，形状与
  ``backend/tests/evals/evaluator.py`` 里 ``EvalReport.to_dict()`` 一致，
  外加顶层 ``generated_at``。这里只取三个确定性指标：``citation_faithfulness``
  ``tool_trigger_rate`` ``trajectory_efficiency``。
- ``compression-cost-curve.json``：release 档位保留窗口网格扫描产出的
  「压缩强度 × 引用忠实度 × 成本」曲线，键是保留窗口。

任一文件缺失、损坏，或网格没有覆盖全部五个保留窗口，对应的数字就是
``None``——这是优雅缺省，不是错误。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

_SUMMARY_FILENAME = "site-summary.json"
_CURVE_FILENAME = "compression-cost-curve.json"
_DISPLAY_METRICS = ("citation_faithfulness", "tool_trigger_rate", "trajectory_efficiency")

# 与 ``backend/tests/evals/ci.py`` 的 ``RELEASE_RETENTION_WINDOWS`` 同源，但那
# 是测试树里的评测执行代码，站点展示面（产品代码）不应反向依赖它，因此在此
# 独立声明。
_REQUIRED_RETENTION_WINDOWS = frozenset({1, 2, 3, 5, 8})


@dataclass(frozen=True, slots=True)
class EvalMetricSnapshot:
    """单个确定性指标的最新一次批量评测取值。"""

    score: float
    sample_size: int
    generated_at: datetime


@dataclass(frozen=True, slots=True)
class CompressionCostPoint:
    """网格扫描中某一个保留窗口的一组取值。"""

    retention_window: int
    citation_faithfulness: float
    cost_tokens: float


@dataclass(frozen=True, slots=True)
class CompressionCostCurve:
    """按保留窗口升序排列的完整曲线；缺一个窗口就不构成曲线。"""

    generated_at: datetime
    points: tuple[CompressionCostPoint, ...]


@dataclass(frozen=True, slots=True)
class EvalSiteSummary:
    """站点展示面正好四个数字；任一项没有落地数据就是 ``None``。"""

    citation_faithfulness: EvalMetricSnapshot | None
    tool_trigger_rate: EvalMetricSnapshot | None
    trajectory_efficiency: EvalMetricSnapshot | None
    compression_cost_curve: CompressionCostCurve | None


class EvalSummaryStore:
    """从磁盘上的评测产出目录读取站点展示面数据。"""

    def __init__(self, reports_dir: Path) -> None:
        self._reports_dir = reports_dir

    def read(self) -> EvalSiteSummary:
        metrics = self._read_summary_metrics()
        return EvalSiteSummary(
            citation_faithfulness=metrics.get("citation_faithfulness"),
            tool_trigger_rate=metrics.get("tool_trigger_rate"),
            trajectory_efficiency=metrics.get("trajectory_efficiency"),
            compression_cost_curve=self._read_curve(),
        )

    def _read_summary_metrics(self) -> dict[str, EvalMetricSnapshot]:
        raw = self._load_json(_SUMMARY_FILENAME)
        if not isinstance(raw, dict):
            return {}
        try:
            generated_at = datetime.fromisoformat(str(raw["generated_at"]))
            aggregate_scores = raw["aggregate_scores"]
            if not isinstance(aggregate_scores, dict):
                return {}
            case_results = raw.get("case_results", [])
            sample_size = len(case_results) if isinstance(case_results, list) else 0
        except (KeyError, TypeError, ValueError):
            return {}

        metrics: dict[str, EvalMetricSnapshot] = {}
        for name in _DISPLAY_METRICS:
            if name not in aggregate_scores:
                continue
            try:
                metrics[name] = EvalMetricSnapshot(
                    score=float(aggregate_scores[name]),
                    sample_size=sample_size,
                    generated_at=generated_at,
                )
            except (TypeError, ValueError):
                continue
        return metrics

    def _read_curve(self) -> CompressionCostCurve | None:
        raw = self._load_json(_CURVE_FILENAME)
        if not isinstance(raw, dict):
            return None
        try:
            generated_at = datetime.fromisoformat(str(raw["generated_at"]))
            raw_points = raw["points"]
            if not isinstance(raw_points, list):
                return None
            points = tuple(
                CompressionCostPoint(
                    retention_window=int(point["retention_window"]),
                    citation_faithfulness=float(point["citation_faithfulness"]),
                    cost_tokens=float(point["cost_tokens"]),
                )
                for point in raw_points
            )
        except (KeyError, TypeError, ValueError):
            return None

        windows = {point.retention_window for point in points}
        if windows != _REQUIRED_RETENTION_WINDOWS:
            return None
        return CompressionCostCurve(
            generated_at=generated_at,
            points=tuple(sorted(points, key=lambda point: point.retention_window)),
        )

    def _load_json(self, filename: str) -> Any:
        path = self._reports_dir / filename
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None


__all__ = [
    "CompressionCostCurve",
    "CompressionCostPoint",
    "EvalMetricSnapshot",
    "EvalSiteSummary",
    "EvalSummaryStore",
]
