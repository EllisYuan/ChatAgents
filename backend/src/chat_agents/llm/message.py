"""协议无关的领域消息类型（ADR-0007 提到的 ``ModelMessage``）。

三协议各自的请求/响应形状在适配器内转换；这里只有一份不偏向任何协议的表示，
供 ``agent/`` 与未来的消息表共用（ADR-0001：消息表存完整模型视角序列）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .protocol import Protocol

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class TextBlock:
    text: str


@dataclass(frozen=True, slots=True)
class ToolCallBlock:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResultBlock:
    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True, slots=True)
class OpaqueBlock:
    """原生推理往返载荷——按协议原样存放的不透明附件（ADR-0017）。

    不解析、不翻译，原样进原样出。``protocol`` 标记这份数据是哪个协议的原生形状，
    因为它只在产出它的那个协议下有意义，不可跨协议复用。
    """

    protocol: Protocol
    data: dict[str, Any]


ContentBlock = TextBlock | ToolCallBlock | ToolResultBlock | OpaqueBlock


@dataclass(frozen=True, slots=True)
class ModelMessage:
    role: Role
    content: tuple[ContentBlock, ...] = field(default_factory=tuple)
