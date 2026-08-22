from types import SimpleNamespace
from uuid import uuid4

from chat_agents.conversation.models import decode_message, encode_content
from chat_agents.conversation.service import project_messages
from chat_agents.llm.message import (
    ModelMessage,
    OpaqueBlock,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)


def _row(seq: int, role: str, content: list[dict], payload: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        session_id=uuid4(),
        seq=seq,
        role=role,
        content=content,
        round_trip_payload=payload,
    )


def test_encode_and_decode_preserve_protocol_neutral_blocks() -> None:
    message = ModelMessage(
        role="assistant",
        content=(
            OpaqueBlock(protocol="anthropic_messages", data={"type": "thinking", "signature": "s"}),
            TextBlock(text="answer"),
            ToolCallBlock(id="call-1", name="lookup", arguments={"q": "x"}),
        ),
    )

    content, opaque = encode_content(message)
    assert content == [
        {"type": "text", "text": "answer"},
        {"type": "tool_call", "id": "call-1", "name": "lookup", "arguments": {"q": "x"}},
    ]
    assert opaque == [
        {"protocol": "anthropic_messages", "data": {"type": "thinking", "signature": "s"}}
    ]
    restored = decode_message(
        role="assistant", content=content, round_trip_payload=opaque, include_round_trip=True
    )
    assert restored.content == message.content


def test_encode_and_decode_preserve_interleaved_opaque_block_order() -> None:
    message = ModelMessage(
        role="assistant",
        content=(
            TextBlock(text="before"),
            OpaqueBlock(protocol="openai_responses", data={"type": "reasoning"}),
            ToolCallBlock(id="call-1", name="lookup", arguments={}),
        ),
    )

    content, opaque = encode_content(message)
    restored = decode_message(
        role="assistant", content=content, round_trip_payload=opaque, include_round_trip=True
    )

    assert restored.content == message.content
    assert opaque == [
        {
            "protocol": "openai_responses",
            "data": {"type": "reasoning"},
            "content_index": 1,
        }
    ]


def test_projection_excludes_system_and_repairs_orphan_tool_call_without_instruction() -> None:
    rows = [
        _row(1, "user", [{"type": "text", "text": "hello"}]),
        _row(
            2,
            "assistant",
            [{"type": "tool_call", "id": "call-1", "name": "lookup", "arguments": {}}],
        ),
    ]

    projected = project_messages(rows)

    assert [message.role for message in projected] == ["user", "assistant", "tool"]
    result = projected[-1].content[0]
    assert result == ToolResultBlock(
        tool_call_id="call-1",
        content="Tool call ended before a result was recorded.",
        is_error=True,
    )
    assert "retry" not in result.content.lower()
    assert "重新调用" not in result.content
    assert "请" not in result.content


def test_projection_repairs_only_missing_results_and_keeps_existing_result() -> None:
    rows = [
        _row(
            1,
            "assistant",
            [
                {"type": "tool_call", "id": "call-1", "name": "one", "arguments": {}},
                {"type": "tool_call", "id": "call-2", "name": "two", "arguments": {}},
            ],
        ),
        _row(
            2,
            "tool",
            [{"type": "tool_result", "tool_call_id": "call-1", "content": "ok", "is_error": False}],
        ),
    ]

    projected = project_messages(rows)
    assert len(projected) == 2
    results = projected[1].content
    assert results[0] == ToolResultBlock(tool_call_id="call-1", content="ok", is_error=False)
    assert results[1] == ToolResultBlock(
        tool_call_id="call-2",
        content="Tool call ended before a result was recorded.",
        is_error=True,
    )


def test_projection_can_limit_opaque_payload_to_current_run() -> None:
    rows = [
        _row(
            1,
            "assistant",
            [{"type": "text", "text": "old"}],
            {"protocol": "anthropic_messages", "data": {"type": "thinking", "signature": "old"}},
        ),
        _row(
            2,
            "assistant",
            [{"type": "text", "text": "new"}],
            {"protocol": "anthropic_messages", "data": {"type": "thinking", "signature": "new"}},
        ),
    ]

    historical = project_messages(rows)
    assert len(historical[0].content) == 1
    assert len(historical[1].content) == 1

    projected = project_messages(rows, round_trip_from_seq=2)
    assert len(projected[0].content) == 1
    assert len(projected[1].content) == 2


def test_projection_masks_old_observations_without_breaking_tool_pairs() -> None:
    rows = [
        _row(
            1,
            "assistant",
            [
                {
                    "type": "tool_call",
                    "id": "call-1",
                    "name": "web_search",
                    "arguments": {"query": "one"},
                }
            ],
        ),
        _row(
            2,
            "tool",
            [
                {
                    "type": "tool_result",
                    "tool_call_id": "call-1",
                    "content": "old title https://old.example",
                }
            ],
        ),
        _row(
            3,
            "assistant",
            [
                {
                    "type": "tool_call",
                    "id": "call-2",
                    "name": "web_search",
                    "arguments": {"query": "two"},
                }
            ],
        ),
        _row(
            4,
            "tool",
            [
                {
                    "type": "tool_result",
                    "tool_call_id": "call-2",
                    "content": "new title https://new.example",
                }
            ],
        ),
        _row(
            5,
            "assistant",
            [
                {
                    "type": "tool_call",
                    "id": "call-3",
                    "name": "web_search",
                    "arguments": {"query": "three"},
                }
            ],
        ),
        _row(
            6,
            "tool",
            [
                {
                    "type": "tool_result",
                    "tool_call_id": "call-3",
                    "content": "latest title https://latest.example",
                }
            ],
        ),
    ]

    projected = project_messages(rows, retention_window=2)

    results = [
        block
        for message in projected
        if message.role == "tool"
        for block in message.content
        if isinstance(block, ToolResultBlock)
    ]
    assert len(results) == 3
    assert "old title" not in results[0].content
    assert "old.example" in results[0].content
    assert results[1].content == "new title https://new.example"
    assert results[2].content == "latest title https://latest.example"
    assert [result.tool_call_id for result in results] == ["call-1", "call-2", "call-3"]


def test_observation_keep_is_global_and_does_not_depend_on_effort() -> None:
    from chat_agents.conversation.service import OBSERVATION_KEEP

    assert OBSERVATION_KEEP > 0
    assert OBSERVATION_KEEP == 2
