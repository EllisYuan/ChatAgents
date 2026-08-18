"""评测 CI 触发、配额与 release 网格的行为。"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from .ci import (
    CI_CASES_PER_EFFORT,
    CI_EFFORTS,
    ModelInputHashes,
    model_input_changes,
    release_retention_windows,
    validate_ci_cases,
    validate_ci_configuration,
)

pytestmark = pytest.mark.eval


@dataclass(frozen=True)
class _Case:
    effort: str


def test_model_input_changes_compare_content_hash_not_names_only() -> None:
    baseline = ModelInputHashes(
        prompts={"system": "same", "title": "old-title"},
        tool_schemas={("tools", "low"): "old-tools"},
    )
    current = ModelInputHashes(
        prompts={"system": "same", "title": "new-title"},
        tool_schemas={("tools", "low"): "new-tools"},
    )

    changes = model_input_changes(current, baseline)

    assert [change.label for change in changes] == ["prompt:title", "tool_schema:tools:low"]
    assert changes[0].baseline_hash == "old-title"
    assert changes[1].current_hash == "new-tools"


def test_removed_model_input_is_a_change() -> None:
    baseline = ModelInputHashes(
        prompts={"system": "same", "title": "removed"},
        tool_schemas={("tools", "low"): "removed"},
    )
    current = ModelInputHashes(
        prompts={"system": "same"},
        tool_schemas={},
    )

    changes = model_input_changes(current, baseline)

    assert [change.label for change in changes] == ["prompt:title", "tool_schema:tools:low"]
    assert all(change.current_hash is None for change in changes)


def test_missing_baseline_hash_is_a_change() -> None:
    current = ModelInputHashes(
        prompts={"system": "current"},
        tool_schemas={("tools", "xhigh"): "current-tools"},
    )

    changes = model_input_changes(
        current,
        ModelInputHashes(prompts={}, tool_schemas={}),
    )

    assert {change.label for change in changes} == {
        "prompt:system",
        "tool_schema:tools:xhigh",
    }
    assert all(change.baseline_hash is None for change in changes)


def test_ci_batch_requires_eight_cases_for_each_effort() -> None:
    cases = [_Case(effort) for effort in CI_EFFORTS for _ in range(CI_CASES_PER_EFFORT)]

    validate_ci_cases(cases, effort_of=lambda case: case.effort)

    with pytest.raises(ValueError, match="每档 8 条"):
        validate_ci_cases(cases[:-1], effort_of=lambda case: case.effort)


def test_release_grid_has_only_the_declared_retention_windows() -> None:
    assert release_retention_windows() == (1, 2, 3, 5, 8)
    validate_ci_configuration(cases_per_effort=8, total_cases=32, retention_window=5)

    with pytest.raises(ValueError, match="8×4=32"):
        validate_ci_configuration(cases_per_effort=7, total_cases=32)
    with pytest.raises(ValueError, match="未知保留窗口"):
        validate_ci_configuration(cases_per_effort=8, total_cases=32, retention_window=4)
