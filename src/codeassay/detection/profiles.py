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


def _builtin_profile_entries() -> list:
    """List bundled profile files as Traversables (filesystem-install agnostic)."""
    root = resources.files("codeassay.profiles")
    return sorted(
        (entry for entry in root.iterdir() if entry.name.endswith(".toml")),
        key=lambda e: e.name,
    )


def _load_single(name: str, raw: dict) -> Profile:
    detect = raw.get("detect", {})
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


def _read_toml(entry) -> dict:
    """Read a TOML file from a Traversable or a Path."""
    if isinstance(entry, Path):
        with entry.open("rb") as f:
            return tomllib.load(f)
    # Traversable (e.g., from importlib.resources) supports .read_bytes()
    return tomllib.loads(entry.read_text(encoding="utf-8"))


def load_profiles(
    *,
    profiles_dir: Path | None = None,
    disabled: set[str] | None = None,
) -> list[Profile]:
    """Return all enabled profiles, ordered alphabetically by filename.

    Args:
        profiles_dir: Override the default bundled profiles directory.
            Useful for tests.
        disabled: Set of filename stems (case-sensitive) to skip.
    """
    disabled = disabled or set()

    if profiles_dir is not None:
        root = Path(profiles_dir)
        if not root.exists():
            return []
        entries = sorted(root.glob("*.toml"))
        def _name(e): return e.stem
    else:
        try:
            entries = _builtin_profile_entries()
        except (ModuleNotFoundError, FileNotFoundError):
            return []
        def _name(e): return e.name.rsplit(".", 1)[0]

    profiles = []
    for entry in entries:
        name = _name(entry)
        if name in disabled:
            continue
        raw = _read_toml(entry)
        profiles.append(_load_single(name, raw))
    return profiles
