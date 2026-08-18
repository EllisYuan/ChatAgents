"""ModelPort 边界的录制与回放测试。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

from chat_agents.agent.runner import AgentRunner
from chat_agents.llm.effort import EffortTier
from chat_agents.llm.events import ModelCallCompleted, ModelEvent, TextDelta, Usage
from chat_agents.llm.message import ModelMessage, TextBlock
from chat_agents.llm.profile import EndpointProfile
from chat_agents.llm.replay import (
    RecordingModelPort,
    ReplayModelPort,
    canonical_json_bytes,
    deterministic_run_id,
)
from pydantic import SecretStr


def _profile() -> EndpointProfile:
    return EndpointProfile(
        name="test",
        protocol="anthropic_messages",
        base_url="https://example.com",
        auth_field="Authorization",
        api_key=SecretStr("sk-test"),
    )


def _events(text: str, input_tokens: int) -> tuple[ModelEvent, ...]:
    return (
        TextDelta(text=text),
        ModelCallCompleted(
            message=ModelMessage(role="assistant", content=(TextBlock(text=text),)),
            usage=Usage(
                state="complete",
                input_tokens=input_tokens,
                output_tokens=3,
                reasoning_tokens=2,
            ),
            stop_reason="end_turn",
        ),
    )


class ScriptedPort:
    def __init__(self, turns: Sequence[Sequence[ModelEvent]]) -> None:
        self.turns = [tuple(turn) for turn in turns]
        self.calls = 0

    async def stream(
        self,
        *,
        messages: Sequence[ModelMessage],
        tools: Sequence[Any],
        model: str,
        effort: EffortTier,
        profile: EndpointProfile,
    ) -> AsyncIterator[ModelEvent]:
        del messages, tools, model, effort, profile
        turn = self.turns[self.calls]
        self.calls += 1
        for event in turn:
            yield event


def _run(port: Any, text: str = "hello") -> list[ModelEvent]:
    async def collect() -> list[ModelEvent]:
        return [
            event
            async for event in port.stream(
                messages=[ModelMessage(role="user", content=(TextBlock(text=text),))],
                tools=[],
                model="model-a",
                effort="medium",
                profile=_profile(),
            )
        ]

    return asyncio.run(collect())


def test_recording_round_trip_preserves_events_and_input_tokens(tmp_path: Path) -> None:
    source = ScriptedPort([_events("answer", 123)])
    recording = RecordingModelPort(source)

    assert _run(recording) == list(_events("answer", 123))
    path = tmp_path / "answer.json"
    recording.save(path)

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1
    assert raw["turns"][0]["events"][-1]["usage"]["input_tokens"] == 123

    replay = ReplayModelPort.load(path)
    assert _run(replay) == list(_events("answer", 123))


def test_same_recording_has_byte_identical_canonical_output(tmp_path: Path) -> None:
    first = RecordingModelPort(ScriptedPort([_events("answer", 123)]))
    second = RecordingModelPort(ScriptedPort([_events("answer", 123)]))
    _run(first)
    _run(second)

    assert first.to_bytes() == second.to_bytes()
    assert first.to_bytes() == canonical_json_bytes(json.loads(first.to_bytes()))


def test_replay_rejects_different_input_instead_of_returning_wrong_turn() -> None:
    recording = RecordingModelPort(ScriptedPort([_events("answer", 123)]))
    _run(recording, text="hello")

    replay = ReplayModelPort.from_bytes(recording.to_bytes())
    try:
        _run(replay, text="different")
    except ValueError as exc:
        assert "回放输入不匹配" in str(exc)
    else:
        raise AssertionError("不同输入不应静默消费录制物")


def test_replay_rejects_usage_without_input_tokens() -> None:
    recording = RecordingModelPort(ScriptedPort([_events("answer", 123)]))
    _run(recording)
    raw = json.loads(recording.to_bytes())
    del raw["turns"][0]["events"][-1]["usage"]["input_tokens"]

    try:
        ReplayModelPort.from_bytes(canonical_json_bytes(raw))
    except ValueError as exc:
        assert "input_tokens" in str(exc)
    else:
        raise AssertionError("缺少 input_tokens 的录制物必须被拒绝")


def test_replay_port_drives_runner_with_identical_fixed_run_id() -> None:
    source = RecordingModelPort(ScriptedPort([_events("answer", 123)]))
    messages = [ModelMessage(role="user", content=(TextBlock(text="hello"),))]
    run_id = deterministic_run_id(
        messages=messages,
        tools=[],
        model="model-a",
        effort="medium",
        profile=_profile(),
    )

    async def collect(runner: AgentRunner) -> list[Any]:
        return [
            event
            async for event in runner.run(
                messages,
                profile=_profile(),
                main_model="model-a",
                auxiliary_model="aux-model",
                effort="medium",
                http_client=object(),
                run_id=run_id,
            )
        ]

    source_events = asyncio.run(collect(AgentRunner(model_port_factory=lambda _profile: source)))
    replay = ReplayModelPort.from_bytes(source.to_bytes())
    replay_events = asyncio.run(collect(AgentRunner(model_port_factory=lambda _profile: replay)))

    assert replay_events == source_events
