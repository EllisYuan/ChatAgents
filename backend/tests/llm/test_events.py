"""ModelEvent——一次模型调用内部事件（ADR-0008）。用量三态缺失不得记 0。"""

import dataclasses

import pytest
from chat_agents.llm.events import (
    ModelCallCompleted,
    ReasoningDelta,
    TextDelta,
    ToolCallArgsDelta,
    ToolCallCompleted,
    ToolCallStarted,
    Usage,
)
from chat_agents.llm.message import ModelMessage, TextBlock


def test_usage_states_never_coerce_missing_to_zero() -> None:
    complete = Usage(state="complete", input_tokens=100, output_tokens=50, reasoning_tokens=10)
    partial = Usage(state="partial", input_tokens=100, output_tokens=None, reasoning_tokens=None)
    unavailable = Usage(
        state="unavailable", input_tokens=None, output_tokens=None, reasoning_tokens=None
    )

    assert complete.state == "complete"
    assert partial.output_tokens is None
    assert partial.output_tokens != 0
    assert unavailable.input_tokens is None


def test_usage_fields_are_optional_ints() -> None:
    fields = {f.name: f.type for f in dataclasses.fields(Usage)}
    assert fields["input_tokens"] == "int | None"
    assert fields["output_tokens"] == "int | None"
    assert fields["reasoning_tokens"] == "int | None"


def test_model_call_completed_carries_message_usage_and_stop_reason() -> None:
    message = ModelMessage(role="assistant", content=(TextBlock(text="hi"),))
    usage = Usage(state="complete", input_tokens=10, output_tokens=5, reasoning_tokens=None)
    event = ModelCallCompleted(message=message, usage=usage, stop_reason="end_turn")
    assert event.message is message
    assert event.usage is usage
    assert event.stop_reason == "end_turn"


def test_event_dataclasses_are_frozen() -> None:
    cases: list[tuple[object, str]] = [
        (TextDelta(text="a"), "text"),
        (ReasoningDelta(text="b"), "text"),
        (ToolCallStarted(id="1", name="web_search"), "id"),
        (ToolCallArgsDelta(id="1", args_delta='{"q":'), "id"),
        (ToolCallCompleted(id="1"), "id"),
    ]
    for instance, field_name in cases:
        assert dataclasses.is_dataclass(instance)
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(instance, field_name, "mutated")
