"""全项目唯一的 token 估算器实现（ADR-0020）。

它的职责不是「数 token」，是「预测上游响应会数出多少输入 token」——这条措辞
决定了它的正确性判据是「与上游报告的用量接近」，不是「符合某个 tokenizer
规范」。`tools/web_reader` 的分节阈值判断与（未来的）会话保留窗口预算共用
这一处实现，两处用同一把尺，差别只在真值可得性。

零依赖，纯函数，谁都不认识——不认识数据库、不认识 `agent/`、不认识任何供应商。
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

# CJK 统一表意文字、假名、韩文音节的常见区段——这些字符按 1 字 ≈ 1 token 估算，
# 其余按 4 字符 ≈ 1 token 估算（拉丁文常见比例）。
_CJK_RANGES = (
    (0x4E00, 0x9FFF),
    (0x3400, 0x4DBF),
    (0xF900, 0xFAFF),
    (0x3040, 0x30FF),
    (0xAC00, 0xD7A3),
)


def _is_cjk(char: str) -> bool:
    code_point = ord(char)
    return any(lo <= code_point <= hi for lo, hi in _CJK_RANGES)


def count_tokens(text: str) -> int:
    """裸估算，未经校准。"""
    if not text:
        return 0
    cjk_count = sum(1 for char in text if _is_cjk(char))
    other_count = len(text) - cjk_count
    return cjk_count + math.ceil(other_count / 4)


def estimate_tokens(text: str, *, calibration: float = 1.0) -> int:
    """预测上游会数出多少 token：裸估算乘以调用方传入的校准系数。

    `calibration` 默认为 1.0，对应没有实测数据可用时的退化路径——ADR-0020
    规定 `PARTIAL`/`UNAVAILABLE` 用量态退化为全量估算。系数必须由调用方
    （工具执行上下文）传入，本函数不查询任何模型或数据库（ADR-0004 编排层
    是纯函数、ADR-0007 分层纪律）。
    """
    if calibration <= 0:
        raise ValueError("calibration must be positive")
    return math.ceil(count_tokens(text) * calibration)


@dataclass(frozen=True, slots=True)
class UsageSample:
    """一次模型调用的实测输入 token 数与本估算器对同一输入给出的裸估算。"""

    model: str
    estimated_tokens: int
    actual_tokens: int


def compute_calibration_factors(samples: Iterable[UsageSample]) -> dict[str, float]:
    """按模型分别计算「实测 ÷ 估算」的平均偏差系数——纯查询层工作（ADR-0020）。

    输入是观测侧已经收集好的样本；本函数不认识样本从哪张表来、不发起任何
    查询，只做分组平均，因此可以在观测层落地之前先行实现与测试。估算为 0
    的样本无法定义比值，跳过。没有样本的模型不出现在返回值里——调用方应对
    未出现的模型使用 `calibration=1.0` 的退化路径。
    """
    ratios_by_model: dict[str, list[float]] = {}
    for sample in samples:
        if sample.estimated_tokens <= 0:
            continue
        ratios_by_model.setdefault(sample.model, []).append(
            sample.actual_tokens / sample.estimated_tokens
        )
    return {model: sum(ratios) / len(ratios) for model, ratios in ratios_by_model.items()}
