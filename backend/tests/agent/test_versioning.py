from __future__ import annotations

from datetime import UTC, datetime

from chat_agents.agent.versioning import (
    SYSTEM_PROMPT_NAME,
    TITLE_PROMPT_NAME,
    build_prompt_versions,
    build_tool_schema_versions,
    content_hash,
    render_system_prompt,
    version_id,
)
from chat_agents.llm.effort import EFFORT_TIERS


def test_system_prompt_is_one_template_with_only_supported_variables() -> None:
    [version] = [item for item in build_prompt_versions() if item.name == SYSTEM_PROMPT_NAME]

    assert version.variables == ["date", "step_budget"]
    assert "Thought:" not in version.content
    assert "Action:" not in version.content
    assert "Tavily" not in version.content
    assert "中国和亚洲" not in version.content
    assert "优先返回中文" not in version.content
    assert "跟随用户消息使用的语言" in version.content
    assert render_system_prompt(date="2026年08月18日", step_budget=6).count("2026年08月18日") == 1
    assert "6" in render_system_prompt(date="2026年08月18日", step_budget=6)


def test_title_prompt_is_stored_in_the_same_prompt_version_family() -> None:
    names = {item.name for item in build_prompt_versions()}

    assert {SYSTEM_PROMPT_NAME, TITLE_PROMPT_NAME} <= names


def test_version_id_uses_content_hash_and_creation_time() -> None:
    created_at = datetime(2026, 8, 18, 12, 34, 56, 123456, tzinfo=UTC)
    digest = content_hash("same content")

    assert digest == "a636bd7cd420"
    assert version_id("system", created_at, "same content") == (
        "system@20260818T123456.123456Z-a636bd7cd420"
    )


def test_tool_schema_versions_have_one_canonical_snapshot_per_effort() -> None:
    versions = build_tool_schema_versions()

    assert [item.effort_tier for item in versions] == list(EFFORT_TIERS)
    assert all(item.content.startswith("[") for item in versions)
    assert all(item.content_hash == content_hash(item.content) for item in versions)
    assert all(item.version_id.endswith(f"-{item.content_hash}") for item in versions)
