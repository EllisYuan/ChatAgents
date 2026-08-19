"""站点评测展示面的响应契约（issue #66）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from .store import EvalMetricSnapshot, EvalSiteSummary


class EvalMetricView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: float
    sample_size: int
    generated_at: datetime


class CompressionCostCurvePointView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retention_window: int
    citation_faithfulness: float
    cost_tokens: float


class CompressionCostCurveView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    points: list[CompressionCostCurvePointView]


class EvalSummaryView(BaseModel):
    """站点展示面正好四个数字（ADR-0028）；未落地的一项是 ``None``，不是 0。"""

    model_config = ConfigDict(extra="forbid")

    citation_faithfulness: EvalMetricView | None
    tool_trigger_rate: EvalMetricView | None
    trajectory_efficiency: EvalMetricView | None
    compression_cost_curve: CompressionCostCurveView | None


def _metric_view(snapshot: EvalMetricSnapshot | None) -> EvalMetricView | None:
    if snapshot is None:
        return None
    return EvalMetricView(
        score=snapshot.score,
        sample_size=snapshot.sample_size,
        generated_at=snapshot.generated_at,
    )


def eval_summary_view(summary: EvalSiteSummary) -> EvalSummaryView:
    curve_view = None
    if summary.compression_cost_curve is not None:
        curve_view = CompressionCostCurveView(
            generated_at=summary.compression_cost_curve.generated_at,
            points=[
                CompressionCostCurvePointView(
                    retention_window=point.retention_window,
                    citation_faithfulness=point.citation_faithfulness,
                    cost_tokens=point.cost_tokens,
                )
                for point in summary.compression_cost_curve.points
            ],
        )

    return EvalSummaryView(
        citation_faithfulness=_metric_view(summary.citation_faithfulness),
        tool_trigger_rate=_metric_view(summary.tool_trigger_rate),
        trajectory_efficiency=_metric_view(summary.trajectory_efficiency),
        compression_cost_curve=curve_view,
    )


__all__ = [
    "CompressionCostCurvePointView",
    "CompressionCostCurveView",
    "EvalMetricView",
    "EvalSummaryView",
    "eval_summary_view",
]
