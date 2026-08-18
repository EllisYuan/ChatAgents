"""测试命令行选项。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from chat_agents.llm.port import ModelPort
from chat_agents.llm.replay import RecordingModelPort


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--record",
        action="store_true",
        default=False,
        help="允许真实上游测试写出 ModelPort replay 录制物",
    )
    parser.addoption(
        "--eval-retention-window",
        type=int,
        default=None,
        help="release 评测使用的观察保留窗口",
    )


@pytest.fixture
def record_mode(request: pytest.FixtureRequest) -> bool:
    """返回当前测试是否显式请求录制模式。"""

    return bool(request.config.getoption("--record"))


@pytest.fixture
def record_model_port(
    request: pytest.FixtureRequest, record_mode: bool
) -> Callable[[ModelPort, str], RecordingModelPort]:
    """包裹 ModelPort，并在 ``--record`` 下写出一个不可覆盖的 fixture。"""

    def wrap(delegate: ModelPort, fixture_name: str) -> RecordingModelPort:
        recorder = RecordingModelPort(delegate)
        if not record_mode:
            return recorder
        path = Path(__file__).parent / "fixtures" / "replay" / f"{fixture_name}.json"
        if path.exists():
            raise RuntimeError(f"拒绝覆盖已有 replay fixture: {path}")

        def save() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            recorder.save(path)

        request.addfinalizer(save)
        return recorder

    return wrap
