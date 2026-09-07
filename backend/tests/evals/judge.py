"""判官契约与快照配置；不绑定任何模型供应商 SDK。"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from chat_agents.llm.events import ModelCallCompleted
from chat_agents.llm.message import ModelMessage, TextBlock
from chat_agents.llm.port import ModelPort, get_model_port
from chat_agents.llm.profile import EndpointProfile

JUDGE_MODEL_ENV = "EVAL_JUDGE_MODEL"
RELEASE_JUDGE_MODEL_ENV = "EVAL_RELEASE_JUDGE_MODEL"


def judge_snapshot_from_env(*, release: bool = False) -> str:
    """读取本次请求的判官快照；型号只由环境变量或 CI secret 注入。"""

    env_name = RELEASE_JUDGE_MODEL_ENV if release else JUDGE_MODEL_ENV
    snapshot_id = os.environ.get(env_name)
    if not snapshot_id:
        raise RuntimeError(f"{env_name} 未配置")
    return snapshot_id


@dataclass(frozen=True, slots=True)
class JudgeRequest:
    scenario_id: str
    query: str
    answer: str
    observations: str
    expected_answer: str | None


@dataclass(frozen=True, slots=True)
class JudgeScores:
    factual_hallucination_rate: float
    task_completion: float
    snapshot_id: str

    def __post_init__(self) -> None:
        for name, score in (
            ("factual_hallucination_rate", self.factual_hallucination_rate),
            ("task_completion", self.task_completion),
        ):
            if not 0.0 <= score <= 1.0:
                raise ValueError(f"{name} 必须位于 [0, 1]")
        if not self.snapshot_id:
            raise ValueError("判官快照标识不能为空")


ModelPortFactory = Callable[[EndpointProfile], ModelPort]

_JUDGE_SYSTEM_PROMPT = """你是评测判官。只评估最终回答，不评估显示摘要或标题。
根据用户问题、工具观察和可选参考答案，输出严格 JSON 对象，且只包含两个字段：
- factual_hallucination_rate：0 到 1，回答中无工具观察或常识支撑的事实性陈述占比；越低越好。
- task_completion：0 到 1，回答完整解决用户问题的程度；越高越好。
不要输出 Markdown、解释或额外字段。
"""


class ModelPortJudge:
    """经项目既有 ModelPort 调用活判官，协议与供应商保持可替换。"""

    def __init__(
        self,
        *,
        profile: EndpointProfile,
        snapshot_id: str | None = None,
        release: bool = False,
        model_port_factory: ModelPortFactory = get_model_port,
    ) -> None:
        self._profile = profile
        self._snapshot_id = snapshot_id or judge_snapshot_from_env(release=release)
        self._model_port_factory = model_port_factory

    async def evaluate(self, request: JudgeRequest) -> JudgeScores:
        payload = json.dumps(
            {
                "scenario_id": request.scenario_id,
                "query": request.query,
                "answer": request.answer,
                "observations": request.observations,
                "expected_answer": request.expected_answer,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        completed: ModelCallCompleted | None = None
        port = self._model_port_factory(self._profile)
        async for event in port.stream(
            messages=[ModelMessage(role="user", content=(TextBlock(text=payload),))],
            tools=[],
            model=self._snapshot_id,
            effort="low",
            profile=self._profile,
            system_prompt=_JUDGE_SYSTEM_PROMPT,
        ):
            if isinstance(event, ModelCallCompleted):
                completed = event
        if completed is None:
            raise RuntimeError("判官模型调用未产出终态事件")
        text = "".join(
            block.text for block in completed.message.content if isinstance(block, TextBlock)
        )
        return _scores_from_json(text, snapshot_id=self._snapshot_id)


def _scores_from_json(text: str, *, snapshot_id: str) -> JudgeScores:
    try:
        raw: Any = json.loads(text)
        if not isinstance(raw, dict) or set(raw) != {
            "factual_hallucination_rate",
            "task_completion",
        }:
            raise ValueError("字段不匹配")
        hallucination = float(raw["factual_hallucination_rate"])
        completion = float(raw["task_completion"])
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError(f"判官输出不是预期 JSON: {text}") from exc
    return JudgeScores(
        factual_hallucination_rate=hallucination,
        task_completion=completion,
        snapshot_id=snapshot_id,
    )


class JudgePort(Protocol):
    async def evaluate(self, request: JudgeRequest) -> JudgeScores: ...
