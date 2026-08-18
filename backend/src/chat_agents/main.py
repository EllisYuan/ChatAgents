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

from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

import httpx
import structlog
from fastapi import Depends, FastAPI, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from .agent.runner import AgentRunner
from .conversation.router import router as conversation_router
from .conversation.service import ConversationService
from .conversation.streaming import persist
from .database import get_session_factory
from .error_codes import error_code, http_status
from .exceptions import AuthenticationFailed, ChatAgentsError, ProtocolError
from .llm.effort import EffortTier
from .llm.errors import ProfileUnavailableError
from .llm.resolve import resolve_profiles
from .llm.server_config import load_server_endpoints
from .llm.settings import Settings
from .logging_config import configure_logging
from .observability.streaming import observe
from .transport.custom_events import SpanPayload, ToolResultPayload, UsagePayload
from .transport.sse import encode_sse

configure_logging()
logger = structlog.get_logger(__name__)

app = FastAPI(title="ChatAgents")
app.include_router(conversation_router)


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
    ):
        schemas[name] = model.model_json_schema(ref_template="#/components/schemas/{model}")
    app.openapi_schema = schema
    return schema


app.openapi = _custom_openapi


class RunRequest(BaseModel):
    """``POST /api/runs`` 的最小请求体（本票范围内，见 execution-plan #59）。

    只支持服务端默认档案，不吃 BYOK/自定义端点覆盖——那是 REST 契约票 #59
    的范围，这里先打通「一条 POST 端点跑通完整流式运行」这条链路。
    """

    session_id: UUID
    message: str
    effort: EffortTier = "medium"


def _problem_response(exc: ChatAgentsError) -> JSONResponse:
    """RFC 9457：``type`` 与流后 ``RUN_ERROR.code`` 共用同一份错误码表。"""

    return JSONResponse(
        status_code=http_status(exc),
        content={
            "type": error_code(exc),
            "title": type(exc).__name__,
            "detail": str(exc),
            "status": http_status(exc),
        },
        media_type="application/problem+json",
    )


@app.exception_handler(ChatAgentsError)
async def _domain_error_handler(request: Request, exc: ChatAgentsError) -> JSONResponse:
    del request
    return _problem_response(exc)


@app.get("/health")
async def health() -> dict[str, Literal["ok"]]:
    return {"status": "ok"}


def get_agent_runner() -> AgentRunner:
    """默认用真实 ``ModelPort`` 的 Runner——测试用 ``app.dependency_overrides`` 换假端口。"""

    return AgentRunner()


@app.post("/api/runs")
async def create_run(
    request: RunRequest, runner: Annotated[AgentRunner, Depends(get_agent_runner)]
) -> EventSourceResponse:
    if not request.message.strip():
        raise ProtocolError("User message must not be empty")

    session_factory = get_session_factory()
    settings = Settings()

    try:
        server_config = load_server_endpoints(settings.endpoints_config_path)
        resolved = resolve_profiles(server_config)
    except ProfileUnavailableError as exc:
        # 密钥未配置——运行时错误，不是启动期结构错误（llm/errors.py 的 docstring）。
        raise AuthenticationFailed(str(exc)) from exc

    user_message_id = uuid4()
    async with session_factory() as session, session.begin():
        service = ConversationService(session)
        await service.append_user_message(
            session_id=request.session_id, message_id=user_message_id, text=request.message
        )

    async with session_factory() as session:
        messages = await ConversationService(session).rebuild_model_input(request.session_id)

    run_id = str(uuid4())
    http_client = httpx.AsyncClient()

    async def stream() -> AsyncIterator[str]:
        try:
            raw_events = runner.run(
                messages,
                profile=resolved.profile,
                main_model=resolved.main_model,
                auxiliary_model=resolved.auxiliary_model,
                effort=request.effort,
                http_client=http_client,
                run_id=run_id,
            )
            persisted = persist(
                raw_events, session_id=request.session_id, session_factory=session_factory
            )
            observed = observe(
                persisted,
                session_id=request.session_id,
                trigger_message_id=user_message_id,
                effort=request.effort,
                model=resolved.main_model,
                session_factory=session_factory,
            )
            async for frame in encode_sse(
                observed,
                session_id=request.session_id,
                run_id=run_id,
                model=resolved.main_model,
            ):
                yield frame
        finally:
            await http_client.aclose()

    return EventSourceResponse(stream())
