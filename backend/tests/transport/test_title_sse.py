"""标题领域事件的 SSE 映射。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

from chat_agents.agent.events import (
    IterationStarted,
    RunCompleted,
    TitleGenerated,
    TitleGenerationStarted,
)
from chat_agents.llm.events import Usage
from chat_agents.llm.message import ModelMessage, TextBlock
from chat_agents.transport.sse import encode_sse


async def _events() -> AsyncIterator[object]:
    yield TitleGenerationStarted(run_id="run-title", model="aux")
    yield IterationStarted(run_id="run-title", iteration=1)
    yield TitleGenerated(
        run_id="run-title",
        session_id=UUID("00000000-0000-0000-0000-000000000001"),
        title="Python 入门",
        usage=Usage(state="complete", input_tokens=2, output_tokens=3, reasoning_tokens=None),
    )
    yield RunCompleted(
        run_id="run-title",
        iteration=1,
        message=ModelMessage(role="assistant", content=(TextBlock(text="答案"),)),
    )


def test_title_generated_is_a_custom_event_with_auxiliary_usage() -> None:
    async def collect() -> list[dict[str, object]]:
        return [
            json.loads(frame)
            async for frame in encode_sse(
                _events(),
                session_id=UUID("00000000-0000-0000-0000-000000000001"),
                run_id="run-title",
                model="main",
            )
        ]

    frames = asyncio.run(collect())
    title_index = next(
        i for i, frame in enumerate(frames) if frame.get("name") == "chatagents.title"
    )
    assert frames[title_index]["type"] == "CUSTOM"
    assert frames[title_index]["value"] == {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "title": "Python 入门",
    }
    usage = next(frame for frame in frames if frame.get("name") == "chatagents.usage")
    assert isinstance(usage["value"], dict)
    assert usage["value"]["role"] == "auxiliary"
    assert title_index < next(
        i for i, frame in enumerate(frames) if frame["type"] == "RUN_FINISHED"
    )
