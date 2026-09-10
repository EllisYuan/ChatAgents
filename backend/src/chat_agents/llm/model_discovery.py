"""运行时发现端点可寻址模型清单（ADR-0016）。

模型发现是独立于 ``ModelPort.stream`` 的能力：生成协议可以是三者之一，清单
始终只读取 OpenAI 格式清单，只消费 ``id`` 与 ``owned_by``；路径遵循所选协议的 SDK base。

``DiscoveredModel`` 表是发现任务的写入边界，不是业务 CRUD 资源。服务端预设
由自动发现写入；用户自定义端点只返回本次结果，永不经过 store。
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx2

from ..model_catalog import ModelCatalog, ModelCatalogStore, ModelItem
from ..validation import validate_model_identifier, validate_non_blank
from .endpoint_address import (
    DISCOVERY_UNAVAILABLE_REASON,
    AddressMode,
    resolve_endpoint_address,
)
from .profile import EndpointProfile
from .protocol import Protocol as LlmProtocol
from .server_config import ServerEndpointsConfig, build_available_profiles

MODEL_DISCOVERY_TIMEOUT_SECONDS = 5.0
MODEL_DISCOVERY_INTERVAL_SECONDS = 24 * 60 * 60
MODEL_DISCOVERY_ENABLED_ENV = "CHATAGENTS_MODEL_DISCOVERY_ENABLED"
# Anthropic 要求每个请求都带这个头；官方 SDK 自己会带，清单请求是自己发的 HTTP。
ANTHROPIC_VERSION = "2023-06-01"
# 上游没给分组标签时的占位——只影响选单分组，不进模型标识。
UNKNOWN_OWNER = "unknown"

logger = logging.getLogger(__name__)


class ModelDiscoveryError(RuntimeError):
    """上游清单不可读取或形状不符合 OpenAI 格式。"""


class ModelsHttpClient(Protocol):
    async def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,  # noqa: ASYNC109 - forwarded to the HTTP client's total timeout
    ) -> Any: ...


def models_url(base_url: str, *, protocol: LlmProtocol, mode: AddressMode = "sdk_native") -> str:
    """清单 URL——与生成同出一次解析（``endpoint_address``），不另立拼接规则。

    完整 URL 模式下清单地址可能压根推不出来，那时 ``ModelDiscoveryError`` 是唯一
    诚实的回答：随便挑一个路径试探，等于用一次猜测冒充用户的配置。
    """

    resolved = resolve_endpoint_address(base_url, protocol=protocol, mode=mode)
    if resolved.discovery_url is None:
        raise ModelDiscoveryError(
            resolved.discovery_unavailable_reason or DISCOVERY_UNAVAILABLE_REASON
        )
    return resolved.discovery_url


def _parse_models(payload: Any) -> tuple[ModelItem, ...]:
    if not isinstance(payload, dict):
        raise ValueError("模型清单响应顶层必须是对象")
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("模型清单响应缺少数组字段 data")

    result: list[ModelItem] = []
    seen: set[str] = set()
    for index, raw_item in enumerate(data):
        if not isinstance(raw_item, dict):
            raise ValueError(f"模型清单 data[{index}] 必须是对象")
        model_id = raw_item.get("id")
        owned_by = raw_item.get("owned_by")
        if not isinstance(model_id, str):
            raise ValueError(f"模型清单 data[{index}] 缺少字符串 id")
        try:
            model_id = validate_model_identifier(model_id)
        except ValueError as exc:
            raise ValueError(f"模型清单 data[{index}] 的 id 不合法：{exc}") from exc
        # owned_by 只是选单的分组标签（前端 ModelPicker 按它分桶），不是标识的一部分。
        # Anthropic 官方 /v1/models 整个响应都没有这个字段（2026-09-01 实测），
        # 缺了就整份清单作废是拿一个显示细节否掉全部可寻址模型——按未知分组收下。
        if owned_by is None:
            owned_by = UNKNOWN_OWNER
        elif not isinstance(owned_by, str):
            raise ValueError(f"模型清单 data[{index}] 的 owned_by 必须是字符串")
        else:
            try:
                validate_non_blank(owned_by, field="owned_by", max_length=256)
            except ValueError as exc:
                raise ValueError(f"模型清单 data[{index}] 的 owned_by 不合法：{exc}") from exc
        if model_id in seen:
            continue
        seen.add(model_id)
        result.append(ModelItem(model_id=model_id, owned_by=owned_by))
    return tuple(result)


def _discovery_headers(profile: EndpointProfile) -> dict[str, str]:
    """清单请求的鉴权头。

    生成路径由官方 SDK 构造请求，这两件事 SDK 替我们做了；清单请求是自己发的
    HTTP，得自己补上（2026-09-01 实测，两处缺失各让一个官方端点 4xx）：

    - ``Authorization`` 要带 ``Bearer `` 前缀，否则 OpenAI 401；
    - Anthropic 要求 ``anthropic-version``，缺了就 400。

    档案自定义的鉴权头字段名照原样使用——``auth_field`` 是端点档案的属性
    （ADR-0014），中转站可能约定别的头名，这里不替它做判断。
    """

    secret = profile.api_key.get_secret_value()
    if profile.auth_field.lower() == "authorization" and not secret.lower().startswith("bearer "):
        secret = f"Bearer {secret}"
    headers = {profile.auth_field: secret}
    if profile.protocol == "anthropic_messages":
        headers["anthropic-version"] = ANTHROPIC_VERSION
    return headers


# 上游响应体截断长度——够看清是哪种错误（密钥/模型名/额度），不做无界拼接。
MAX_RESPONSE_DETAIL_LENGTH = 500


def _response_detail(response: Any) -> str:
    """尽力取一段可读的上游响应体，取不到就返回空串（ADR-0015：错误原样透传）。"""
    try:
        text = getattr(response, "text", "")
    except Exception:
        return ""
    if not isinstance(text, str):
        return ""
    text = text.strip()
    if len(text) > MAX_RESPONSE_DETAIL_LENGTH:
        text = f"{text[:MAX_RESPONSE_DETAIL_LENGTH]}…"
    return text


async def _get_models(
    profile: EndpointProfile,
    *,
    http_client: ModelsHttpClient | None,
    timeout: float,  # noqa: ASYNC109 - forwarded to the HTTP client's total timeout
) -> tuple[ModelItem, ...]:
    # URL 先解析：完整 URL 推不出清单地址时在这里就抛，一个 HTTP 请求都不发。
    url = models_url(profile.base_url, protocol=profile.protocol, mode=profile.address_mode)
    headers = _discovery_headers(profile)

    if http_client is not None:
        response = await http_client.get(url, headers=headers, timeout=timeout)
    else:
        async with httpx2.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers)

    status_code = getattr(response, "status_code", None)
    if not isinstance(status_code, int) or status_code < 200 or status_code >= 300:
        detail = _response_detail(response)
        message = f"模型清单上游返回 HTTP {status_code}"
        if detail:
            message = f"{message}：{detail}"
        raise ModelDiscoveryError(message)

    try:
        payload = response.json()
    except Exception as exc:
        raise ModelDiscoveryError("模型清单上游返回的不是合法 JSON") from exc

    try:
        return _parse_models(payload)
    except ValueError as exc:
        raise ModelDiscoveryError(str(exc)) from exc


async def discover_openai_models(
    profile: EndpointProfile,
    *,
    http_client: ModelsHttpClient | None = None,
    timeout: float = MODEL_DISCOVERY_TIMEOUT_SECONDS,  # noqa: ASYNC109
) -> tuple[ModelItem, ...]:
    """读取一个端点的 OpenAI 格式清单；调用方负责决定失败后的降级行为。"""
    try:
        return await _get_models(profile, http_client=http_client, timeout=timeout)
    except ModelDiscoveryError:
        raise
    except Exception as exc:
        # 按 ADR-0015「上游错误原样透传」：异常原文（连接失败、DNS、超时）交回用户，
        # 让填错 URL/key 的人能照着原话去改，而不是猜一句「不可达」到底是哪种不可达。
        raise ModelDiscoveryError(f"模型清单上游不可达：{exc}") from exc


class InMemoryModelCatalogStore:
    """测试与本地装配用的 store；生产写入使用 ``SqlAlchemyModelCatalogStore``。"""

    def __init__(self) -> None:
        self._catalogs: dict[str, tuple[tuple[ModelItem, ...], datetime]] = {}

    async def load(self, endpoint_profile: str) -> tuple[tuple[ModelItem, ...], datetime | None]:
        stored = self._catalogs.get(endpoint_profile)
        if stored is None:
            return (), None
        return stored

    async def replace(
        self,
        endpoint_profile: str,
        models: tuple[ModelItem, ...],
        discovered_at: datetime,
    ) -> None:
        self._catalogs[endpoint_profile] = (models, discovered_at)


class ModelDiscoveryService:
    """编排预设端落库与自定义端临时发现两条不同生命周期。"""

    def __init__(
        self,
        store: ModelCatalogStore,
        *,
        server_config: ServerEndpointsConfig | None = None,
        env: Mapping[str, str] | None = None,
        http_client: ModelsHttpClient | None = None,
        clock: Any | None = None,
    ) -> None:
        self._store = store
        self._server_config = server_config
        self._env = env
        self._http_client = http_client
        self._clock = clock or (lambda: datetime.now(UTC))

    async def refresh_preset(self, profile: EndpointProfile) -> ModelCatalog:
        old_models, old_success_at = await self._store.load(profile.name)
        try:
            models = await discover_openai_models(profile, http_client=self._http_client)
            if not models:
                raise ModelDiscoveryError("模型清单为空")
        except ModelDiscoveryError as exc:
            logger.warning("模型清单发现失败，保留上次成功清单：profile=%s", profile.name)
            return ModelCatalog(
                models=old_models,
                source="fallback",
                last_success_at=old_success_at,
                error=str(exc),
            )

        discovered_at = self._clock()
        await self._store.replace(profile.name, models, discovered_at)
        return ModelCatalog(
            models=models,
            source="discovered",
            last_success_at=discovered_at,
        )

    async def refresh_custom(self, profile: EndpointProfile) -> ModelCatalog:
        try:
            models = await discover_openai_models(profile, http_client=self._http_client)
            if not models:
                raise ModelDiscoveryError("模型清单为空")
        except ModelDiscoveryError as exc:
            logger.warning("自定义端模型清单发现失败：profile=%s", profile.name)
            return ModelCatalog(models=(), source="fallback", last_success_at=None, error=str(exc))
        return ModelCatalog(
            models=models,
            source="discovered",
            last_success_at=self._clock(),
        )

    async def refresh_configured_presets(
        self,
        server_config: ServerEndpointsConfig | None = None,
        *,
        env: Mapping[str, str] | None = None,
        profiles: Mapping[str, EndpointProfile] | None = None,
    ) -> dict[str, ModelCatalog]:
        if profiles is None:
            resolved_config = server_config or self._server_config
            if resolved_config is None:
                raise ValueError("server_config 或 profiles 必须提供一个")
            resolved_env = self._env if env is None else env
            profiles, _ = build_available_profiles(resolved_config, resolved_env)
        return {name: await self.refresh_preset(profile) for name, profile in profiles.items()}


async def periodic_model_refresh(
    service: Any,
    *,
    sleep: Any = asyncio.sleep,
    interval_seconds: float = MODEL_DISCOVERY_INTERVAL_SECONDS,
) -> None:
    """启动即刷新，随后每 24 小时刷新；取消由应用 shutdown 传播。"""
    while True:
        await service.refresh_configured_presets()
        await sleep(interval_seconds)


def start_model_refresh_task(
    service: Any, *, env: Mapping[str, str] | None = None
) -> asyncio.Task[None] | None:
    """按 env 开关创建进程内 task；应用 shutdown 负责取消返回的 task。"""
    if not is_model_discovery_enabled(env):
        return None
    return asyncio.create_task(periodic_model_refresh(service))


@asynccontextmanager
async def model_discovery_lifespan(
    service: Any,
    *,
    env: Mapping[str, str] | None = None,
) -> Any:
    """给 FastAPI lifespan 使用的 task 生命周期包装。"""
    task = start_model_refresh_task(service, env=env)
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def is_model_discovery_enabled(env: Mapping[str, str] | None = None) -> bool:
    resolved_env = os.environ if env is None else env
    value = resolved_env.get(MODEL_DISCOVERY_ENABLED_ENV)
    return value is None or value.strip().lower() not in {"0", "false", "no", "off"}
