"""错误码单一事实来源（issue #52，ADR-0021）。

流开始前的 RFC 9457 响应体 `type` 字段，与流开始后 `RUN_ERROR.code` 字段，
必须是同一个字符串——这条纪律 schema 层面无从校验，只能靠两处都从这一个表里
取值。异常类型只有五个（`exceptions.py`），这里不新增第六个，未落在表里的
异常一律走 `UNKNOWN_ERROR_CODE` 兜底。
"""

from __future__ import annotations

from .exceptions import (
    AuthenticationFailed,
    ChatAgentsError,
    ModelNotFound,
    ProtocolError,
    SessionNotFound,
    UpstreamUnavailable,
)

ERROR_CODES: dict[type[ChatAgentsError], str] = {
    AuthenticationFailed: "authentication_failed",
    ModelNotFound: "model_not_found",
    UpstreamUnavailable: "upstream_unavailable",
    ProtocolError: "protocol_error",
    SessionNotFound: "session_not_found",
}

HTTP_STATUS: dict[type[ChatAgentsError], int] = {
    AuthenticationFailed: 401,
    ModelNotFound: 404,
    UpstreamUnavailable: 502,
    ProtocolError: 400,
    SessionNotFound: 404,
}

# 兜底——未分类的失败（包括 RunFailed 携带的上游原文，ADR-0015 不分类）与真正
# 意外的异常共用这一个值，不因此新增第六个异常类。
UNKNOWN_ERROR_CODE = "internal_error"
UNKNOWN_HTTP_STATUS = 500

# RunEvent.RunFailed 不是本项目的领域异常（它是 Runner 把任意上游异常事件化后的
# 文本），固定用这个码，与 UNKNOWN_ERROR_CODE 区分开，便于前端/评测按码分流。
RUN_FAILED_CODE = "run_failed"


def error_code(exc: Exception) -> str:
    return ERROR_CODES.get(type(exc), UNKNOWN_ERROR_CODE)


def http_status(exc: Exception) -> int:
    return HTTP_STATUS.get(type(exc), UNKNOWN_HTTP_STATUS)
