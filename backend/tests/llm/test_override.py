"""ModelOverride 的校验边界——静默忽略用户填的字段正是 issue #82 要修的那类失效。"""

import pytest
from chat_agents.llm.override import ModelOverride
from pydantic import SecretStr, ValidationError


def test_empty_override_is_valid_and_reads_as_a_preset_profile() -> None:
    override = ModelOverride()

    assert override.is_custom_endpoint is False
    assert override.main_model is None


def test_custom_endpoint_requires_key_and_main_model() -> None:
    with pytest.raises(ValidationError):
        ModelOverride(base_url="https://relay.example.com/v1", main_model="m")
    with pytest.raises(ValidationError):
        ModelOverride(base_url="https://relay.example.com/v1", api_key=SecretStr("sk"))


def test_endpoint_sources_are_mutually_exclusive() -> None:
    with pytest.raises(ValidationError):
        ModelOverride(
            endpoint_profile="anthropic-official",
            base_url="https://relay.example.com/v1",
            api_key=SecretStr("sk"),
            main_model="m",
        )


def test_endpoint_fields_without_base_url_are_rejected_not_ignored() -> None:
    for field, value in (
        ("protocol", "openai_responses"),
        ("auth_field", "Authorization"),
        ("api_key", SecretStr("sk")),
    ):
        with pytest.raises(ValidationError):
            ModelOverride(**{field: value})


def test_model_identifier_shape_is_validated() -> None:
    with pytest.raises(ValidationError):
        ModelOverride(main_model="model name")
    with pytest.raises(ValidationError):
        ModelOverride(auxiliary_model=" ")
    assert ModelOverride(main_model="model-name/latest").main_model == "model-name/latest"


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ModelOverride(model="claude-opus-5")


def test_api_key_never_appears_in_repr() -> None:
    override = ModelOverride(
        base_url="https://relay.example.com/v1", api_key=SecretStr("sk-secret"), main_model="m"
    )

    assert "sk-secret" not in repr(override)
    assert "sk-secret" not in str(override)
