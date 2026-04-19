"""Per-commit fingerprint metrics + per-author baseline statistics."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

_COMMENT_RE = re.compile(r"^\s*(//|#|/\*|\*)")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")
_PUNCT_CHARS = set(".,;:!?")


def metric_avg_diff_size(*, lines_added: int) -> float:
    """Number of lines added by the commit. Baseline compares each commit's
    size to the author's historical mean."""
    return float(lines_added)


def metric_comment_ratio(added_lines: list[str]) -> float:
    """Fraction of added lines that begin with a comment marker."""
    if not added_lines:
        return 0.0
    comment_count = sum(1 for line in added_lines if _COMMENT_RE.match(line))
    return comment_count / len(added_lines)


def metric_identifier_entropy(added_lines: list[str]) -> float:
    """Shannon entropy of identifier tokens extracted from added lines."""
    tokens: list[str] = []
    for line in added_lines:
        tokens.extend(_IDENT_RE.findall(line))
    if not tokens:
        return 0.0
    counts = Counter(tokens)
    total = sum(counts.values())
    entropy = 0.0
    for c in counts.values():
        p = c / total
        entropy -= p * math.log(p)
    return entropy


def metric_punctuation_density(message: str) -> float:
    """Ratio of `.,;:!?` chars to total chars in commit message."""
    if not message:
        return 0.0
    punct = sum(1 for c in message if c in _PUNCT_CHARS)
    return punct / len(message)


def metric_message_length(message: str) -> int:
    """Character count of commit message."""
    return len(message)


@dataclass(frozen=True)
class Baseline:
    """Per-author, per-metric running baseline."""
    mean: float
    stddev: float
    sample_size: int


def update_baseline(b: Baseline, *, new_value: float) -> Baseline:
    """Welford's online algorithm for incremental mean + sample stddev."""
    n = b.sample_size + 1
    # Convert stored (mean, stddev, n) back into Welford's M2.
    old_m2 = b.stddev * b.stddev * max(b.sample_size - 1, 0)
    delta = new_value - b.mean
    new_mean = b.mean + delta / n
    new_m2 = old_m2 + delta * (new_value - new_mean)
    new_stddev = math.sqrt(new_m2 / (n - 1)) if n > 1 else 0.0
    return Baseline(mean=new_mean, stddev=new_stddev, sample_size=n)


def is_divergent(
    baseline: Baseline, *, value: float, sigma: float = 2.0,
    min_sample: int = 20,
) -> bool:
    """Z-score divergence check with minimum sample gating."""
    if baseline.sample_size < min_sample:
        return False
    if baseline.stddev == 0:
        return value != baseline.mean
    z = abs(value - baseline.mean) / baseline.stddev
    return z >= sigma
