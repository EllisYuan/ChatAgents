"""测试命令行选项。"""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--record",
        action="store_true",
        default=False,
        help="允许真实上游测试写出 ModelPort replay 录制物",
    )


@pytest.fixture
def record_mode(request: pytest.FixtureRequest) -> bool:
    """返回当前测试是否显式请求录制模式。"""

    return bool(request.config.getoption("--record"))
