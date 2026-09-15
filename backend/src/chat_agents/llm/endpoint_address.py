"""自定义端点地址解析——运行时对 ``base_url`` 的唯一解释处（issue #83）。

一个地址要回答两个问题：生成打哪个 URL、清单打哪个 URL。历史上这两处各写各的
拼接规则，于是同一份配置在「下载模型」和「运行」两步被解释成两个地址。本模块
把两者收敛成一次解析，调用方只消费结果，不再自己拼路径。

三种模式，前两种给用户自定义端点，第三种只留给服务端预设与既有调用：

- ``auto``：地址是**服务前缀**。只有根地址补 ``v1``，已有 path 一律当作用户
  明确写好的 API 前缀（``/gateway/v1``、``/compatible`` 都要原样保留）。
- ``full``：地址是**最终生成 URL**，一个字符都不加。清单只在 path 以本协议的
  资源后缀结尾时才推得出来——推不出就如实说推不出，绝不试探别的路径。
- ``sdk_native``：把 ``base_url`` 原样交给 SDK，路径由 SDK 自己拼（OpenAI 不补
  版本段、Anthropic 自带 ``v1/``）。服务端 YAML 配的是官方端点，这条是它们的
  既有行为。

path 一律保持原样：不折叠重复 ``/``、不解码 ``%2e%2e``、不删末尾 ``/``。两个 SDK
和 httpx 都按字面发送这些片段，解析这一层擅自规范化就会与真实请求分叉。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from ..validation import validate_base_url
from .protocol import Protocol

AddressMode = Literal["sdk_native", "auto", "full"]

# 生成资源路径。SDK 自己也这么拼——``sdk_native`` 下本模块只是复述 SDK 的规则，
# 不改变它；真正发请求的仍是 SDK。
_OPERATION_PATHS: dict[Protocol, str] = {
    "openai_responses": "responses",
    "openai_chat_completions": "chat/completions",
    "anthropic_messages": "messages",
}
_MODELS_PATH = "models"
_ANTHROPIC_VERSION_PREFIX = "v1"

DISCOVERY_UNAVAILABLE_REASON = (
    "完整 URL 未包含可识别的生成路径，无法推导模型清单地址；请手动填写模型标识"
)


@dataclass(frozen=True, slots=True)
class ResolvedAddress:
    """一次解析的全部结果——生成与发现共用它，不各自再拼一遍。"""

    sdk_base_url: str
    generation_url: str
    discovery_url: str | None
    discovery_unavailable_reason: str | None


def _join(path: str, suffix: str) -> str:
    """只补分隔符。``path`` 已有的结尾 ``/`` 保留，因此重复段不会被吃掉。"""

    return f"{path}{suffix}" if path.endswith("/") else f"{path}/{suffix}"


def _with_path(parts: tuple[str, str], path: str) -> str:
    scheme, netloc = parts
    return urlunsplit((scheme, netloc, path, "", ""))


def _strip_operation_suffix(path: str, operation: str) -> str | None:
    """从最终 URL 反推 API 前缀；只认本协议那一个后缀，且整段匹配。

    ``chat/completions`` 是两段，必须整体剥离——只剥 ``completions`` 会留下一个
    ``chat/`` 前缀，清单就打到一个不存在的地方去了。
    """

    candidate = path[:-1] if path.endswith("/") else path
    suffix = f"/{operation}"
    if not candidate.endswith(suffix):
        return None
    return candidate[: -len(operation)]


def resolve_endpoint_address(
    base_url: str, *, protocol: Protocol, mode: AddressMode = "sdk_native"
) -> ResolvedAddress:
    """把一个用户或配置写下的地址解析成本次调用实际要打的 URL。"""

    validate_base_url(base_url)
    split = urlsplit(base_url)
    origin = (split.scheme, split.netloc)
    path = split.path
    operation = _OPERATION_PATHS[protocol]

    if mode == "full":
        # 生成路径原样使用，包括末尾 `/`；空 path 交给 httpx 的常规 `/`。
        generation_path = path or "/"
        prefix = _strip_operation_suffix(generation_path, operation)
        return ResolvedAddress(
            sdk_base_url=_with_path(origin, ""),
            generation_url=_with_path(origin, generation_path),
            discovery_url=None
            if prefix is None
            else _with_path(origin, _join(prefix, _MODELS_PATH)),
            discovery_unavailable_reason=None
            if prefix is not None
            else DISCOVERY_UNAVAILABLE_REASON,
        )

    if mode == "auto":
        # 只有根地址补版本段。已经写了 path 的人是在告诉我们前缀是什么，替他改
        # 成别的就又回到 issue #83 那种「应用偷偷改地址」的状态。
        prefix = "/v1" if path in ("", "/") else path
    else:
        prefix = (
            _join(path, _ANTHROPIC_VERSION_PREFIX) if protocol == "anthropic_messages" else path
        )

    return ResolvedAddress(
        sdk_base_url=_with_path(origin, path),
        generation_url=_with_path(origin, _join(prefix, operation)),
        discovery_url=_with_path(origin, _join(prefix, _MODELS_PATH)),
        discovery_unavailable_reason=None,
    )
