"""Load and validate .codeassay.toml into typed config objects."""

from __future__ import annotations

import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_THRESHOLD = 0.7
DEFAULT_WEIGHTS = {
    "diff_wholesale_rewrite": 0.20,
    "message_structured_body": 0.15,
    "commit_velocity": 0.15,
    "emoji_indicator": 0.10,
    "message_boilerplate": 0.15,
    "file_diversity": 0.10,
    "perfect_punctuation": 0.15,
}
VALID_CONFIDENCE = {"high", "medium", "low"}
KNOWN_TOP_LEVEL_KEYS = {"profiles", "detect", "score"}


@dataclass(frozen=True)
class RuleSpec:
    pattern: re.Pattern
    tool: str
    confidence: str = "medium"


@dataclass(frozen=True)
class WindowSpec:
    author: re.Pattern
    start: str  # ISO date YYYY-MM-DD, inclusive
    end: str    # ISO date YYYY-MM-DD, inclusive
    tool: str
    confidence: str = "medium"
    note: str = ""


@dataclass
class ScoreConfig:
    enabled: bool = False
    threshold: float = DEFAULT_THRESHOLD
    weights: dict = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))


@dataclass
class DetectionConfig:
    author_rules: list[RuleSpec] = field(default_factory=list)
    branch_rules: list[RuleSpec] = field(default_factory=list)
    message_rules: list[RuleSpec] = field(default_factory=list)
    window_rules: list[WindowSpec] = field(default_factory=list)
    disabled_profiles: set[str] = field(default_factory=set)
    score: ScoreConfig = field(default_factory=ScoreConfig)


def _warn(msg: str) -> None:
    print(f"codeassay: warning: {msg}", file=sys.stderr)


def _compile(pattern: str, location: str) -> re.Pattern:
    try:
        return re.compile(pattern)
    except re.error as e:
        raise ValueError(f"invalid regex at {location}: {e}") from e


def _parse_confidence(raw: dict, location: str) -> str:
    c = raw.get("confidence", "medium")
    if c not in VALID_CONFIDENCE:
        _warn(f"{location}: unknown confidence {c!r}, defaulting to 'medium'")
        return "medium"
    return c


def _parse_rule_list(rules_raw: list, category: str) -> list[RuleSpec]:
    out = []
    for i, entry in enumerate(rules_raw):
        location = f"detect.{category}[{i}]"
        if "pattern" not in entry or "tool" not in entry:
            _warn(f"{location}: missing required field (pattern or tool); skipping")
            continue
        out.append(RuleSpec(
            pattern=_compile(entry["pattern"], location),
            tool=entry["tool"],
            confidence=_parse_confidence(entry, location),
        ))
    return out


def _parse_window_list(rules_raw: list) -> list[WindowSpec]:
    out = []
    for i, entry in enumerate(rules_raw):
        location = f"detect.window[{i}]"
        required = ("author", "start", "end", "tool")
        missing = [k for k in required if k not in entry]
        if missing:
            _warn(f"{location}: missing required fields {missing}; skipping")
            continue
        out.append(WindowSpec(
            author=_compile(entry["author"], location),
            start=entry["start"],
            end=entry["end"],
            tool=entry["tool"],
            confidence=_parse_confidence(entry, location),
            note=entry.get("note", ""),
        ))
    return out


def _parse_score(score_raw: dict) -> ScoreConfig:
    weights = dict(DEFAULT_WEIGHTS)
    user_weights = score_raw.get("weights", {})
    if user_weights:
        weights = dict(user_weights)
        total = sum(weights.values())
        if not (0.99 <= total <= 1.01):
            _warn(f"score.weights sum to {total:.3f}, not ~1.0; normalizing")
            if total > 0:
                weights = {k: v / total for k, v in weights.items()}
    return ScoreConfig(
        enabled=bool(score_raw.get("enabled", False)),
        threshold=float(score_raw.get("threshold", DEFAULT_THRESHOLD)),
        weights=weights,
    )


def _parse_disabled_profiles(profiles_raw: dict) -> set[str]:
    disabled = set()
    for name, settings in profiles_raw.items():
        if isinstance(settings, dict) and settings.get("enabled") is False:
            disabled.add(name)
    return disabled


def load_config(repo_path: Path) -> DetectionConfig:
    """Load .codeassay.toml from repo_path. Returns defaults if absent."""
    cfg_file = Path(repo_path) / ".codeassay.toml"
    if not cfg_file.exists():
        return DetectionConfig()

    with cfg_file.open("rb") as f:
        raw = tomllib.load(f)

    unknown = set(raw.keys()) - KNOWN_TOP_LEVEL_KEYS
    for key in unknown:
        _warn(f".codeassay.toml: unknown top-level key {key!r} (ignored)")

    detect = raw.get("detect", {})
    return DetectionConfig(
        author_rules=_parse_rule_list(detect.get("author", []), "author"),
        branch_rules=_parse_rule_list(detect.get("branch", []), "branch"),
        message_rules=_parse_rule_list(detect.get("message", []), "message"),
        window_rules=_parse_window_list(detect.get("window", [])),
        disabled_profiles=_parse_disabled_profiles(raw.get("profiles", {})),
        score=_parse_score(raw.get("score", {})),
    )
