"""原生 reasoning 显示摘要到跨度属性的纯投影（ADR-0017）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from ..agent.events import reasoning_message_id


@dataclass(slots=True)
class ReasoningSummary:
    """累积一次模型迭代的摘要，不把摘要写进模型消息。"""

    run_id: str
    iteration: int
    _parts: list[str] = field(default_factory=list)

    @property
    def message_id(self) -> UUID:
        """返回独立于助手消息的摘要消息标识。"""

        return reasoning_message_id(self.run_id, self.iteration)

    def append(self, text: str) -> None:
        """追加一个流式摘要片段；空片段不制造空摘要。"""

        if text:
            self._parts.append(text)

    @property
    def text(self) -> str:
        return "".join(self._parts)

    def attributes(self) -> dict[str, list[dict[str, str]]] | None:
        """返回 OpenInference ``message_content`` 快照，没有摘要时返回 ``None``。"""

        text = self.text
        if not text:
            return None
        return {"message_content": [{"type": "reasoning", "text": text}]}


def reasoning_attributes(text: str) -> dict[str, list[dict[str, str]]] | None:
    """把完整摘要投影成跨度属性；空摘要不落空数组。"""

    if not text:
        return None
    return {"message_content": [{"type": "reasoning", "text": text}]}
