"""Configurable AI commit detection pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from codeassay.detection.rules import (
    match_author, match_branch, match_message, match_window,
)
from codeassay.detection.scorer import score_commit

if TYPE_CHECKING:
    from codeassay.detection.config import DetectionConfig
    from codeassay.detection.profiles import Profile


@dataclass(frozen=True)
class Detection:
    """Result of classifying a single commit as AI-authored.

    Attributes:
        tool: AI tool name (e.g. "claude_code", "cursor", "unknown").
        confidence: One of "high", "medium", "low".
        method: Coarse bucket — "rule", "profile", or "score".
        source: Fine-grained pointer — e.g. "user:detect.author[0]",
                "profile:cursor", "score:0.82".
        detection_confidence: Numeric confidence 0–100. Rule/profile matches
            backfill from the text value (high=90, medium=60, low=30); scorer
            matches use the real score rounded to an integer.
    """

    tool: str
    confidence: str
    method: str
    source: str
    detection_confidence: int


_CONFIDENCE_NUMERIC = {"high": 90, "medium": 60, "low": 30}


def _confidence_to_numeric(text: str) -> int:
    return _CONFIDENCE_NUMERIC.get(text, 30)


def _check_rule_bundle(
    *, commit, branches, author_rules, branch_rules, message_rules, window_rules,
):
    """Walk categories in fixed order. Return (category, index, rule) or None."""
    for i, rule in enumerate(author_rules):
        if match_author(rule, commit):
            return ("author", i, rule)
    for i, rule in enumerate(branch_rules):
        if match_branch(rule, commit, branches=branches):
            return ("branch", i, rule)
    for i, rule in enumerate(message_rules):
        if match_message(rule, commit):
            return ("message", i, rule)
    for i, rule in enumerate(window_rules):
        if match_window(rule, commit):
            return ("window", i, rule)
    return None


def classify(
    commit: dict,
    *,
    config: "DetectionConfig",
    profiles: list,
    diff_stats: list | None = None,
    seconds_since_prior: int | None = None,
    baselines_for_author=None,   # callable: email -> dict[metric_name, Baseline]
    commit_fingerprint_metrics: dict | None = None,
) -> Detection | None:
    """Run detection pipeline. Returns Detection if AI, None if human.

    Evaluation order:
    1. User rules (author -> branch -> message -> window), first match wins.
    2. Enabled profiles (caller supplies them in alphabetic order), each
       evaluated in the same category order. First matching profile wins.
    3. Per-author fingerprint (if config.fingerprint.enabled).
    4. Probabilistic scorer (if config.score.enabled and score >= threshold).
    """
    branches = set(commit.get("branches", set()) or set())

    # 1. User rules
    hit = _check_rule_bundle(
        commit=commit, branches=branches,
        author_rules=config.author_rules,
        branch_rules=config.branch_rules,
        message_rules=config.message_rules,
        window_rules=config.window_rules,
    )
    if hit:
        cat, idx, rule = hit
        return Detection(
            tool=rule.tool,
            confidence=rule.confidence,
            method="rule",
            source=f"user:detect.{cat}[{idx}]",
            detection_confidence=_confidence_to_numeric(rule.confidence),
        )

    # 2. Profiles
    for profile in profiles:
        hit = _check_rule_bundle(
            commit=commit, branches=branches,
            author_rules=profile.author_rules,
            branch_rules=profile.branch_rules,
            message_rules=profile.message_rules,
            window_rules=profile.window_rules,
        )
        if hit:
            _cat, _idx, rule = hit
            return Detection(
                tool=rule.tool,
                confidence=rule.confidence,
                method="profile",
                source=f"profile:{profile.name}",
                detection_confidence=_confidence_to_numeric(rule.confidence),
            )

    # 3. Fingerprint
    if (
        config.fingerprint.enabled
        and baselines_for_author is not None
        and commit_fingerprint_metrics is not None
    ):
        from codeassay.detection.fingerprint import classify_by_fingerprint
        email = commit.get("author_email", "") or ""
        baselines = baselines_for_author(email)
        if baselines:
            fp = classify_by_fingerprint(
                baselines=baselines,
                commit_metrics=commit_fingerprint_metrics,
                sigma=config.fingerprint.sigma_threshold,
                min_divergent=config.fingerprint.min_divergent_metrics,
                min_prior_commits=config.fingerprint.min_prior_commits,
            )
            if fp is not None:
                return Detection(
                    tool="unknown",
                    confidence="medium",
                    method="fingerprint",
                    source=f"fingerprint:{email}:{fp.divergent_count}/5",
                    detection_confidence=fp.confidence,
                )

    # 4. Scorer
    if config.score.enabled:
        s = score_commit(
            commit=commit,
            diff_stats=diff_stats or [],
            seconds_since_prior=seconds_since_prior,
            config=config.score,
        )
        if s >= config.score.threshold:
            return Detection(
                tool="unknown",
                confidence="low",
                method="score",
                source=f"score:{s:.2f}",
                detection_confidence=int(round(s * 100)),
            )

    return None


__all__ = ["Detection", "classify"]
