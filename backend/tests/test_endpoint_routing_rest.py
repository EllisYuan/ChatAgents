"""自定义端点的 REST → 真实 SDK → HTTP → SSE / 持久化回归。"""

import asyncio
import json
from uuid import uuid4

import httpx
import pytest
from chat_agents import main as main_module
from chat_agents.db.app import DiscoveredModel, Message, Session
from chat_agents.db.obs import Run, Span
from sqlalchemy import select

from .db_helpers import migrated_engine, session_factory_for
from .endpoint_gateway import ANSWER, API_KEY, AUXILIARY_MODEL, MODEL, endpoint_gateway


@pytest.mark.db
@pytest.mark.parametrize(
    ("base_path", "full_url", "prefix"),
    [
        # 用户填根地址：自动补 /v1（issue #83 的这一轮诉求）。
        ("", None, "/v1"),
        ("/v1", False, "/v1"),
        # 完整 URL：填的就是最终生成地址，清单从同一前缀推出。
        ("/v1/chat/completions", True, "/v1"),
    ],
)
def test_custom_endpoint_discovery_and_run_share_one_address(
    monkeypatch: pytest.MonkeyPatch,
    base_path: str,
    full_url: bool | None,
    prefix: str,
) -> None:
    async def scenario() -> None:
        async with migrated_engine("chat_agents_endpoint_routing") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)
            with endpoint_gateway(
                {
                    ("GET", "/v1/models"): None,
                    ("POST", "/v1/chat/completions"): "openai_chat_completions",
                }
            ) as gateway:
                endpoint: dict[str, object] = {
                    "protocol": "openai_chat_completions",
                    "base_url": gateway.origin + base_path,
                    "auth_field": "Authorization",
                    "api_key": API_KEY,
                }
                if full_url is not None:
                    endpoint["full_url"] = full_url
                session_id = uuid4()
                transport = httpx.ASGITransport(app=main_module.app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    refresh = await client.post("/api/models/refresh", json=endpoint)
                    assert refresh.status_code == 200
                    assert refresh.json()["source"] == "discovered"
                    response = await client.post(
                        "/api/runs",
                        json={
                            "session_id": str(session_id),
                            "message": "hi",
                            "effort": "medium",
                            "model_override": {
                                **endpoint,
                                "main_model": MODEL,
                                "auxiliary_model": AUXILIARY_MODEL,
                            },
                        },
                    )
                    assert response.status_code == 200
                    frames = [
                        json.loads(line.removeprefix("data: "))
                        for line in response.text.splitlines()
                        if line.startswith("data: ")
                    ]

                types = [frame["type"] for frame in frames]
                assert "RUN_FINISHED" in types
                assert "RUN_ERROR" not in types
                assert "TEXT_MESSAGE_CONTENT" in types

                assert gateway.requests[0] == ("GET", prefix + "/models", None)
                assert sorted(gateway.requests[1:]) == sorted(
                    [
                        ("POST", prefix + "/chat/completions", MODEL),
                        ("POST", prefix + "/chat/completions", AUXILIARY_MODEL),
                    ]
                )
                async with factory() as session:
                    messages = (
                        (await session.execute(select(Message).order_by(Message.seq)))
                        .scalars()
                        .all()
                    )
                    assert [row.role for row in messages] == ["user", "assistant"]
                    run = (await session.execute(select(Run))).scalar_one()
                    assert run.status == "completed"
                    spans = (await session.execute(select(Span))).scalars().all()
                    assert len(spans) == 2
                    assert {span.role: span.model for span in spans} == {
                        "main": MODEL,
                        "auxiliary": AUXILIARY_MODEL,
                    }
                    assert {span.status for span in spans} == {"ok"}
                    for span in spans:
                        assert span.attributes["protocol"] == "openai_chat_completions"
                        assert span.attributes["key_source"] == "user_provided"
                    assert ANSWER in json.dumps(messages[1].content)
                    saved_session = await session.get(Session, session_id)
                    assert saved_session is not None and saved_session.title == ANSWER
                    assert (await session.execute(select(DiscoveredModel))).scalars().all() == []
                    for entity in (Session, Message, Run, Span):
                        rows = (await session.execute(select(entity.__table__))).mappings().all()
                        serialized = json.dumps([dict(row) for row in rows], default=str)
                        assert API_KEY not in serialized
                        assert gateway.origin not in serialized

    asyncio.run(scenario())


@pytest.mark.db
def test_a_wrong_custom_address_still_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    """自动补全不是「怎么填都能跑」：地址真错时仍按 ADR-0015 原样透传上游 404。"""

    async def scenario() -> None:
        async with migrated_engine("chat_agents_endpoint_routing_error") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)
            with endpoint_gateway(
                {("POST", "/v1/chat/completions"): "openai_chat_completions"}
            ) as gateway:
                endpoint = {
                    "protocol": "openai_chat_completions",
                    "base_url": gateway.origin + "/wrong-prefix",
                    "auth_field": "Authorization",
                    "api_key": API_KEY,
                }
                transport = httpx.ASGITransport(app=main_module.app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    refresh = await client.post("/api/models/refresh", json=endpoint)
                    assert refresh.json()["source"] == "fallback"
                    response = await client.post(
                        "/api/runs",
                        json={
                            "session_id": str(uuid4()),
                            "message": "hi",
                            "model_override": {**endpoint, "main_model": MODEL},
                        },
                    )
                    frames = [
                        json.loads(line.removeprefix("data: "))
                        for line in response.text.splitlines()
                        if line.startswith("data: ")
                    ]

                errors = [frame for frame in frames if frame["type"] == "RUN_ERROR"]
                assert len(errors) == 1
                assert errors[0]["message"] == "Error code: 404"
                assert gateway.requests[0] == ("GET", "/wrong-prefix/models", None)
                async with factory() as session:
                    run = (await session.execute(select(Run))).scalar_one()
                    assert run.status == "failed"

    asyncio.run(scenario())


@pytest.mark.db
def test_an_opaque_full_url_runs_but_reports_no_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """完整 URL 指向非标准路径：生成照常，清单如实说推不出来且不试探。"""

    async def scenario() -> None:
        async with migrated_engine("chat_agents_endpoint_routing_opaque") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)
            with endpoint_gateway(
                {("POST", "/custom/infer"): "openai_chat_completions"}
            ) as gateway:
                endpoint = {
                    "protocol": "openai_chat_completions",
                    "base_url": gateway.origin + "/custom/infer",
                    "auth_field": "Authorization",
                    "api_key": API_KEY,
                    "full_url": True,
                }
                transport = httpx.ASGITransport(app=main_module.app)
                async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                    refresh = await client.post("/api/models/refresh", json=endpoint)
                    body = refresh.json()
                    assert body["source"] == "fallback"
                    assert body["models"] == []
                    assert "无法推导模型清单地址" in body["error"]
                    # 推不出清单地址就不发请求，这一步必须零 HTTP。
                    assert gateway.requests == []

                    response = await client.post(
                        "/api/runs",
                        json={
                            "session_id": str(uuid4()),
                            "message": "hi",
                            "model_override": {**endpoint, "main_model": MODEL},
                        },
                    )
                    types = [
                        json.loads(line.removeprefix("data: "))["type"]
                        for line in response.text.splitlines()
                        if line.startswith("data: ")
                    ]

                assert "RUN_FINISHED" in types
                assert "RUN_ERROR" not in types
                assert [request[1] for request in gateway.requests] == ["/custom/infer"] * 2
                async with factory() as session:
                    run = (await session.execute(select(Run))).scalar_one()
                    assert run.status == "completed"

    asyncio.run(scenario())
