from __future__ import annotations

import asyncio

import pytest
from chat_agents.agent.versioning import (
    build_prompt_versions,
    build_tool_schema_versions,
    sync_model_input_versions,
)
from chat_agents.db.app import PromptVersion, ToolSchemaVersion
from sqlalchemy import func, select
from tests.db_helpers import migrated_engine, session_factory_for


@pytest.mark.db
def test_startup_sync_is_hash_stable_and_idempotent() -> None:
    async def scenario() -> None:
        async with migrated_engine("chat_agents_prompt_versions") as engine:
            factory = session_factory_for(engine)
            async with factory() as session, session.begin():
                first_prompts, first_tools = await sync_model_input_versions(session)
                first_counts = (
                    await session.scalar(select(func.count()).select_from(PromptVersion)),
                    await session.scalar(select(func.count()).select_from(ToolSchemaVersion)),
                )

            async with factory() as session, session.begin():
                second_prompts, second_tools = await sync_model_input_versions(session)
                second_counts = (
                    await session.scalar(select(func.count()).select_from(PromptVersion)),
                    await session.scalar(select(func.count()).select_from(ToolSchemaVersion)),
                )
                stored_prompts = list((await session.scalars(select(PromptVersion))).all())
                stored_tools = list((await session.scalars(select(ToolSchemaVersion))).all())

            assert [row.version_id for row in first_prompts] == [
                row.version_id for row in second_prompts
            ]
            assert [row.version_id for row in first_tools] == [
                row.version_id for row in second_tools
            ]
            assert first_counts == second_counts == (2, 4)
            assert {row.content_hash for row in stored_prompts} == {
                row.content_hash for row in build_prompt_versions()
            }
            assert {row.content_hash for row in stored_tools} == {
                row.content_hash for row in build_tool_schema_versions()
            }

    asyncio.run(scenario())
