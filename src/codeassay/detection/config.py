"""Load and validate .codeassay.toml into typed config objects."""

from __future__ import annotations

import re
import sys
import tomllib
from dataclasses import dataclass, field
from datetime import date
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
KNOWN_TOP_LEVEL_KEYS = {"profiles", "detect", "score", "turnover", "fingerprint"}


@dataclass(frozen=True)
class RuleSpec:
    pattern: re.Pattern[str]
    tool: str
    confidence: str = "medium"


@dataclass(frozen=True)
class WindowSpec:
    author: re.Pattern[str]
    start: date  # inclusive
    end: date    # inclusive
    tool: str
    confidence: str = "medium"
    note: str = ""


@dataclass
class ScoreConfig:
    enabled: bool = False
    threshold: float = DEFAULT_THRESHOLD
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))


@dataclass
class TurnoverConfig:
    lookback_days: int = 90
    rewrite_window_days: int = 30
    yellow_threshold: float = 0.04
    red_threshold: float = 0.06


@dataclass
class FingerprintConfig:
    enabled: bool = False
    min_prior_commits: int = 20
    sigma_threshold: float = 2.0
    min_divergent_metrics: int = 3


@dataclass
class DetectionConfig:
    author_rules: list[RuleSpec] = field(default_factory=list)
    branch_rules: list[RuleSpec] = field(default_factory=list)
    message_rules: list[RuleSpec] = field(default_factory=list)
    window_rules: list[WindowSpec] = field(default_factory=list)
    disabled_profiles: set[str] = field(default_factory=set)
    score: ScoreConfig = field(default_factory=ScoreConfig)
    turnover: TurnoverConfig = field(default_factory=TurnoverConfig)
    fingerprint: FingerprintConfig = field(default_factory=FingerprintConfig)


def _warn(msg: str) -> None:
    print(f"codeassay: warning: {msg}", file=sys.stderr)


def _compile(pattern: str, location: str) -> re.Pattern[str]:
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


def parse_rule_list(rules_raw: list, location_prefix: str) -> list[RuleSpec]:
    out = []
    for i, entry in enumerate(rules_raw):
        location = f"{location_prefix}[{i}]"
        if "pattern" not in entry or "tool" not in entry:
            _warn(f"{location}: missing required field (pattern or tool); skipping")
            continue
        out.append(RuleSpec(
            pattern=_compile(entry["pattern"], location),
            tool=entry["tool"],
            confidence=_parse_confidence(entry, location),
        ))
    return out


def parse_window_list(rules_raw: list, location_prefix: str) -> list[WindowSpec]:
    out = []
    for i, entry in enumerate(rules_raw):
        location = f"{location_prefix}[{i}]"
        required = ("author", "start", "end", "tool")
        missing = [k for k in required if k not in entry]
        if missing:
            _warn(f"{location}: missing required fields {missing}; skipping")
            continue
        try:
            start = date.fromisoformat(entry["start"])
            end = date.fromisoformat(entry["end"])
        except ValueError as e:
            raise ValueError(f"invalid date at {location}: {e}") from e
        out.append(WindowSpec(
            author=_compile(entry["author"], location),
            start=start,
            end=end,
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
        if total <= 0:
            _warn(
                f"score.weights sum to {total:.3f}; cannot normalize. "
                "Falling back to defaults."
            )
            weights = dict(DEFAULT_WEIGHTS)
        elif not (0.99 <= total <= 1.01):
            _warn(f"score.weights sum to {total:.3f}, not ~1.0; normalizing")
            weights = {k: v / total for k, v in weights.items()}
    return ScoreConfig(
        enabled=bool(score_raw.get("enabled", False)),
        threshold=float(score_raw.get("threshold", DEFAULT_THRESHOLD)),
        weights=weights,
    )


def _parse_turnover(raw: dict) -> TurnoverConfig:
    return TurnoverConfig(
        lookback_days=int(raw.get("lookback_days", 90)),
        rewrite_window_days=int(raw.get("rewrite_window_days", 30)),
        yellow_threshold=float(raw.get("yellow_threshold", 0.04)),
        red_threshold=float(raw.get("red_threshold", 0.06)),
    )


def _parse_fingerprint(raw: dict) -> FingerprintConfig:
    return FingerprintConfig(
        enabled=bool(raw.get("enabled", False)),
        min_prior_commits=int(raw.get("min_prior_commits", 20)),
        sigma_threshold=float(raw.get("sigma_threshold", 2.0)),
        min_divergent_metrics=int(raw.get("min_divergent_metrics", 3)),
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
        author_rules=parse_rule_list(detect.get("author", []), "detect.author"),
        branch_rules=parse_rule_list(detect.get("branch", []), "detect.branch"),
        message_rules=parse_rule_list(detect.get("message", []), "detect.message"),
        window_rules=parse_window_list(detect.get("window", []), "detect.window"),
        disabled_profiles=_parse_disabled_profiles(raw.get("profiles", {})),
        score=_parse_score(raw.get("score", {})),
        turnover=_parse_turnover(raw.get("turnover", {})),
        fingerprint=_parse_fingerprint(raw.get("fingerprint", {})),
    )
