"""旧入口的兼容包装；实际模板由 ``chat_agents.agent.versioning`` 统一维护。"""

from __future__ import annotations

import datetime

from chat_agents.agent.versioning import SYSTEM_PROMPT_TEMPLATE, render_system_prompt


def get_current_date() -> str:
    """返回当前日期，供旧入口兼容使用。"""
    today = datetime.datetime.now()
    weekday = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
    return f"{today:%Y年%m月%d日} {weekday[today.weekday()]}（{today:%A, %B %d, %Y}）"


def get_simple_prompt() -> str:
    """兼容旧调用方，使用统一模板和 low 档软预算。"""
    return render_system_prompt(date=get_current_date(), step_budget=3)


def get_reasoning_prompt() -> str:
    """兼容旧调用方，使用统一模板和 high 档软预算。"""
    return render_system_prompt(date=get_current_date(), step_budget=10)


__all__ = [
    "SYSTEM_PROMPT_TEMPLATE",
    "get_current_date",
    "get_reasoning_prompt",
    "get_simple_prompt",
]
