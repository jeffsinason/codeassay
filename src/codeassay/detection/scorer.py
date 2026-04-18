"""Probabilistic weak-signal scorer for commits lacking deterministic markers."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from codeassay.detection.config import ScoreConfig

EMOJI_SET = {"🤖", "✨", "🚀", "♻️"}
BOILERPLATE_HEADERS = ("Summary:", "Changes:", "Test plan:", "## Summary", "## Test plan")


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def signal_diff_wholesale_rewrite(stats: list[dict]) -> float:
    """(added + removed) / max(file_size, 1), averaged across touched files."""
    if not stats:
        return 0.0
    ratios = []
    for s in stats:
        size = max(int(s.get("file_size", 0)), 1)
        churn = int(s.get("added", 0)) + int(s.get("removed", 0))
        ratios.append(min(churn / size, 1.0))
    return _clamp(sum(ratios) / len(ratios))


def signal_message_structured_body(message: str) -> float:
    """Body has multi-paragraph + bullet lists. 0.0 if only a one-line title."""
    if not message:
        return 0.0
    lines = message.splitlines()
    if len(lines) < 2:
        return 0.0
    body = "\n".join(lines[1:]).strip()
    if not body:
        return 0.0
    paragraphs = [p for p in body.split("\n\n") if p.strip()]
    bullet_lines = sum(1 for line in body.splitlines() if line.strip().startswith(("- ", "* ")))
    score = 0.0
    if len(paragraphs) >= 2:
        score += 0.4
    if bullet_lines >= 2:
        score += 0.4
    if len(body) > 120:
        score += 0.2
    return _clamp(score)


def signal_commit_velocity(seconds_since_prior: int | None) -> float:
    """<60s → 1.0, >1h → 0.0, linear in between."""
    if seconds_since_prior is None:
        return 0.0
    if seconds_since_prior <= 60:
        return 1.0
    if seconds_since_prior >= 3600:
        return 0.0
    return _clamp(1.0 - (seconds_since_prior - 60) / (3600 - 60))


def signal_emoji_indicator(message: str) -> float:
    return 1.0 if any(e in message for e in EMOJI_SET) else 0.0


def signal_message_boilerplate(message: str) -> float:
    hits = sum(1 for h in BOILERPLATE_HEADERS if h in message)
    if hits == 0:
        return 0.0
    return _clamp(min(hits / 2, 1.0))


def signal_file_diversity(stats: list[dict]) -> float:
    if not stats:
        return 0.0
    exts = set()
    for s in stats:
        path = s.get("path", "")
        if "." in path:
            exts.add(path.rsplit(".", 1)[-1].lower())
        else:
            exts.add("")
    return _clamp(min(len(exts) / 4, 1.0))


_DOUBLE_SPACE = re.compile(r"  +")
_MULTI_COMMA = re.compile(r",{2,}")


def signal_perfect_punctuation(message: str) -> float:
    if not message:
        return 0.0
    title = message.splitlines()[0]
    score = 1.0
    if _DOUBLE_SPACE.search(message):
        score -= 0.4
    if _MULTI_COMMA.search(message):
        score -= 0.3
    if title and title[0].islower() and not title.startswith(("fix:", "feat:", "chore:", "docs:", "refactor:", "test:")):
        score -= 0.2
    if title and not title.rstrip().endswith((".", ":")) and len(title) > 40:
        score -= 0.1
    return _clamp(score)


def _raw_signals(
    commit: dict,
    diff_stats: list[dict],
    seconds_since_prior: int | None,
) -> dict[str, float]:
    """Compute the 7 raw (unweighted) signal values for a commit."""
    msg = commit.get("message", "") or ""
    return {
        "diff_wholesale_rewrite": signal_diff_wholesale_rewrite(diff_stats),
        "message_structured_body": signal_message_structured_body(msg),
        "commit_velocity": signal_commit_velocity(seconds_since_prior),
        "emoji_indicator": signal_emoji_indicator(msg),
        "message_boilerplate": signal_message_boilerplate(msg),
        "file_diversity": signal_file_diversity(diff_stats),
        "perfect_punctuation": signal_perfect_punctuation(msg),
    }


def score_commit(
    *,
    commit: dict,
    diff_stats: list[dict],
    seconds_since_prior: int | None,
    config: "ScoreConfig",
) -> float:
    """Return a 0-1 score combining all signals weighted per config."""
    signals = _raw_signals(commit, diff_stats, seconds_since_prior)
    total = sum(value * config.weights.get(name, 0.0) for name, value in signals.items())
    return _clamp(total)


def per_signal_contributions(
    *,
    commit: dict,
    diff_stats: list[dict],
    seconds_since_prior: int | None,
    config: "ScoreConfig",
) -> dict[str, dict[str, float]]:
    """Return a dict of signal -> {'raw': float, 'weighted': float} for auditing.

    The raw values are guaranteed to match those used by score_commit on the same
    inputs — both go through _raw_signals.
    """
    raw = _raw_signals(commit, diff_stats, seconds_since_prior)
    return {
        name: {"raw": value, "weighted": value * config.weights.get(name, 0.0)}
        for name, value in raw.items()
    }
