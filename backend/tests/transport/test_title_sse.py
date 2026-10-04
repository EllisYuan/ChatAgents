"""标题不再进入主运行的 SSE 编码（issue #93）。

旧协议（``chatagents.title`` custom 事件、标题 auxiliary 用量与兄弟跨度）已从
``encode_sse`` 移除；这里断言编码器不产出任何标题相关帧。历史标题协议不存在，
旧事件测试迁移为「无标题帧」的行为断言。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

from chat_agents.agent.events import (
    IterationCompleted,
    IterationStarted,
    RunCompleted,
)
from chat_agents.llm.events import Usage
from chat_agents.llm.message import ModelMessage, TextBlock
from chat_agents.transport.sse import encode_sse

SESSION_ID = UUID("00000000-0000-0000-0000-000000000001")


async def _events() -> AsyncIterator[object]:
    yield IterationStarted(run_id="run-title", iteration=1, model="test-model")
    message = ModelMessage(role="assistant", content=(TextBlock(text="答案"),))
    yield IterationCompleted(
        run_id="run-title",
        iteration=1,
        message=message,
        usage=Usage(state="complete", input_tokens=2, output_tokens=3, reasoning_tokens=None),
        stop_reason="end_turn",
    )
    yield RunCompleted(run_id="run-title", iteration=1, message=message)


def test_main_run_sse_has_no_title_frames_or_auxiliary_usage() -> None:
    async def collect() -> list[dict[str, object]]:
        return [
            json.loads(frame)
            async for frame in encode_sse(_events(), session_id=SESSION_ID, run_id="run-title")
        ]

    frames = asyncio.run(collect())

    assert not any(frame.get("name") == "chatagents.title" for frame in frames)
    usage_frames = [frame for frame in frames if frame.get("name") == "chatagents.usage"]
    assert usage_frames, "主运行仍应产出 main 用量帧"
    for frame in usage_frames:
        value = frame["value"]
        assert isinstance(value, dict)
        assert value["role"] == "main"
        assert value["model"] == "test-model"
    assert frames[-1]["type"] == "RUN_FINISHED"
