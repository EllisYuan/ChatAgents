"""Issue #64 输入校验的纯边界测试。"""

from uuid import uuid4

import pytest
from chat_agents.api_models import ModelRefreshRequest
from chat_agents.conversation.models import RenameSessionRequest, UserMessageRequest
from chat_agents.llm.user_config import UserEndpointConfig
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


def test_user_endpoint_config_validates_url_and_model_shape() -> None:
    valid = {
        "base_url": "https://example.com/v1",
        "auth_field": "Authorization",
        "api_key": "key",
        "main_model": "model-name/latest",
    }
    assert UserEndpointConfig(**valid).main_model == "model-name/latest"
    with pytest.raises(ValidationError):
        UserEndpointConfig(**{**valid, "base_url": "ftp://example.com"})
    with pytest.raises(ValidationError):
        UserEndpointConfig(**{**valid, "main_model": "model name"})


def test_section_rejects_values_outside_positive_unique_range() -> None:
    assert parse_section_indices("1, 20") == [1, 20]
    for value in ("0", "1,1", "1,,2", "1,10001"):
        with pytest.raises(ValueError):
            parse_section_indices(value)
