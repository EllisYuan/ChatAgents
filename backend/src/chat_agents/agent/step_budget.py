"""努力档位 → 步数预算的映射（CONTEXT.md「硬上限」「软预算」）。

硬上限与软预算是两套机制，按运行计不按会话累计。硬上限在这里由 ``AgentRunner``
强制生效；软预算是写进系统提示词的数字，注入动作归 #54（提示词与工具集版本化）
——这里先把两档数值一起钉死，供 #54 直接复用而不必重新拍数字。同一档位下软
预算低于硬上限，留出余量使越限成为异常而非常态。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from ..llm.effort import EffortTier


@dataclass(frozen=True, slots=True)
class StepBudget:
    soft: int
    hard_cap: int


STEP_BUDGETS: Final[dict[EffortTier, StepBudget]] = {
    "low": StepBudget(soft=3, hard_cap=4),
    "medium": StepBudget(soft=6, hard_cap=8),
    "high": StepBudget(soft=10, hard_cap=13),
    "xhigh": StepBudget(soft=16, hard_cap=20),
}
