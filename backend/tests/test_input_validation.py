"""Issue #64 输入校验的纯边界测试。"""

from uuid import uuid4

import pytest
from chat_agents.api_models import ModelRefreshRequest
from chat_agents.conversation.models import RenameSessionRequest, UserMessageRequest
from chat_agents.llm.override import ModelOverride
from chat_agents.tools.web_reader.orchestration import parse_section_indices
from chat_agents.validation import MAX_MESSAGE_LENGTH, MAX_TITLE_LENGTH
from pydantic import ValidationError


def test_message_and_title_reject_blank_and_overlong_values() -> None:
    with pytest.raises(ValidationError):
        UserMessageRequest(id=uuid4(), content=" " * 2)
    with pytest.raises(ValidationError):
        UserMessageRequest(id=uuid4(), content="x" * (MAX_MESSAGE_LENGTH + 1))
    with pytest.raises(ValidationError):
        RenameSessionRequest(title=" " * 2)
    with pytest.raises(ValidationError):
        RenameSessionRequest(title="x" * (MAX_TITLE_LENGTH + 1))


def test_model_refresh_requires_a_complete_custom_endpoint() -> None:
    with pytest.raises(ValidationError):
        ModelRefreshRequest(base_url="https://example.com")
    with pytest.raises(ValidationError):
        ModelRefreshRequest(api_key="key")
    with pytest.raises(ValidationError):
        ModelRefreshRequest(base_url="https://example.com", api_key=" ")


def test_model_override_validates_url_and_model_shape() -> None:
    valid = {
        "base_url": "https://example.com/v1",
        "auth_field": "Authorization",
        "api_key": "key",
        "main_model": "model-name/latest",
    }
    assert ModelOverride(**valid).main_model == "model-name/latest"
    with pytest.raises(ValidationError):
        ModelOverride(**{**valid, "base_url": "ftp://example.com"})
    with pytest.raises(ValidationError):
        ModelOverride(**{**valid, "main_model": "model name"})


def test_full_url_mode_travels_with_the_custom_endpoint() -> None:
    """两个 API 的 `full_url` 同义；缺省即自动补全，且它只属于自定义端点。"""

    endpoint = {"base_url": "https://example.com/v1", "api_key": "key"}
    override = {**endpoint, "auth_field": "Authorization", "main_model": "fixture"}

    assert ModelRefreshRequest(**endpoint).address_mode == "auto"
    assert ModelRefreshRequest(**endpoint, full_url=False).address_mode == "auto"
    assert ModelRefreshRequest(**endpoint, full_url=True).address_mode == "full"
    assert ModelOverride(**override).address_mode == "auto"
    assert ModelOverride(**override, full_url=True).address_mode == "full"

    # 没有 base_url 就没有「怎么解释这个地址」可言——静默忽略正是 issue #82 那类失效。
    for value in (True, False):
        with pytest.raises(ValidationError):
            ModelRefreshRequest(endpoint_profile="preset", full_url=value)
        with pytest.raises(ValidationError):
            ModelOverride(endpoint_profile="preset", full_url=value)


@pytest.mark.parametrize("suffix", ["?token=private-marker", "#private-marker", "?", "#"])
def test_base_url_rejects_query_and_fragment_on_both_api_inputs(suffix: str) -> None:
    endpoint = {"base_url": "https://example.com/v1" + suffix, "api_key": "key"}
    for schema, payload in (
        (ModelRefreshRequest, endpoint),
        (ModelOverride, {**endpoint, "main_model": "fixture"}),
    ):
        with pytest.raises(ValidationError) as error:
            schema.model_validate(payload)
        message = error.value.errors()[0]["msg"]
        assert "query" in message and "fragment" in message
        assert "private-marker" not in message


def test_section_rejects_values_outside_positive_unique_range() -> None:
    assert parse_section_indices("1, 20") == [1, 20]
    for value in ("0", "1,1", "1,,2", "1,10001"):
        with pytest.raises(ValueError):
            parse_section_indices(value)
