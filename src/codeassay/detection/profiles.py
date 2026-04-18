"""Discover and load built-in detection profiles from src/codeassay/profiles/."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from codeassay.detection.config import (
    RuleSpec, WindowSpec,
    parse_rule_list, parse_window_list,
)


@dataclass
class Profile:
    name: str
    author_rules: list[RuleSpec] = field(default_factory=list)
    branch_rules: list[RuleSpec] = field(default_factory=list)
    message_rules: list[RuleSpec] = field(default_factory=list)
    window_rules: list[WindowSpec] = field(default_factory=list)


def _default_profiles_dir() -> Path:
    """Locate the bundled profiles/ directory inside the installed package."""
    pkg_root = resources.files("codeassay")
    return Path(str(pkg_root)) / "profiles"


def _load_single(path: Path) -> Profile:
    with path.open("rb") as f:
        raw = tomllib.load(f)
    detect = raw.get("detect", {})
    name = path.stem
    # Prefix location hints with the profile name so regex-compile failures
    # point at the offending profile, not just the category index.
    try:
        return Profile(
            name=name,
            author_rules=parse_rule_list(detect.get("author", []), f"profile[{name}].author"),
            branch_rules=parse_rule_list(detect.get("branch", []), f"profile[{name}].branch"),
            message_rules=parse_rule_list(detect.get("message", []), f"profile[{name}].message"),
            window_rules=parse_window_list(detect.get("window", []), f"profile[{name}].window"),
        )
    except ValueError as e:
        raise ValueError(f"profile {name!r}: {e}") from e


def load_profiles(
    *,
    profiles_dir: Path | None = None,
    disabled: set[str] | None = None,
) -> list[Profile]:
    """Return all enabled profiles, ordered alphabetically by filename."""
    disabled = disabled or set()
    root = Path(profiles_dir) if profiles_dir else _default_profiles_dir()
    if not root.exists():
        return []
    profiles = []
    for toml_file in sorted(root.glob("*.toml")):
        name = toml_file.stem
        if name in disabled:
            continue
        profiles.append(_load_single(toml_file))
    return profiles
