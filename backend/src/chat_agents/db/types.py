"""数据模型专用的字面量类型（issue #48）。

``UsageState``/``EffortTier`` 已分别在 ``llm/events.py``、``llm/effort.py`` 定义，
这里直接复用，避免同一概念两处定义后悄悄漂移。本模块只补 DB 层特有、别处没有
定义过的取值集合。
"""

from typing import Literal

from ..llm.effort import EffortTier  # noqa: F401  (re-exported for db 模块内引用)
from ..llm.events import UsageState  # noqa: F401  (re-exported for db 模块内引用)

# app.message.role：ADR-0010 定了系统提示词不进消息表，所以这里比协议层的
# ``llm.message.Role``（含 "system"）窄一格——消息表只会出现这三种。
MessageRole = Literal["user", "assistant", "tool"]

# obs.span 的物化真列 role：CONTEXT.md「模型角色」，判据是输出去向（ADR-0012）。
ModelRole = Literal["main", "auxiliary"]

# obs.run.status：运行终态。aborted 对应 ADR-0008 定的客户端断连就地停。
RunStatus = Literal["running", "completed", "failed", "aborted"]

# obs.span.status：跨度是否记为失败（ADR-0006：外部失败仍要记错误跨度）。
SpanStatus = Literal["ok", "error"]
