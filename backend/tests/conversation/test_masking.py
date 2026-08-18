from types import SimpleNamespace
from uuid import uuid4

from chat_agents.conversation.service import (
    RETENTION_WINDOW,
    project_messages,
    project_messages_with_metadata,
)
from chat_agents.llm.message import ToolResultBlock


def _row(seq: int, role: str, content: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        session_id=uuid4(),
        seq=seq,
        role=role,
        content=content,
        round_trip_payload=None,
    )


def _tool_pair(
    seq: int, call_id: str, name: str, arguments: dict, result: str
) -> list[SimpleNamespace]:
    return [
        _row(
            seq,
            "assistant",
            [{"type": "tool_call", "id": call_id, "name": name, "arguments": arguments}],
        ),
        _row(
            seq + 1,
            "tool",
            [{"type": "tool_result", "tool_call_id": call_id, "content": result}],
        ),
    ]


def test_masking_keeps_only_the_latest_tool_observation_pairs() -> None:
    rows: list[SimpleNamespace] = [_row(0, "user", [{"type": "text", "text": "查资料"}])]
    for index in range(3):
        rows.extend(
            _tool_pair(
                index * 2 + 1,
                f"call-{index}",
                "web_reader",
                {"url": f"https://{index}.example"},
                f"正文 {index}",
            )
        )

    projected = project_messages(rows, retention_window=2)

    results = [message.content[0] for message in projected if message.role == "tool"]
    assert len(results) == 3
    assert results[0] != ToolResultBlock(tool_call_id="call-0", content="正文 0")
    assert results[1] == ToolResultBlock(tool_call_id="call-1", content="正文 1")
    assert results[2] == ToolResultBlock(tool_call_id="call-2", content="正文 2")
    assert "web_reader" in results[0].content
    assert "https://0.example" in results[0].content
    assert "正文 0" not in results[0].content


def test_masking_window_is_global_and_has_one_default_value() -> None:
    assert RETENTION_WINDOW == 2
    rows: list[SimpleNamespace] = [_row(0, "user", [{"type": "text", "text": "查资料"}])]
    for index in range(RETENTION_WINDOW + 1):
        rows.extend(
            _tool_pair(
                index * 2 + 1, f"call-{index}", "web_search", {"query": str(index)}, f"结果 {index}"
            )
        )

    projected = project_messages(rows)

    results = [message.content[0] for message in projected if message.role == "tool"]
    assert len(results) == RETENTION_WINDOW + 1
    assert "结果 0" not in results[0].content
    assert results[-1] == ToolResultBlock(
        tool_call_id=f"call-{RETENTION_WINDOW}", content=f"结果 {RETENTION_WINDOW}"
    )


def test_masking_metadata_contains_call_arguments_and_sources() -> None:
    rows = [
        _row(0, "user", [{"type": "text", "text": "搜索"}]),
        *_tool_pair(
            1,
            "call-1",
            "web_search",
            {"query": "context editing"},
            "搜索结果：\n1. Context Editing\n   https://example.com/context\n   正文",
        ),
    ]

    projection = project_messages_with_metadata(rows, retention_window=0)

    assert len(projection.masked_observations) == 1
    observation = projection.masked_observations[0]
    assert observation.tool_name == "web_search"
    assert observation.arguments == {"query": "context editing"}
    assert {source.url for source in observation.sources} == {"https://example.com/context"}
    assert observation.sources[0].title == "Context Editing"
    assert projection.attributes["masked_observation_ids"] == ["call-1"]


def test_pruned_ranges_remove_whole_runs_without_creating_orphans() -> None:
    rows = [
        _row(0, "user", [{"type": "text", "text": "第一问"}]),
        *_tool_pair(1, "call-1", "web_reader", {"url": "https://one.example"}, "one"),
        _row(3, "user", [{"type": "text", "text": "第二问"}]),
        *_tool_pair(4, "call-2", "web_reader", {"url": "https://two.example"}, "two"),
    ]

    projected = project_messages(rows, skipped_seq_ranges=((0, 2),))

    assert [message.role for message in projected] == ["user", "assistant", "tool"]
    assert projected[0].content[0].text == "第二问"
    assert projected[-1].content[0].tool_call_id == "call-2"
