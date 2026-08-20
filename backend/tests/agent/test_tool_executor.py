import asyncio

import pytest
from chat_agents.agent.tool_execution import RunToolContext
from chat_agents.agent.tool_executor import ToolExecutor, ToolProgramError
from chat_agents.tools.types import ToolExternalFailure, ToolHandler, ToolResult, ToolSpec

_original_sleep = asyncio.sleep


def _ctx() -> RunToolContext:
    return RunToolContext(run_id="run-1", http_client=object())


def _spec(
    handler: ToolHandler,
    *,
    retryable: bool = True,
    timeout_s: float = 1.0,
    parallelizable: bool = True,
) -> ToolSpec:
    return ToolSpec(
        name="fake_tool",
        description="",
        parameters={"type": "object", "properties": {}},
        handler=handler,
        timeout_s=timeout_s,
        retryable=retryable,
        parallelizable=parallelizable,
    )


def test_execute_returns_model_text_on_success():
    async def handler(args, ctx):
        return ToolResult(structured={"ok": True}, model_text="成功")

    executor = ToolExecutor({"fake_tool": _spec(handler)})

    text, structured = asyncio.run(executor.execute("fake_tool", {}, _ctx()))

    assert text == "成功"
    assert structured == {"ok": True}


def test_unregistered_tool_raises_program_error():
    executor = ToolExecutor({})

    with pytest.raises(ToolProgramError):
        asyncio.run(executor.execute("missing", {}, _ctx()))


def test_unexpected_exception_is_a_program_error_not_a_model_result():
    async def handler(args, ctx):
        raise ValueError("bug")

    executor = ToolExecutor({"fake_tool": _spec(handler, retryable=False)})

    with pytest.raises(ToolProgramError):
        asyncio.run(executor.execute("fake_tool", {}, _ctx()))


def test_non_retryable_external_failure_returns_text_without_raising():
    async def handler(args, ctx):
        raise ToolExternalFailure("目标站拒绝", retryable=False)

    executor = ToolExecutor({"fake_tool": _spec(handler, retryable=True)})

    text, structured = asyncio.run(executor.execute("fake_tool", {}, _ctx()))

    assert text == "目标站拒绝"
    assert structured is None


def test_retryable_external_failure_retries_then_returns_text_to_model(monkeypatch):
    attempts = []

    async def handler(args, ctx):
        attempts.append(1)
        if len(attempts) < 3:
            raise ToolExternalFailure("超时", retryable=True)
        return ToolResult(structured={}, model_text="第三次成功")

    executor = ToolExecutor({"fake_tool": _spec(handler, retryable=True)})
    monkeypatch.setattr(asyncio, "sleep", lambda _seconds: _original_sleep(0))

    text, structured = asyncio.run(executor.execute("fake_tool", {}, _ctx()))

    assert len(attempts) == 3
    assert text == "第三次成功"
    assert structured == {}


def test_exhausting_retries_returns_last_failure_text(monkeypatch):
    async def handler(args, ctx):
        raise ToolExternalFailure("一直超时", retryable=True)

    executor = ToolExecutor({"fake_tool": _spec(handler, retryable=True)})
    monkeypatch.setattr(asyncio, "sleep", lambda _seconds: _original_sleep(0))

    text, structured = asyncio.run(executor.execute("fake_tool", {}, _ctx()))

    assert text == "一直超时"
    assert structured is None


def test_non_retryable_spec_only_attempts_once():
    attempts = []

    async def handler(args, ctx):
        attempts.append(1)
        raise ToolExternalFailure("外部失败", retryable=True)

    executor = ToolExecutor({"fake_tool": _spec(handler, retryable=False)})

    asyncio.run(executor.execute("fake_tool", {}, _ctx()))

    assert len(attempts) == 1


def test_timeout_is_classified_as_retryable_external_failure():
    async def handler(args, ctx):
        await asyncio.sleep(10)
        return ToolResult(structured={}, model_text="不会走到这里")

    executor = ToolExecutor({"fake_tool": _spec(handler, retryable=False, timeout_s=0.01)})

    text, structured = asyncio.run(executor.execute("fake_tool", {}, _ctx()))

    assert "超时" in text
    assert structured is None


def test_tool_definitions_expose_only_name_description_parameters():
    async def handler(args, ctx):
        return ToolResult(structured={}, model_text="")

    executor = ToolExecutor({"fake_tool": _spec(handler)})

    definitions = executor.tool_definitions()

    assert definitions == [
        {"name": "fake_tool", "description": "", "parameters": {"type": "object", "properties": {}}}
    ]
