"""独立标题 HTTP 请求的断连传播与任务回收（issue #93）。"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
import pytest
import uvicorn
from chat_agents import main as main_module
from chat_agents.conversation.repository import ConversationRepository
from chat_agents.conversation.service import ConversationService
from chat_agents.db.obs import Span
from chat_agents.llm import port as port_module
from chat_agents.llm.events import ModelCallCompleted, ModelEvent, Usage
from chat_agents.llm.message import ModelMessage, TextBlock
from chat_agents.llm.override import ModelOverride
from chat_agents.llm.profile import EndpointProfile
from chat_agents.observability.repository import ObservabilityRepository
from chat_agents.observability.writer import RunWriter
from sqlalchemy import select

from .db_helpers import migrated_engine, session_factory_for


class _Port:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def stream(self, **kwargs: Any) -> AsyncIterator[ModelEvent]:
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        yield ModelCallCompleted(
            message=ModelMessage(role="assistant", content=(TextBlock(text="标题"),)),
            usage=Usage(state="complete", input_tokens=2, output_tokens=1, reasoning_tokens=None),
            stop_reason="stop",
        )


class _Request:
    def __init__(self) -> None:
        self.disconnected = asyncio.Event()

    async def receive(self) -> dict[str, str]:
        await self.disconnected.wait()
        return {"type": "http.disconnect"}


@pytest.mark.db
def test_title_disconnect_cancels_model_and_keeps_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_disconnect") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)
            session_id = uuid4()
            async with factory() as session, session.begin():
                await ConversationService(session).append_user_message_with_title_candidate(
                    session_id=session_id, message_id=uuid4(), text="首条消息"
                )
            port = _Port()
            request = _Request()
            title_task = asyncio.create_task(
                main_module.generate_session_title(
                    session_id,
                    main_module.TitleGenerationRequest(),
                    request,
                    lambda _profile: port,
                )
            )
            try:
                await asyncio.wait_for(port.started.wait(), timeout=3)
                request.disconnected.set()
                response = await asyncio.wait_for(title_task, timeout=3)
                assert response.status == "fallback"
                assert response.title == "首条消息"
                assert port.cancelled.is_set()
                async with factory() as session:
                    row = await ConversationRepository(session).get_session(session_id)
                    assert row is not None
                    assert row.title == "首条消息"
                    assert row.title_generation_outcome == "fallback"
                    assert row.title_generation_eligible is False
                    observation = await ObservabilityRepository(session).get_title_generation(
                        session_id
                    )
                    assert len(observation.spans) == 1
                    span = observation.spans[0]
                    assert span.status == "error"
                    assert span.failure_reason == "cancelled"
                    assert span.usage_status == "unavailable"
                    assert span.input_tokens is None
                    assert span.output_tokens is None
                    assert span.reasoning_tokens is None
                repeated = await main_module.generate_session_title(
                    session_id,
                    main_module.TitleGenerationRequest(),
                    _Request(),
                    lambda _profile: port,
                )
                assert repeated.status == "fallback"
                assert repeated.title == "首条消息"
            finally:
                port.release.set()
                title_task.cancel()
                await asyncio.gather(title_task, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.db
def test_completed_model_wins_a_simultaneous_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_simultaneous_disconnect") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)
            session_id = uuid4()
            async with factory() as session, session.begin():
                await ConversationService(session).append_user_message_with_title_candidate(
                    session_id=session_id, message_id=uuid4(), text="首条消息"
                )
            port = _Port()
            port.release.set()
            request = _Request()
            request.disconnected.set()
            response = await asyncio.wait_for(
                main_module.generate_session_title(
                    session_id, main_module.TitleGenerationRequest(), request, lambda _profile: port
                ),
                timeout=3,
            )
            assert response.status == "applied"
            assert response.title == "标题"
            async with factory() as session:
                observation = await ObservabilityRepository(session).get_title_generation(
                    session_id
                )
                span = observation.spans[0]
                assert span.status == "ok"
                assert span.usage_status == "complete"
                assert span.input_tokens == 2
                assert span.output_tokens == 1
                assert span.application_result == "applied"
                assert span.failure_reason is None

    asyncio.run(scenario())


@pytest.mark.db
def test_upstream_interruption_preserves_available_partial_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    class InterruptedPort:
        async def stream(self, **kwargs: Any) -> AsyncIterator[ModelEvent]:
            yield ModelCallCompleted(
                message=ModelMessage(role="assistant", content=(TextBlock(text="未完成"),)),
                usage=Usage(
                    state="partial", input_tokens=25, output_tokens=None, reasoning_tokens=None
                ),
                stop_reason="interrupted",
            )
            raise RuntimeError("上游流中断")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_partial_usage") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)
            session_id = uuid4()
            async with factory() as session, session.begin():
                await ConversationService(session).append_user_message_with_title_candidate(
                    session_id=session_id, message_id=uuid4(), text="首条消息"
                )
            response = await main_module.generate_session_title(
                session_id,
                main_module.TitleGenerationRequest(),
                _Request(),
                lambda _profile: InterruptedPort(),
            )
            assert response.status == "fallback"
            async with factory() as session:
                observation = await ObservabilityRepository(session).get_title_generation(
                    session_id
                )
                span = observation.spans[0]
                assert span.status == "error"
                assert span.failure_reason == "upstream"
                assert span.usage_status == "partial"
                assert span.input_tokens == 25
                assert span.output_tokens is None
                row = await ConversationRepository(session).get_session(session_id)
                assert row is not None
                assert row.title_generation_outcome == "fallback"

    asyncio.run(scenario())


@pytest.mark.db
def test_title_model_completion_does_not_wait_for_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_no_disconnect") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)
            session_id = uuid4()
            async with factory() as session, session.begin():
                await ConversationService(session).append_user_message_with_title_candidate(
                    session_id=session_id, message_id=uuid4(), text="首条消息"
                )
            port = _Port()
            port.release.set()
            response = await asyncio.wait_for(
                main_module.generate_session_title(
                    session_id,
                    main_module.TitleGenerationRequest(),
                    _Request(),
                    lambda _profile: port,
                ),
                timeout=3,
            )
            assert response.status == "applied"
            assert response.title == "标题"

    asyncio.run(scenario())


@pytest.mark.db
def test_real_http_disconnect_cancels_title_model(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    finalized = asyncio.Event()
    observation_closed = asyncio.Event()
    original_close = RunWriter.close_span

    async def close_span_and_signal(self: RunWriter, **kwargs: Any) -> None:
        await original_close(self, **kwargs)
        observation_closed.set()

    monkeypatch.setattr(RunWriter, "close_span", close_span_and_signal)
    original_finalize = ConversationService.short_transaction_finalize_title_generation

    async def finalize_and_signal(self: ConversationService, **kwargs: Any) -> Any:
        outcome = await original_finalize(self, **kwargs)
        finalized.set()
        return outcome

    monkeypatch.setattr(
        ConversationService, "short_transaction_finalize_title_generation", finalize_and_signal
    )

    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_real_disconnect") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)
            session_id = uuid4()
            async with factory() as session, session.begin():
                await ConversationService(session).append_user_message_with_title_candidate(
                    session_id=session_id, message_id=uuid4(), text="首条消息"
                )
            port = _Port()
            closed = asyncio.Event()

            class TrackedClient:
                async def aclose(self) -> None:
                    closed.set()

            monkeypatch.setattr(port_module, "_new_http_client", lambda _profile: TrackedClient())
            monkeypatch.setattr(port_module, "_build_port", lambda _profile, _client: port)
            main_module.app.dependency_overrides[main_module.get_title_model_port_factory] = (
                lambda: None
            )
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen(5)
            host, tcp_port = listener.getsockname()
            server = uvicorn.Server(
                uvicorn.Config(main_module.app, log_level="error", lifespan="off")
            )
            server_task = asyncio.create_task(server.serve(sockets=[listener]))
            try:
                async with httpx.AsyncClient() as client:

                    async def send_title() -> httpx.Response:
                        return await client.post(
                            f"http://{host}:{tcp_port}/api/sessions/{session_id}/title",
                            json={
                                "model_override": {
                                    "protocol": "openai_chat_completions",
                                    "base_url": "https://relay.example.com/v1",
                                    "api_key": "user-key",
                                    "main_model": "test-model",
                                }
                            },
                        )

                    http_task = asyncio.create_task(send_title())
                    try:
                        await asyncio.wait_for(port.started.wait(), timeout=3)
                        http_task.cancel()
                        await asyncio.gather(http_task, return_exceptions=True)
                        await asyncio.wait_for(port.cancelled.wait(), timeout=3)
                        await asyncio.wait_for(closed.wait(), timeout=3)
                        # 断连后服务端仍会把终态写进短事务（shield）；等它提交完再断言，
                        # 不靠固定 sleep。
                        await asyncio.wait_for(finalized.wait(), timeout=3)
                        await asyncio.wait_for(observation_closed.wait(), timeout=3)
                    finally:
                        port.release.set()
                        http_task.cancel()
                        await asyncio.gather(http_task, return_exceptions=True)
                async with factory() as session:
                    row = await ConversationRepository(session).get_session(session_id)
                    assert row is not None
                    assert row.title_generation_outcome == "fallback"
                    observation = await ObservabilityRepository(session).get_title_generation(
                        session_id
                    )
                    assert observation.spans[0].failure_reason == "cancelled"
                    assert observation.spans[0].ended_at is not None
            finally:
                server.should_exit = True
                await asyncio.wait_for(server_task, timeout=5)
                main_module.app.dependency_overrides.pop(
                    main_module.get_title_model_port_factory, None
                )

    asyncio.run(scenario())
    assert not any("Exception in ASGI application" in record.message for record in caplog.records)


@pytest.mark.db
def test_disconnect_during_committed_finalization_preserves_title_and_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    finalized = asyncio.Event()
    release = asyncio.Event()
    original = ConversationService.short_transaction_finalize_title_generation

    async def pause_after_commit(self: ConversationService, **kwargs: Any) -> Any:
        outcome = await original(self, **kwargs)
        finalized.set()
        await release.wait()
        return outcome

    monkeypatch.setattr(
        ConversationService, "short_transaction_finalize_title_generation", pause_after_commit
    )

    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_committed_disconnect") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)
            session_id = uuid4()
            async with factory() as session, session.begin():
                await ConversationService(session).append_user_message_with_title_candidate(
                    session_id=session_id, message_id=uuid4(), text="首条消息"
                )
            port = _Port()
            port.release.set()
            title_task = asyncio.create_task(
                main_module.generate_session_title(
                    session_id,
                    main_module.TitleGenerationRequest(),
                    _Request(),
                    lambda _profile: port,
                )
            )
            try:
                await asyncio.wait_for(finalized.wait(), timeout=3)
                title_task.cancel()
                await asyncio.sleep(0)
                title_task.cancel()
                release.set()
                response = await asyncio.wait_for(title_task, timeout=3)
                assert response.status == "applied"
                assert response.title == "标题"
                async with factory() as session:
                    row = await ConversationRepository(session).get_session(session_id)
                    assert row is not None
                    assert row.title == "标题"
                    assert row.title_generation_outcome == "applied"
                    observation = await ObservabilityRepository(session).get_title_generation(
                        session_id
                    )
                    span = observation.spans[0]
                    assert span.status == "ok"
                    assert span.usage_status == "complete"
                    assert span.input_tokens == 2
                    assert span.output_tokens == 1
                    assert span.application_result == "applied"
                repeated = await main_module.generate_session_title(
                    session_id,
                    main_module.TitleGenerationRequest(),
                    _Request(),
                    lambda _profile: port,
                )
                assert repeated.status == "applied"
                assert repeated.title == "标题"
            finally:
                release.set()
                title_task.cancel()
                await asyncio.gather(title_task, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.db
def test_disconnect_closes_custom_client_and_cancels_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    async def scenario() -> None:
        async with migrated_engine("chat_agents_title_client_close") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)
            session_id = uuid4()
            async with factory() as session, session.begin():
                await ConversationService(session).append_user_message_with_title_candidate(
                    session_id=session_id, message_id=uuid4(), text="首条消息"
                )
            port = _Port()
            closed = asyncio.Event()

            class TrackedClient:
                async def aclose(self) -> None:
                    closed.set()

            def new_client(profile: EndpointProfile) -> TrackedClient:
                return TrackedClient()

            def build_port(profile: EndpointProfile, client: TrackedClient) -> _Port:
                return port

            monkeypatch.setattr(port_module, "_new_http_client", new_client)
            monkeypatch.setattr(port_module, "_build_port", build_port)
            request = _Request()
            title_task = asyncio.create_task(
                main_module.generate_session_title(
                    session_id,
                    main_module.TitleGenerationRequest(
                        model_override=ModelOverride(
                            protocol="openai_chat_completions",
                            base_url="https://relay.example.com/v1",
                            api_key="user-key",
                            main_model="test-model",
                        )
                    ),
                    request,
                    None,
                )
            )
            try:
                await asyncio.wait_for(port.started.wait(), timeout=3)
                request.disconnected.set()
                response = await asyncio.wait_for(title_task, timeout=3)
                assert response.status == "fallback"
                assert port.cancelled.is_set()
                assert closed.is_set()
            finally:
                port.release.set()
                title_task.cancel()
                await asyncio.gather(title_task, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.db
@pytest.mark.parametrize("failed_method", ["open_span", "close_span"])
def test_observation_write_failure_does_not_retry_or_block_title(
    monkeypatch: pytest.MonkeyPatch, failed_method: str
) -> None:
    """观测写入故障不能改变标题业务结果。"""

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    async def fail_span_write(self: RunWriter, **kwargs: Any) -> None:
        raise RuntimeError("observation unavailable")

    monkeypatch.setattr(RunWriter, failed_method, fail_span_write)

    async def scenario() -> None:
        async with migrated_engine(f"chat_agents_title_obs_{failed_method}") as engine:
            factory = session_factory_for(engine)
            monkeypatch.setattr(main_module, "get_session_factory", lambda: factory)
            session_id = uuid4()
            async with factory() as session, session.begin():
                await ConversationService(session).append_user_message_with_title_candidate(
                    session_id=session_id, message_id=uuid4(), text="首条消息"
                )
            port = _Port()
            port.release.set()
            response = await main_module.generate_session_title(
                session_id,
                main_module.TitleGenerationRequest(),
                _Request(),
                lambda _profile: port,
            )
            assert response.status == "applied"
            assert response.title == "标题"
            async with factory() as session:
                row = await ConversationRepository(session).get_session(session_id)
                assert row is not None
                assert row.title == "标题"
                assert row.title_generation_outcome == "applied"
                spans = (await session.execute(select(Span))).scalars().all()
                if failed_method == "open_span":
                    assert spans == []
                else:
                    assert len(spans) == 1
                    assert spans[0].ended_at is None

    asyncio.run(scenario())
