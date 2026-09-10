"""地址解析规则——与前端预览共用 `tests/fixtures/endpoint_address_cases.json`。"""

import json
from pathlib import Path
from typing import Any

import pytest
from chat_agents.llm.endpoint_address import AddressMode, resolve_endpoint_address
from chat_agents.llm.protocol import Protocol

ORIGIN = "https://relay.example.com"
CASES: list[dict[str, Any]] = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "endpoint_address_cases.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize(
    "case", CASES, ids=lambda case: f"{case['mode']}-{case['protocol']}-{case['path'] or 'root'}"
)
def test_shared_address_cases(case: dict[str, Any]) -> None:
    mode: AddressMode = case["mode"]
    protocol: Protocol = case["protocol"]

    resolved = resolve_endpoint_address(ORIGIN + case["path"], protocol=protocol, mode=mode)

    assert resolved.generation_url == ORIGIN + case["generation"]
    if case["discovery"] is None:
        assert resolved.discovery_url is None
        assert resolved.discovery_unavailable_reason is not None
    else:
        assert resolved.discovery_url == ORIGIN + case["discovery"]
        assert resolved.discovery_unavailable_reason is None


@pytest.mark.parametrize("mode", ["sdk_native", "auto", "full"])
def test_sdk_base_lets_the_sdk_reach_the_generation_url(mode: AddressMode) -> None:
    """SDK 构造 base 必须与最终 URL 同源；full 模式由请求钩子改写路径。"""

    resolved = resolve_endpoint_address(f"{ORIGIN}/v1", protocol="openai_responses", mode=mode)

    assert resolved.sdk_base_url.startswith(ORIGIN)
    assert resolved.generation_url.startswith(ORIGIN)


@pytest.mark.parametrize(
    "value", [f"{ORIGIN}/v1?token=private-marker", f"{ORIGIN}/v1#private-marker"]
)
def test_invalid_urls_are_rejected_without_echoing_the_input(value: str) -> None:
    with pytest.raises(ValueError) as error:
        resolve_endpoint_address(value, protocol="openai_responses", mode="auto")
    assert "private-marker" not in str(error.value)
