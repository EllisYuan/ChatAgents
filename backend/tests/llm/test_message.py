"""ModelMessage 是协议无关的领域消息类型（ADR-0007 提到的 ModelMessage）。"""

import dataclasses

import pytest
from chat_agents.llm.message import (
    ModelMessage,
    OpaqueBlock,
    TextBlock,
    ToolCallBlock,
    ToolResultBlock,
)


def test_blocks_are_frozen_dataclasses() -> None:
    text = TextBlock(text="hello")
    assert dataclasses.is_dataclass(text)
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(text, "text", "mutated")  # noqa: B010


def test_message_preserves_block_order() -> None:
    blocks = (
        OpaqueBlock(protocol="anthropic_messages", data={"signature": "abc"}),
        TextBlock(text="the answer is 4"),
        ToolCallBlock(id="call_1", name="add", arguments={"a": 1, "b": 3}),
    )
    message = ModelMessage(role="assistant", content=blocks)
    assert message.content == blocks
    assert dataclasses.is_dataclass(message)
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(message, "role", "user")  # noqa: B010


def test_tool_result_block_defaults_to_not_an_error() -> None:
    block = ToolResultBlock(tool_call_id="call_1", content="42")
    assert block.is_error is False


def test_opaque_block_is_untranslated_payload() -> None:
    block = OpaqueBlock(protocol="openai_responses", data={"encrypted_content": "xyz"})
    assert block.protocol == "openai_responses"
    assert block.data == {"encrypted_content": "xyz"}
