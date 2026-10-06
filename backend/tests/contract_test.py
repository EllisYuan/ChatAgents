"""进程内 Schemathesis 契约门禁。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy

import pytest
import schemathesis
from chat_agents import main as main_module
from chat_agents.agent.versioning import build_prompt_versions, build_tool_schema_versions
from chat_agents.main import app
from hypothesis import seed, settings


@pytest.fixture
def api_schema(monkeypatch: pytest.MonkeyPatch) -> object:
    monkeypatch.setenv("CHATAGENTS_MODEL_DISCOVERY_ENABLED", "false")

    @asynccontextmanager
    async def fixed_versions(_factory: object) -> AsyncIterator[tuple[list[object], list[object]]]:
        yield build_prompt_versions(), build_tool_schema_versions()

    monkeypatch.setattr(main_module, "model_input_version_lifespan", fixed_versions)
    document = deepcopy(app.openapi())
    document["paths"] = {"/health": document["paths"]["/health"]}
    schema = schemathesis.openapi.from_dict(document)
    schema.app = app
    return schema


# 只在契约门禁中跑非流式健康端点；完整 REST 运行由带真 Postgres 的 CI job 执行。
schema = schemathesis.pytest.from_fixture("api_schema")


@schema.parametrize()
@pytest.mark.contract
@settings(max_examples=5, database=None)
@seed(59)
def test_health_conforms_to_openapi(case: schemathesis.Case) -> None:
    response = case.call()
    case.validate_response(response)
