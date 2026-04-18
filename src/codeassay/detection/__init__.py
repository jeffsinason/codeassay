"""Configurable AI commit detection pipeline."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Detection:
    """Result of classifying a single commit as AI-authored.

    Attributes:
        tool: AI tool name (e.g. "claude_code", "cursor", "unknown").
        confidence: One of "high", "medium", "low".
        method: Coarse bucket — "rule", "profile", or "score".
        source: Fine-grained pointer — e.g. "user:detect.author[0]",
                "profile:cursor", "score:0.82".
    """

    tool: str
    confidence: str
    method: str
    source: str


__all__ = ["Detection"]
