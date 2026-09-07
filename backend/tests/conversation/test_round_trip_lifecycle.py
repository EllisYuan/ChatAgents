import asyncio
from uuid import uuid4

import pytest
from chat_agents.conversation.service import ConversationService


def test_round_trip_payload_scope_clears_registered_messages_on_failure() -> None:
    service = object.__new__(ConversationService)
    cleared: list[set[object]] = []

    async def clear(
        *, session_factory: object, session_id: object, message_ids: set[object]
    ) -> int:
        del session_factory, session_id
        cleared.append(message_ids)
        return len(message_ids)

    service.short_transaction_clear_round_trip_payload = clear
    message_id = uuid4()

    async def scenario() -> None:
        with pytest.raises(RuntimeError, match="断连"):
            async with service.round_trip_payload_scope(
                session_factory=object(), session_id=uuid4()
            ) as message_ids:
                message_ids.add(message_id)
                raise RuntimeError("断连")

    asyncio.run(scenario())

    assert cleared == [{message_id}]
