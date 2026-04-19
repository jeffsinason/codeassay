"""Rule matching primitives for the detection pipeline."""

from __future__ import annotations

from datetime import date, datetime
from typing import Iterable

from codeassay.detection.config import RuleSpec, WindowSpec


def match_author(rule: RuleSpec, commit: dict) -> bool:
    """Match against author email, then author name.

    NOTE: the ``author_email`` field is populated by Task 11's scanner
    refactor (``%ae`` in the git-log format). Until that lands, only the
    ``author`` (name) branch of this matcher effectively fires.
    """
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
    """Check author+date match against a time-window rule.

    Date comparison uses the commit's author-local timezone: a commit
    timestamped ``2025-12-31T23:30:00-08:00`` registers as 2025-12-31
    regardless of the machine running codeassay. This matches user
    intuition about "commits from that week" better than UTC would.
    """
    email = commit.get("author_email", "") or ""
    name = commit.get("author", "") or ""
    if not (rule.author.search(email) or rule.author.search(name)):
        return False
    d = _parse_commit_date(commit.get("date", "") or "")
    if d is None:
        return False
    return rule.start <= d <= rule.end
