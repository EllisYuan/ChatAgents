from uuid import UUID

from chat_agents.agent.events import ReasoningDelta, reasoning_message_id
from chat_agents.observability import ReasoningSummary, reasoning_attributes


def test_reasoning_message_id_is_stable_and_separate_from_assistant_id() -> None:
    first = reasoning_message_id("00000000-0000-0000-0000-000000000001", 2)
    second = reasoning_message_id("00000000-0000-0000-0000-000000000001", 2)
    other_iteration = reasoning_message_id("00000000-0000-0000-0000-000000000001", 3)

    assert isinstance(first, UUID)
    assert first == second
    assert first != other_iteration
    assert ReasoningDelta(run_id=str(UUID(int=1)), iteration=2, text="x").message_id == first


def test_reasoning_summary_is_an_observation_projection_only() -> None:
    summary = ReasoningSummary(run_id="run-1", iteration=1)
    assert summary.attributes() is None

    summary.append("先看")
    summary.append("一下")

    assert summary.text == "先看一下"
    assert summary.attributes() == {"message_content": [{"type": "reasoning", "text": "先看一下"}]}
    assert summary.message_id == reasoning_message_id("run-1", 1)


def test_empty_reasoning_is_not_serialized_as_an_attribute() -> None:
    assert reasoning_attributes("") is None
