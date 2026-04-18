import re
from datetime import date
import pytest

from codeassay.detection.config import RuleSpec, WindowSpec
from codeassay.detection.rules import (
    match_author, match_branch, match_message, match_window,
)


def _commit(**overrides):
    base = {
        "hash": "abc123",
        "author": "Jane Dev",
        "author_email": "jane@example.com",
        "date": "2026-02-15T12:00:00+00:00",
        "message": "feat: add foo",
    }
    base.update(overrides)
    return base


def _rule(pattern: str, tool="x", confidence="high") -> RuleSpec:
    return RuleSpec(pattern=re.compile(pattern), tool=tool, confidence=confidence)


# ---- author rule ----

def test_match_author_by_email():
    assert match_author(_rule("jane@.*"), _commit()) is True


def test_match_author_by_name():
    assert match_author(_rule("Jane Dev"), _commit()) is True


def test_match_author_no_match():
    assert match_author(_rule("alice@.*"), _commit()) is False


# ---- branch rule ----

def test_match_branch_hit():
    rule = _rule("^cursor/.*")
    assert match_branch(rule, _commit(), branches={"cursor/feature-x"}) is True


def test_match_branch_multiple_branches_any_hit():
    rule = _rule("^ai/.*")
    assert match_branch(rule, _commit(), branches={"main", "ai/foo"}) is True


def test_match_branch_no_match():
    rule = _rule("^cursor/.*")
    assert match_branch(rule, _commit(), branches={"main"}) is False


def test_match_branch_empty_branches():
    rule = _rule("^cursor/.*")
    assert match_branch(rule, _commit(), branches=set()) is False


# ---- message rule ----

def test_match_message_hit():
    rule = _rule(r"^\[AI\]")
    assert match_message(rule, _commit(message="[AI] feat: thing")) is True


def test_match_message_multiline_trailer():
    rule = _rule(r"Co-Authored-By:.*Claude")
    assert match_message(
        rule,
        _commit(message="feat: x\n\nCo-Authored-By: Claude <x@y>"),
    ) is True


def test_match_message_no_match():
    rule = _rule(r"^\[AI\]")
    assert match_message(rule, _commit(message="feat: thing")) is False


# ---- window rule ----

def _wspec(author_pat="jane@.*", start="2026-01-01", end="2026-03-15") -> WindowSpec:
    return WindowSpec(
        author=re.compile(author_pat),
        start=date.fromisoformat(start),
        end=date.fromisoformat(end),
        tool="claude_code",
        confidence="high",
    )


def test_match_window_in_range():
    assert match_window(_wspec(), _commit(date="2026-02-10T00:00:00+00:00")) is True


def test_match_window_before_start():
    assert match_window(_wspec(), _commit(date="2025-12-31T23:59:59+00:00")) is False


def test_match_window_after_end():
    assert match_window(_wspec(), _commit(date="2026-03-16T00:00:00+00:00")) is False


def test_match_window_boundary_inclusive():
    assert match_window(_wspec(), _commit(date="2026-01-01T00:00:00+00:00")) is True
    assert match_window(_wspec(), _commit(date="2026-03-15T23:59:59+00:00")) is True


def test_match_window_author_mismatch():
    assert match_window(
        _wspec(author_pat="bob@.*"),
        _commit(date="2026-02-10T00:00:00+00:00"),
    ) is False


def test_match_window_malformed_date_returns_false():
    assert match_window(_wspec(), _commit(date="not-a-date")) is False
