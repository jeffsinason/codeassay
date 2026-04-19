"""Unit tests for per-commit fingerprint metrics."""

from codeassay.detection.fingerprint import (
    metric_avg_diff_size,
    metric_comment_ratio,
    metric_identifier_entropy,
    metric_punctuation_density,
    metric_message_length,
)


def test_avg_diff_size_single_commit():
    # This metric is a SINGLE commit's diff size — just lines added.
    assert metric_avg_diff_size(lines_added=42) == 42.0


def test_avg_diff_size_zero():
    assert metric_avg_diff_size(lines_added=0) == 0.0


def test_comment_ratio_half():
    added_lines = [
        "# a comment",
        "x = 1",
        "// another comment",
        "y = 2",
    ]
    assert metric_comment_ratio(added_lines) == 0.5


def test_comment_ratio_none():
    assert metric_comment_ratio(["x = 1", "y = 2"]) == 0.0


def test_comment_ratio_empty():
    assert metric_comment_ratio([]) == 0.0


def test_identifier_entropy_uniform_high():
    # Many distinct tokens → high entropy
    added_lines = ["alpha beta gamma delta epsilon", "zeta eta theta iota kappa"]
    e = metric_identifier_entropy(added_lines)
    assert e > 2.0  # natural log of >8 unique tokens


def test_identifier_entropy_repeating_low():
    added_lines = ["foo foo foo foo", "foo foo foo"]
    e = metric_identifier_entropy(added_lines)
    assert e == 0.0  # single token, zero entropy


def test_identifier_entropy_empty():
    assert metric_identifier_entropy([]) == 0.0


def test_punctuation_density_matches():
    msg = "feat: add thing, fix bug. And another."
    d = metric_punctuation_density(msg)
    # 5 punctuation chars (: , . . .) out of ~38 chars → ~0.13
    assert 0.10 < d < 0.18


def test_punctuation_density_empty():
    assert metric_punctuation_density("") == 0.0


def test_message_length():
    assert metric_message_length("hello world") == 11


def test_message_length_empty():
    assert metric_message_length("") == 0


import pytest
from codeassay.detection.fingerprint import (
    Baseline, update_baseline, is_divergent,
)


def test_update_baseline_incremental():
    b = Baseline(mean=0.0, stddev=0.0, sample_size=0)
    b = update_baseline(b, new_value=10.0)
    assert b.sample_size == 1
    assert b.mean == 10.0
    assert b.stddev == 0.0
    b = update_baseline(b, new_value=20.0)
    assert b.sample_size == 2
    assert b.mean == pytest.approx(15.0)
    # Sample stddev of (10, 20) = sqrt(50) ≈ 7.07
    assert b.stddev == pytest.approx(7.07, abs=0.1)


def test_update_baseline_many():
    b = Baseline(mean=0.0, stddev=0.0, sample_size=0)
    for v in [5, 5, 5, 5, 5]:
        b = update_baseline(b, new_value=float(v))
    assert b.mean == 5.0
    assert b.stddev == 0.0  # no variance


def test_is_divergent_above_threshold():
    b = Baseline(mean=100.0, stddev=10.0, sample_size=30)
    assert is_divergent(b, value=125.0, sigma=2.0) is True   # 2.5σ
    assert is_divergent(b, value=115.0, sigma=2.0) is False  # 1.5σ
    assert is_divergent(b, value=75.0, sigma=2.0) is True    # -2.5σ


def test_is_divergent_zero_stddev():
    """With zero variance, any non-matching value is divergent."""
    b = Baseline(mean=5.0, stddev=0.0, sample_size=20)
    assert is_divergent(b, value=5.0, sigma=2.0) is False
    assert is_divergent(b, value=6.0, sigma=2.0) is True


def test_is_divergent_small_sample_returns_false():
    """If sample too small, never divergent (insufficient baseline)."""
    b = Baseline(mean=5.0, stddev=1.0, sample_size=3)
    assert is_divergent(b, value=100.0, sigma=2.0, min_sample=20) is False


from codeassay.detection.fingerprint import classify_by_fingerprint, FingerprintResult


def test_classify_returns_none_if_author_has_no_baseline():
    baselines = {}
    result = classify_by_fingerprint(
        baselines=baselines,
        commit_metrics={"avg_diff_size": 500, "comment_ratio": 0.2,
                        "identifier_entropy": 3.0, "punctuation_density": 0.05,
                        "message_length": 100},
        sigma=2.0, min_divergent=3, min_prior_commits=20,
    )
    assert result is None


def test_classify_none_when_too_few_commits():
    baselines = {
        name: Baseline(mean=100.0, stddev=10.0, sample_size=5)  # below min
        for name in ["avg_diff_size", "comment_ratio", "identifier_entropy",
                     "punctuation_density", "message_length"]
    }
    result = classify_by_fingerprint(
        baselines=baselines,
        commit_metrics={"avg_diff_size": 999, "comment_ratio": 0.99,
                        "identifier_entropy": 999.0, "punctuation_density": 0.99,
                        "message_length": 99999},
        sigma=2.0, min_divergent=3, min_prior_commits=20,
    )
    assert result is None


def test_classify_flags_when_3_of_5_diverge():
    baselines = {
        name: Baseline(mean=10.0, stddev=1.0, sample_size=30)
        for name in ["avg_diff_size", "comment_ratio", "identifier_entropy",
                     "punctuation_density", "message_length"]
    }
    # All 5 metrics 3σ above mean
    commit_metrics = {name: 13.0 for name in baselines}
    result = classify_by_fingerprint(
        baselines=baselines, commit_metrics=commit_metrics,
        sigma=2.0, min_divergent=3, min_prior_commits=20,
    )
    assert isinstance(result, FingerprintResult)
    assert result.divergent_count == 5
    assert len(result.divergent_metrics) == 5


def test_classify_none_when_only_2_diverge():
    baselines = {
        name: Baseline(mean=10.0, stddev=1.0, sample_size=30)
        for name in ["avg_diff_size", "comment_ratio", "identifier_entropy",
                     "punctuation_density", "message_length"]
    }
    # Only 2 metrics diverge
    commit_metrics = {
        "avg_diff_size": 20.0, "comment_ratio": 20.0,
        "identifier_entropy": 10.0, "punctuation_density": 10.0,
        "message_length": 10.0,
    }
    result = classify_by_fingerprint(
        baselines=baselines, commit_metrics=commit_metrics,
        sigma=2.0, min_divergent=3, min_prior_commits=20,
    )
    assert result is None
