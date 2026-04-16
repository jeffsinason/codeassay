"""Tests for codeassay.classifier."""

from codeassay.classifier import classify_rework, ClassificationResult


def test_classify_bug_fix_from_message():
    result = classify_rework(
        commit_message="fix: bug in greet function",
        lines_added=2, lines_removed=1, total_original_lines=50,
        files_affected=["src/foo.py"],
    )
    assert result.category == "bug_fix"
    assert result.confidence in ("high", "medium")


def test_classify_misunderstanding_from_message():
    result = classify_rework(
        commit_message="rewrite: wrong approach, misunderstood the requirement",
        lines_added=40, lines_removed=35, total_original_lines=35,
        files_affected=["src/foo.py"],
    )
    assert result.category == "misunderstanding"


def test_classify_test_failure():
    result = classify_rework(
        commit_message="fix: tests were failing",
        lines_added=3, lines_removed=2, total_original_lines=50,
        files_affected=["src/foo.py"],
    )
    assert result.category == "test_failure"


def test_classify_security_issue():
    result = classify_rework(
        commit_message="fix: SQL injection vulnerability in query builder",
        lines_added=5, lines_removed=3, total_original_lines=100,
        files_affected=["src/db.py"],
    )
    assert result.category == "security_issue"


def test_classify_style_violation():
    result = classify_rework(
        commit_message="style: fix naming convention",
        lines_added=4, lines_removed=4, total_original_lines=100,
        files_affected=["src/foo.py"],
    )
    assert result.category == "style_violation"


def test_classify_incomplete_implementation():
    result = classify_rework(
        commit_message="feat: implement the TODO left by AI",
        lines_added=20, lines_removed=2, total_original_lines=50,
        files_affected=["src/foo.py"],
    )
    assert result.category == "incomplete_implementation"


def test_classify_over_engineering():
    result = classify_rework(
        commit_message="simplify: remove unnecessary abstraction layer",
        lines_added=5, lines_removed=40, total_original_lines=80,
        files_affected=["src/foo.py"],
    )
    assert result.category == "over_engineering"


def test_classify_unknown_defaults_to_bug_fix():
    result = classify_rework(
        commit_message="update some code",
        lines_added=3, lines_removed=2, total_original_lines=100,
        files_affected=["src/foo.py"],
    )
    assert result.category == "bug_fix"
    assert result.confidence == "low"
