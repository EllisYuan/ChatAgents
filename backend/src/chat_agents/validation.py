"""跨 API、配置和工具边界共用的输入约束。"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

MAX_MESSAGE_LENGTH = 32_000
MAX_TITLE_LENGTH = 30
MAX_MODEL_IDENTIFIER_LENGTH = 256
MAX_BASE_URL_LENGTH = 2_048
MAX_PROFILE_NAME_LENGTH = 100
MAX_AUTH_FIELD_LENGTH = 128
MAX_SECTION_COUNT = 100
MAX_SECTION_INDEX = 10_000

_MODEL_IDENTIFIER_RE = re.compile(r"^[^\s\x00-\x1f\x7f]+$")
_HEADER_NAME_RE = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
_SECTION_RE = re.compile(r"^[1-9][0-9]{0,3}(?:\s*,\s*[1-9][0-9]{0,3})*$")


def validate_non_blank(value: str, *, field: str, max_length: int) -> str:
    """验证一个需要内容的字符串，但不改变调用方传入的文本。"""
    if not value.strip():
        raise ValueError(f"{field} 不能是空白字符串")
    if len(value) > max_length:
        raise ValueError(f"{field} 长度不能超过 {max_length} 个字符")
    return value


def validate_identifier(value: str, *, field: str, max_length: int) -> str:
    """验证模型或档案标识的形态，不判断标识是否存在。"""
    validate_non_blank(value, field=field, max_length=max_length)
    if not _MODEL_IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{field} 只能包含非空白、非控制字符")
    return value


def validate_model_identifier(value: str, *, field: str = "model") -> str:
    return validate_identifier(value, field=field, max_length=MAX_MODEL_IDENTIFIER_LENGTH)


def validate_base_url(value: str, *, field: str = "base_url") -> str:
    """验证 HTTP(S) URL 的形态；不会发起网络请求。"""
    validate_non_blank(value, field=field, max_length=MAX_BASE_URL_LENGTH)
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in value):
        raise ValueError(f"{field} 不能包含控制字符")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
    except ValueError as exc:
        raise ValueError(f"{field} 不是合法 URL") from exc
    if parsed.scheme not in {"http", "https"} or not hostname:
        raise ValueError(f"{field} 必须是带 host 的 http 或 https URL")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError(f"{field} 不能包含用户凭据")
    return value


def validate_auth_field(value: str) -> str:
    validate_non_blank(value, field="auth_field", max_length=MAX_AUTH_FIELD_LENGTH)
    if not _HEADER_NAME_RE.fullmatch(value):
        raise ValueError("auth_field 不是合法 HTTP header 名称")
    return value


def validate_section(value: str) -> str:
    """验证 web_reader 的逗号分隔正整数章节列表。"""
    validate_non_blank(value, field="section", max_length=MAX_SECTION_COUNT * 5)
    if not _SECTION_RE.fullmatch(value):
        raise ValueError("section 必须是逗号分隔的正整数列表")
    parts = [part.strip() for part in value.split(",")]
    if len(parts) > MAX_SECTION_COUNT:
        raise ValueError(f"section 一次最多请求 {MAX_SECTION_COUNT} 个章节")
    indices = [int(part) for part in parts]
    if any(index > MAX_SECTION_INDEX for index in indices):
        raise ValueError(f"section 章节编号不能超过 {MAX_SECTION_INDEX}")
    if len(set(indices)) != len(indices):
        raise ValueError("section 不能包含重复章节编号")
    return value
