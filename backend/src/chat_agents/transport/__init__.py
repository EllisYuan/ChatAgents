"""领域事件到线格式（AG-UI over SSE）的转换（issue #52，ADR-0009）。"""

from .sse import encode_sse

__all__ = ["encode_sse"]
