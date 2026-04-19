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
