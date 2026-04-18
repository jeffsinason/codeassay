"""Rule matching primitives for the detection pipeline."""

from __future__ import annotations

from datetime import date, datetime
from typing import Iterable

from codeassay.detection.config import RuleSpec, WindowSpec


def match_author(rule: RuleSpec, commit: dict) -> bool:
    """Match against author email, then author name."""
    email = commit.get("author_email", "") or ""
    name = commit.get("author", "") or ""
    return bool(rule.pattern.search(email) or rule.pattern.search(name))


def match_branch(rule: RuleSpec, commit: dict, *, branches: Iterable[str]) -> bool:
    """Match if any branch that contains this commit matches the rule pattern."""
    for b in branches:
        if rule.pattern.search(b):
            return True
    return False


def match_message(rule: RuleSpec, commit: dict) -> bool:
    msg = commit.get("message", "") or ""
    return bool(rule.pattern.search(msg))


def _parse_commit_date(raw: str) -> date | None:
    try:
        return datetime.fromisoformat(raw).date()
    except (ValueError, TypeError):
        return None


def match_window(rule: WindowSpec, commit: dict) -> bool:
    email = commit.get("author_email", "") or ""
    name = commit.get("author", "") or ""
    if not (rule.author.search(email) or rule.author.search(name)):
        return False
    d = _parse_commit_date(commit.get("date", "") or "")
    if d is None:
        return False
    try:
        start = date.fromisoformat(rule.start)
        end = date.fromisoformat(rule.end)
    except ValueError:
        return False
    return start <= d <= end
