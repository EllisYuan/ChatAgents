"""流前 HTTP 状态码与流后 RUN_ERROR.code 必须共用同一份错误码表（ADR-0021）。"""

from __future__ import annotations

from chat_agents import exceptions
from chat_agents.error_codes import (
    ERROR_CODES,
    HTTP_STATUS,
    RUN_FAILED_CODE,
    UNKNOWN_ERROR_CODE,
    UNKNOWN_HTTP_STATUS,
    error_code,
    http_status,
)

_DOMAIN_EXCEPTIONS = [
    exceptions.AuthenticationFailed,
    exceptions.ModelNotFound,
    exceptions.UpstreamUnavailable,
    exceptions.ProtocolError,
    exceptions.SessionNotFound,
]


def test_exactly_five_domain_exceptions_are_mapped() -> None:
    assert set(ERROR_CODES) == set(_DOMAIN_EXCEPTIONS)
    assert set(HTTP_STATUS) == set(_DOMAIN_EXCEPTIONS)


def test_error_code_and_http_status_agree_for_every_domain_exception() -> None:
    for cls in _DOMAIN_EXCEPTIONS:
        exc = cls("boom")
        assert error_code(exc) == ERROR_CODES[cls]
        assert http_status(exc) == HTTP_STATUS[cls]


def test_unknown_exception_falls_back_without_a_sixth_class() -> None:
    exc = RuntimeError("unexpected")
    assert error_code(exc) == UNKNOWN_ERROR_CODE
    assert http_status(exc) == UNKNOWN_HTTP_STATUS


def test_run_failed_code_is_distinct_and_stable() -> None:
    assert RUN_FAILED_CODE != UNKNOWN_ERROR_CODE
    assert RUN_FAILED_CODE not in ERROR_CODES.values()
