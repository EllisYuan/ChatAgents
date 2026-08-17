"""EndpointProfile 是两条构造路径交汇的同一个 frozen dataclass 类型。"""

import dataclasses

import pytest
from chat_agents.llm.profile import EndpointProfile
from pydantic import SecretStr


def _make_profile() -> EndpointProfile:
    return EndpointProfile(
        name="anthropic-official",
        protocol="anthropic_messages",
        base_url="https://api.anthropic.com",
        auth_field="x-api-key",
        api_key=SecretStr("sk-test"),
    )


def test_is_frozen_dataclass() -> None:
    profile = _make_profile()
    assert dataclasses.is_dataclass(profile)
    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(profile, "name", "mutated")  # noqa: B010


def test_api_key_is_secret_str() -> None:
    profile = _make_profile()
    assert isinstance(profile.api_key, SecretStr)
    assert "sk-test" not in repr(profile)
    assert "sk-test" not in str(profile)
