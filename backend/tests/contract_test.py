"""进程内 Schemathesis 契约门禁。"""

from __future__ import annotations

from copy import deepcopy

import pytest
import schemathesis
from chat_agents.main import app
from hypothesis import seed, settings


@pytest.fixture
def api_schema() -> object:
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
