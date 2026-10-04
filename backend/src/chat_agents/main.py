"""FastAPI 入口——三重包装在这一处组装（issue #52，ADR-0008/0009）。

```python
encode_sse(              # 传输层：领域事件 → AG-UI 线格式
    observe(             # observability/：落跨度，独立事务，失败只记日志
        persist(         # conversation/：落消息，业务事务，失败要报错
            runner.run(messages, ...))))
```

流开始前的失败（档案校验、会话存在性、空消息）走正常 HTTP 状态码；流开始后
的失败一律走 ``RUN_ERROR`` 事件，HTTP 已经是 200 改不了——这是 ``encode_sse``
一处的职责，``main.py`` 只负责把「流开始前」这一段做完。
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4, uuid5

import httpx
import structlog
from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sse_starlette.sse import EventSourceResponse

from .agent.runner import AgentRunner
from .agent.versioning import TITLE_PROMPT_TEMPLATE
from .api_models import (
    HealthResponse,
    ModelItemView,
    ModelProfileChoice,
    ModelProfilesResponse,
    ModelProfileView,
    ModelRefreshRequest,
    ModelRefreshResponse,
    ModelsResponse,
    ProblemDetails,
)
from .conversation.models import TitleGenerationRequest, TitleGenerationResponse
from .conversation.router import router as conversation_router
from .conversation.service import ConversationService
from .conversation.streaming import persist
from .database import get_session_factory
from .db.model_catalog import SqlAlchemyModelCatalogStore
from .error_codes import error_code, http_status
from .eval_summary.router import router as eval_summary_router
from .exceptions import AuthenticationFailed, ChatAgentsError, ProtocolError, SessionNotFound
from .llm.effort import EffortTier
from .llm.errors import ProfileUnavailableError
from .llm.events import ModelCallCompleted, Usage
from .llm.message import ModelMessage, TextBlock
from .llm.model_discovery import ModelDiscoveryService, model_discovery_lifespan
from .llm.override import ModelOverride
from .llm.port import ModelPort, model_port_scope
from .llm.profile import EndpointProfile
from .llm.resolve import ResolvedProfiles, resolve_profiles
from .llm.server_config import build_available_profiles, load_server_endpoints
from .llm.settings import Settings
from .logging_config import configure_logging
from .observability.router import router as observability_router
from .observability.streaming import observe
from .observability.writer import RunWriter
from .transport.custom_events import SpanPayload, ToolResultPayload, UsagePayload
from .transport.sse import encode_sse
from .validation import (
    MAX_MESSAGE_LENGTH,
    MAX_PROFILE_NAME_LENGTH,
    MAX_TITLE_LENGTH,
    validate_non_blank,
)

configure_logging()
logger = structlog.get_logger(__name__)
_TITLE_TIMEOUT_SECONDS = 30


@asynccontextmanager
async def _app_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """管理模型清单 24 小时刷新任务的生命周期。"""

    settings = Settings()
    config = load_server_endpoints(settings.endpoints_config_path)
    store = SqlAlchemyModelCatalogStore(get_session_factory())
    service = ModelDiscoveryService(store, server_config=config)
    async with model_discovery_lifespan(service):
        yield


app = FastAPI(title="ChatAgents", lifespan=_app_lifespan)
app.include_router(conversation_router)
app.include_router(observability_router)
app.include_router(eval_summary_router)


def _custom_openapi() -> dict[str, Any]:
    """把三个自有 ``Custom`` 载荷注入 ``components.schemas``（ADR-0021）。

    AG-UI 的 ``CustomEvent.value`` 是无类型的 ``Any``——三个载荷是契约里唯一
    无人替我们把关的部分，即使没有任何路径引用它们，也要让它们进最终产出的
    schema，供前端的 ``openapi-typescript`` 生成类型。
    """

    if app.openapi_schema:
        result: dict[str, Any] = app.openapi_schema
        return result
    schema: dict[str, Any] = get_openapi(title=app.title, version=app.version, routes=app.routes)
    schemas = schema.setdefault("components", {}).setdefault("schemas", {})
    for name, model in (
        ("ChatAgentsUsagePayload", UsagePayload),
        ("ChatAgentsSpanPayload", SpanPayload),
        ("ChatAgentsToolResultPayload", ToolResultPayload),
        ("ProblemDetails", ProblemDetails),
    ):
        schemas[name] = model.model_json_schema(ref_template="#/components/schemas/{model}")
    problem_response = {
        "description": "请求参数不合法",
        "content": {
            "application/problem+json": {"schema": {"$ref": "#/components/schemas/ProblemDetails"}}
        },
    }
    for path_item in schema["paths"].values():
        for operation in path_item.values():
            if isinstance(operation, dict) and "responses" in operation:
                operation["responses"].setdefault("400", problem_response)
    app.openapi_schema = schema
    return schema


app.openapi = _custom_openapi


class RunRequest(BaseModel):
    """``POST /api/runs`` 的请求体。

    ``model_override`` 是可选的——不传就是「用服务端预设的一切」，行为与它存在
    之前完全一致（issue #82）。传了则逐字段覆盖，覆盖只活这一次运行：不落库、
    不进会话行、不进任何进程级缓存，因此多个访客之间没有共享状态可踩。
    """

    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)
    effort: EffortTier = "medium"
    model_override: ModelOverride | None = None

    @field_validator("message")
    @classmethod
    def _validate_message(cls, value: str) -> str:
        return validate_non_blank(value, field="message", max_length=MAX_MESSAGE_LENGTH)


def _problem_response(exc: ChatAgentsError) -> JSONResponse:
    """RFC 9457：``type`` 与流后 ``RUN_ERROR.code`` 共用同一份错误码表。"""

    problem = ProblemDetails(
        type=error_code(exc),
        title=type(exc).__name__,
        detail=str(exc),
        status=http_status(exc),
        upstream_error=exc.upstream_error,
        run_id=exc.run_id,
        key_source=exc.key_source,
    )
    return JSONResponse(
        status_code=problem.status,
        content=problem.model_dump(mode="json"),
        media_type="application/problem+json",
    )


@app.exception_handler(ChatAgentsError)
async def _domain_error_handler(request: Request, exc: ChatAgentsError) -> JSONResponse:
    del request
    return _problem_response(exc)


def _validation_detail(exc: RequestValidationError) -> str:
    errors: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ())) or "request"
        errors.append(f"{location}: {error.get('msg', '输入不合法')}")
    return "请求参数校验失败：" + "; ".join(errors)


@app.exception_handler(RequestValidationError)
async def _request_validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    del request
    return _problem_response(ProtocolError(_validation_detail(exc)))


def _health_payload() -> HealthResponse:
    return HealthResponse(status="ok", version=os.environ.get("APP_VERSION", "dev"))


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return _health_payload()


def get_model_catalog_store() -> SqlAlchemyModelCatalogStore:
    """生产环境的模型清单存储；测试可通过依赖覆盖替换。"""

    return SqlAlchemyModelCatalogStore(get_session_factory())


def get_model_discovery_service(
    store: Annotated[SqlAlchemyModelCatalogStore, Depends(get_model_catalog_store)],
) -> ModelDiscoveryService:
    settings = Settings()
    config = load_server_endpoints(settings.endpoints_config_path)
    return ModelDiscoveryService(store, server_config=config)


def _models_response(
    *,
    endpoint_profile: str,
    profile: ModelProfileView,
    models: tuple[Any, ...],
    source: Literal["discovered", "fallback"],
    last_success_at: Any,
    error: str | None,
) -> ModelsResponse:
    return ModelsResponse(
        endpoint_profile=endpoint_profile,
        profile=profile,
        models=[
            ModelItemView(
                id=item.model_id, owned_by=item.owned_by, endpoint_profile=endpoint_profile
            )
            for item in models
        ],
        source=source,
        last_success_at=last_success_at,
        error=error,
    )


async def _default_profile_context() -> tuple[Any, dict[str, Any], dict[str, Any]]:
    settings = Settings()
    config = load_server_endpoints(settings.endpoints_config_path)
    available, unavailable = build_available_profiles(config)
    return config, available, unavailable


@app.get("/api/models/profiles", response_model=ModelProfilesResponse, tags=["models"])
async def list_model_profiles() -> ModelProfilesResponse:
    """枚举服务端已配置的端点档案（issue #70）；前端据此渲染档案选择槽位。"""

    config, available, unavailable = await _default_profile_context()
    return ModelProfilesResponse(
        default_profile=config.default_profile,
        profiles=[
            ModelProfileChoice(
                name=name,
                status="available",
                main_model=config.profiles[name].main_model,
                auxiliary_model=config.profiles[name].auxiliary_model,
            )
            for name in config.profiles
            if name in available
        ]
        + [
            ModelProfileChoice(name=name, status="unavailable", reason=profile.reason)
            for name, profile in unavailable.items()
        ],
    )


@app.get("/api/models", response_model=ModelsResponse, tags=["models"])
async def list_models(
    store: Annotated[SqlAlchemyModelCatalogStore, Depends(get_model_catalog_store)],
    endpoint_profile: Annotated[str | None, Query(max_length=MAX_PROFILE_NAME_LENGTH)] = None,
) -> ModelsResponse:
    config, available, unavailable = await _default_profile_context()
    profile_name = endpoint_profile or config.default_profile
    unavailable_profile = unavailable.get(profile_name)
    if unavailable_profile is not None:
        return _models_response(
            endpoint_profile=profile_name,
            profile=ModelProfileView(
                name=profile_name, status="unavailable", reason=unavailable_profile.reason
            ),
            models=(),
            source="fallback",
            last_success_at=None,
            error=None,
        )
    if profile_name not in available:
        raise ProtocolError(f"未知端点档案：{profile_name}")

    models, last_success_at = await store.load(profile_name)
    return _models_response(
        endpoint_profile=profile_name,
        profile=ModelProfileView(name=profile_name, status="available"),
        models=models,
        source="discovered" if models else "fallback",
        last_success_at=last_success_at,
        error=None if models else "模型清单为空",
    )


@app.post("/api/models/refresh", response_model=ModelRefreshResponse, tags=["models"])
async def refresh_models(
    request: ModelRefreshRequest,
    service: Annotated[ModelDiscoveryService, Depends(get_model_discovery_service)],
) -> ModelRefreshResponse:
    if request.base_url is not None:
        if request.api_key is None:
            raise ProtocolError("自定义端点缺少 api_key")
        profile_name = request.endpoint_profile or "custom"
        profile = EndpointProfile(
            name=profile_name,
            protocol=request.protocol,
            base_url=request.base_url,
            auth_field=request.auth_field,
            api_key=request.api_key,
            address_mode=request.address_mode,
        )
        catalog = await service.refresh_custom(profile)
        return ModelRefreshResponse(
            **_models_response(
                endpoint_profile=profile_name,
                profile=ModelProfileView(name=profile_name, status="available"),
                models=catalog.models,
                source=catalog.source,
                last_success_at=catalog.last_success_at,
                error=catalog.error,
            ).model_dump()
        )

    config, available, unavailable = await _default_profile_context()
    profile_name = request.endpoint_profile or config.default_profile
    if profile_name in unavailable:
        unavailable_profile = unavailable[profile_name]
        return ModelRefreshResponse(
            **_models_response(
                endpoint_profile=profile_name,
                profile=ModelProfileView(
                    name=profile_name, status="unavailable", reason=unavailable_profile.reason
                ),
                models=(),
                source="fallback",
                last_success_at=None,
                error=None,
            ).model_dump()
        )
    if profile_name not in available:
        raise ProtocolError(f"未知端点档案：{profile_name}")

    catalog = await service.refresh_preset(available[profile_name])
    return ModelRefreshResponse(
        **_models_response(
            endpoint_profile=profile_name,
            profile=ModelProfileView(name=profile_name, status="available"),
            models=catalog.models,
            source=catalog.source,
            last_success_at=catalog.last_success_at,
            error=catalog.error,
        ).model_dump()
    )


def get_agent_runner() -> AgentRunner:
    """默认用真实 ``ModelPort`` 的 Runner——测试用 ``app.dependency_overrides`` 换假端口。"""

    return AgentRunner()


def get_title_model_port_factory() -> Callable[[EndpointProfile], ModelPort] | None:
    """测试可替换标题调用的模型边界，线上由 ``model_port_scope`` 管理资源。"""

    return None


@app.post("/api/runs")
async def create_run(
    request: RunRequest, runner: Annotated[AgentRunner, Depends(get_agent_runner)]
) -> EventSourceResponse:
    session_factory = get_session_factory()
    settings = Settings()

    try:
        server_config = load_server_endpoints(settings.endpoints_config_path)
        resolved = resolve_profiles(server_config, request.model_override)
    except ProfileUnavailableError as exc:
        # 密钥未配置——运行时错误，不是启动期结构错误（llm/errors.py 的 docstring）。
        raise AuthenticationFailed(str(exc)) from exc

    user_message_id = uuid4()
    async with session_factory() as session, session.begin():
        service = ConversationService(session)
        await service.append_user_message_with_title_candidate(
            session_id=request.session_id, message_id=user_message_id, text=request.message
        )
    async with session_factory() as session:
        projection = await ConversationService(session).rebuild_model_input_with_metadata(
            request.session_id
        )
        messages = projection.messages

    run_id = str(uuid4())
    http_client = httpx.AsyncClient()
    # 访客自带的中转站不进进程级客户端缓存（issue #82）——它按 base URL 为键、容量
    # 只有 8，访客一多就互相淘汰，且淘汰时不关客户端。ADR-0016 的「访客的东西不进
    # 全局设施」在这里的第二次落地。
    custom_endpoint = (
        request.model_override is not None and request.model_override.is_custom_endpoint
    )

    async def stream() -> AsyncIterator[str]:
        try:
            raw_events = runner.run(
                messages,
                profile=resolved.profile,
                main_model=resolved.main_model,
                effort=request.effort,
                http_client=http_client,
                run_id=run_id,
                shared_model_client=not custom_endpoint,
            )
            scope_service = object.__new__(ConversationService)
            async with scope_service.round_trip_payload_scope(
                session_factory=session_factory, session_id=request.session_id
            ) as round_trip_message_ids:
                persisted = persist(
                    raw_events,
                    session_id=request.session_id,
                    session_factory=session_factory,
                    round_trip_message_ids=round_trip_message_ids,
                )
                observed = observe(
                    persisted,
                    session_id=request.session_id,
                    trigger_message_id=user_message_id,
                    effort=request.effort,
                    protocol=resolved.profile.protocol,
                    key_source=resolved.key_source,
                    retention_window=projection.retention_window,
                    run_attributes=projection.attributes,
                    session_factory=session_factory,
                )
                async for frame in encode_sse(
                    observed, session_id=request.session_id, run_id=run_id
                ):
                    yield frame
        finally:
            await http_client.aclose()

    return EventSourceResponse(stream())


async def _title_model_call(
    port: ModelPort, *, text: str, model: str, profile: EndpointProfile
) -> tuple[str | None, Usage | None, str | None]:
    completed: ModelCallCompleted | None = None
    try:
        async with asyncio.timeout(_TITLE_TIMEOUT_SECONDS):
            async for event in port.stream(
                messages=[ModelMessage(role="user", content=(TextBlock(text=text),))],
                tools=[],
                model=model,
                effort="low",
                profile=profile,
                system_prompt=TITLE_PROMPT_TEMPLATE,
            ):
                if isinstance(event, ModelCallCompleted):
                    completed = event
    except TimeoutError:
        return None, completed.usage if completed is not None else None, "timeout"
    except asyncio.CancelledError:
        raise
    except Exception:
        return None, completed.usage if completed is not None else None, "upstream"
    if completed is None:
        return None, None, "missing_terminal"
    generated = " ".join(
        "".join(block.text for block in completed.message.content if isinstance(block, TextBlock))
        .strip()
        .split()
    )
    if not generated:
        return None, completed.usage, "empty_output"
    return generated[:MAX_TITLE_LENGTH], completed.usage, None


async def _title_call_until_disconnect(
    request: Request, port: ModelPort, *, text: str, model: str, profile: EndpointProfile
) -> tuple[str | None, Usage | None, str | None]:
    async def watch_disconnect() -> None:
        while True:
            if (await request.receive())["type"] == "http.disconnect":
                return

    model_task = asyncio.create_task(
        _title_model_call(port, text=text, model=model, profile=profile)
    )
    disconnect_task = asyncio.create_task(watch_disconnect())
    try:
        done, _ = await asyncio.wait(
            {model_task, disconnect_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if model_task in done:
            return await model_task
        model_task.cancel()
        await asyncio.gather(model_task, return_exceptions=True)
        raise asyncio.CancelledError
    finally:
        disconnect_task.cancel()
        model_task.cancel()
        await asyncio.gather(disconnect_task, model_task, return_exceptions=True)


@app.post(
    "/api/sessions/{session_id}/title",
    response_model=TitleGenerationResponse,
    tags=["sessions"],
)
async def generate_session_title(
    session_id: UUID,
    payload: TitleGenerationRequest,
    request: Request,
    port_factory: Annotated[
        Callable[[EndpointProfile], ModelPort] | None,
        Depends(get_title_model_port_factory),
    ],
) -> TitleGenerationResponse:
    session_factory = get_session_factory()
    service = object.__new__(ConversationService)
    claim = await service.short_transaction_claim_title_generation(
        session_factory=session_factory, session_id=session_id
    )
    if claim is None:
        raise SessionNotFound(f"Session {session_id} was not found")
    if not claim.claimed:
        return TitleGenerationResponse(
            session_id=session_id, title=claim.title, status=claim.status
        )

    span_id = uuid5(session_id, "title_generation")
    writer = RunWriter(session_factory=session_factory)
    usage: Usage | None = None
    failure_reason: str | None = None
    generated_title: str | None = None
    resolved: ResolvedProfiles | None = None
    span_open = False
    try:
        try:
            server_config = load_server_endpoints(Settings().endpoints_config_path)
            resolved = resolve_profiles(server_config, payload.model_override)
        except ProfileUnavailableError:
            failure_reason = "upstream"
        if resolved is not None and claim.source_text:
            try:
                await writer.open_span(
                    span_id=span_id,
                    run_id=None,
                    session_id=session_id,
                    parent_span_id=None,
                    name="title_generation",
                    kind="llm",
                    role="auxiliary",
                    model=resolved.auxiliary_model,
                    attributes={
                        "effort": "low",
                        "protocol": resolved.profile.protocol,
                        "key_source": resolved.key_source,
                        "auxiliary_model_source": resolved.auxiliary_model_source,
                    },
                )
                span_open = True
            except Exception as exc:
                logger.warning("title.observation_failed", error_type=type(exc).__name__)
            async with AsyncExitStack() as stack:
                port = (
                    port_factory(resolved.profile)
                    if port_factory is not None
                    else await stack.enter_async_context(
                        model_port_scope(
                            resolved.profile,
                            shared_client=not (
                                payload.model_override is not None
                                and payload.model_override.is_custom_endpoint
                            ),
                        )
                    )
                )
                generated_title, usage, failure_reason = await _title_call_until_disconnect(
                    request,
                    port,
                    text=claim.source_text,
                    model=resolved.auxiliary_model,
                    profile=resolved.profile,
                )
    except asyncio.CancelledError:
        failure_reason = "cancelled"
    except Exception:
        failure_reason = "upstream"

    outcome = None
    finalization = asyncio.create_task(
        service.short_transaction_finalize_title_generation(
            session_factory=session_factory,
            session_id=session_id,
            generated_title=generated_title,
        )
    )
    try:
        while not finalization.done():
            try:
                await asyncio.shield(finalization)
            except asyncio.CancelledError:
                continue
        outcome = await finalization
    finally:
        if span_open:
            attributes = {
                "effort": "low",
                "protocol": resolved.profile.protocol if resolved else None,
                "key_source": resolved.key_source if resolved else None,
                "auxiliary_model_source": resolved.auxiliary_model_source if resolved else None,
            }
            if failure_reason is not None:
                attributes["failure_reason"] = failure_reason
            if outcome is not None and generated_title is not None:
                attributes["application_result"] = (
                    "deleted_not_applied"
                    if outcome.status == "processed" and outcome.title is None
                    else outcome.status
                )
            try:
                await writer.close_span(
                    span_id=span_id,
                    run_id=None,
                    status="error" if failure_reason is not None else "ok",
                    usage_status=usage.state if usage is not None else "unavailable",
                    input_tokens=usage.input_tokens if usage is not None else None,
                    output_tokens=usage.output_tokens if usage is not None else None,
                    reasoning_tokens=usage.reasoning_tokens if usage is not None else None,
                    attributes=attributes,
                )
            except Exception as exc:
                logger.warning("title.observation_failed", error_type=type(exc).__name__)
    if outcome is None:
        raise SessionNotFound(f"Session {session_id} was not found")
    return TitleGenerationResponse(
        session_id=session_id, title=outcome.title, status=outcome.status
    )
