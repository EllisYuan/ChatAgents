import math

import pytest
from chat_agents.token_estimation import (
    UsageSample,
    compute_calibration_factors,
    count_tokens,
    estimate_tokens,
)


def test_count_tokens_is_pure_and_deterministic():
    assert count_tokens("hello world") == count_tokens("hello world")
    assert count_tokens("") == 0


def test_count_tokens_treats_cjk_as_one_char_one_token():
    assert count_tokens("你好世界") == 4


def test_count_tokens_treats_latin_as_four_chars_one_token():
    assert count_tokens("abcd") == 1
    assert count_tokens("abcde") == 2


def test_estimate_tokens_with_default_calibration_matches_raw_count():
    text = "hello world 你好"
    assert estimate_tokens(text) == count_tokens(text)


def test_estimate_tokens_applies_calibration_factor():
    text = "abcd" * 100  # 100 tokens raw

    assert estimate_tokens(text, calibration=1.2) == math.ceil(count_tokens(text) * 1.2)
    assert estimate_tokens(text, calibration=0.5) == math.ceil(count_tokens(text) * 0.5)


def test_estimate_tokens_rejects_nonpositive_calibration():
    with pytest.raises(ValueError):
        estimate_tokens("text", calibration=0)
    with pytest.raises(ValueError):
        estimate_tokens("text", calibration=-1)


def test_compute_calibration_factors_averages_per_model():
    samples = [
        UsageSample(model="a", estimated_tokens=100, actual_tokens=110),
        UsageSample(model="a", estimated_tokens=200, actual_tokens=180),
        UsageSample(model="b", estimated_tokens=100, actual_tokens=130),
    ]

    factors = compute_calibration_factors(samples)

    assert factors["a"] == pytest.approx((1.1 + 0.9) / 2)
    assert factors["b"] == pytest.approx(1.3)


def test_compute_calibration_factors_skips_zero_estimate_samples():
    samples = [
        UsageSample(model="a", estimated_tokens=0, actual_tokens=10),
        UsageSample(model="a", estimated_tokens=100, actual_tokens=100),
    ]

    factors = compute_calibration_factors(samples)

    assert factors["a"] == pytest.approx(1.0)


def test_compute_calibration_factors_returns_empty_for_no_samples():
    assert compute_calibration_factors([]) == {}
