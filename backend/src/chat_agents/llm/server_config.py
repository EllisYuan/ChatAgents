"""YAML 端点配置文件——服务端预设那一层。

结构错误（缺字段、非法协议、重名、default_profile 悬空）在解析阶段就 raise
`ConfigError`，交给启动流程转为启动失败。env 变量缺失是另一件事：它只让对应
档案在 `build_available_profiles` 里不可用，不影响解析本身，也不该让服务起不来。
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import SecretStr

from ..validation import (
    MAX_PROFILE_NAME_LENGTH,
    validate_auth_field,
    validate_base_url,
    validate_identifier,
    validate_model_identifier,
)
from .errors import ConfigError
from .profile import EndpointProfile
from .protocol import DEFAULT_PROTOCOL, PROTOCOLS, Protocol


@dataclass(frozen=True, slots=True)
class ServerProfileDefinition:
    name: str
    protocol: Protocol
    base_url: str
    auth_field: str
    auth_secret_ref: str
    main_model: str
    auxiliary_model: str | None


@dataclass(frozen=True, slots=True)
class ServerEndpointsConfig:
    default_profile: str
    profiles: dict[str, ServerProfileDefinition]


def _require_str(entry: dict, field: str, *, where: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{where} 缺少字符串字段 {field}")
    return value


def _validated(value: str, *, field: str, where: str, validator: Callable[[str], str]) -> str:
    try:
        return validator(value)
    except ValueError as exc:
        raise ConfigError(f"{where} 的 {field} 不合法：{exc}") from exc


def load_server_endpoints(path: Path) -> ServerEndpointsConfig:
    """解析 YAML 端点配置文件。"""
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"读不到端点配置文件：{path}") from exc

    try:
        raw = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"端点配置文件不是合法 YAML：{path}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"端点配置文件顶层必须是一个映射：{path}")

    default_profile = _validated(
        _require_str(raw, "default_profile", where="端点配置文件"),
        field="default_profile",
        where="端点配置文件",
        validator=lambda value: validate_identifier(
            value, field="default_profile", max_length=MAX_PROFILE_NAME_LENGTH
        ),
    )

    raw_endpoints = raw.get("endpoints")
    if not isinstance(raw_endpoints, list) or not raw_endpoints:
        raise ConfigError("端点配置文件的 endpoints 必须是非空列表")

    profiles: dict[str, ServerProfileDefinition] = {}
    for index, entry in enumerate(raw_endpoints):
        where = f"endpoints[{index}]"
        if not isinstance(entry, dict):
            raise ConfigError(f"{where} 必须是一个映射")
        unknown = set(entry) - {
            "name",
            "protocol",
            "base_url",
            "auth_field",
            "auth_secret_ref",
            "main_model",
            "auxiliary_model",
        }
        if unknown:
            raise ConfigError(f"{where} 包含未知字段：{', '.join(sorted(unknown))}")

        name = _validated(
            _require_str(entry, "name", where=where),
            field="name",
            where=where,
            validator=lambda value: validate_identifier(
                value, field="name", max_length=MAX_PROFILE_NAME_LENGTH
            ),
        )
        if name in profiles:
            raise ConfigError(f"endpoints 中存在重复的 name：{name}")

        protocol = entry.get("protocol", DEFAULT_PROTOCOL)
        if protocol not in PROTOCOLS:
            raise ConfigError(f"档案 {name} 的 protocol 不合法：{protocol!r}")

        base_url = _validated(
            _require_str(entry, "base_url", where=f"档案 {name}"),
            field="base_url",
            where=f"档案 {name}",
            validator=validate_base_url,
        )
        auth_field = _validated(
            _require_str(entry, "auth_field", where=f"档案 {name}"),
            field="auth_field",
            where=f"档案 {name}",
            validator=validate_auth_field,
        )
        auth_secret_ref = _require_str(entry, "auth_secret_ref", where=f"档案 {name}")
        main_model = _validated(
            _require_str(entry, "main_model", where=f"档案 {name}"),
            field="main_model",
            where=f"档案 {name}",
            validator=lambda value: validate_model_identifier(value, field="main_model"),
        )

        auxiliary_model = entry.get("auxiliary_model")
        if auxiliary_model is not None and not isinstance(auxiliary_model, str):
            raise ConfigError(f"档案 {name} 的 auxiliary_model 必须是字符串或省略")
        if auxiliary_model is not None:
            auxiliary_model = _validated(
                auxiliary_model,
                field="auxiliary_model",
                where=f"档案 {name}",
                validator=lambda value: validate_model_identifier(value, field="auxiliary_model"),
            )

        profiles[name] = ServerProfileDefinition(
            name=name,
            protocol=protocol,
            base_url=base_url,
            auth_field=auth_field,
            auth_secret_ref=auth_secret_ref,
            main_model=main_model,
            auxiliary_model=auxiliary_model or None,
        )

    if default_profile not in profiles:
        raise ConfigError(f"default_profile {default_profile!r} 不在 endpoints 列表中")

    return ServerEndpointsConfig(default_profile=default_profile, profiles=profiles)


@dataclass(frozen=True, slots=True)
class UnavailableProfile:
    """env 缺失时的占位——不进选单，不中断启动。"""

    name: str
    reason: str


def build_available_profiles(
    config: ServerEndpointsConfig,
    env: Mapping[str, str] | None = None,
) -> tuple[dict[str, EndpointProfile], dict[str, UnavailableProfile]]:
    """把结构上合法的档案定义与运行环境的密钥可用性对齐。"""
    resolved_env = env if env is not None else os.environ

    available: dict[str, EndpointProfile] = {}
    unavailable: dict[str, UnavailableProfile] = {}

    for name, definition in config.profiles.items():
        secret_value = resolved_env.get(definition.auth_secret_ref)
        if not secret_value:
            unavailable[name] = UnavailableProfile(
                name=name,
                reason=f"环境变量 {definition.auth_secret_ref} 未设置",
            )
            continue
        available[name] = EndpointProfile(
            name=definition.name,
            protocol=definition.protocol,
            base_url=definition.base_url,
            auth_field=definition.auth_field,
            api_key=SecretStr(secret_value),
        )

    return available, unavailable
