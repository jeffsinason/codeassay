"""Load and match .codeassayignore patterns (gitignore-style)."""

from pathlib import Path, PurePosixPath


def load_ignore_patterns(repo_path: Path) -> list[str]:
    """Load ignore patterns from .codeassayignore in the repo root.

    Returns a list of patterns. Blank lines and comments (#) are skipped.
    """
    ignore_file = repo_path / ".codeassayignore"
    if not ignore_file.exists():
        return []
    patterns = []
    for line in ignore_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return patterns


def is_ignored(filepath: str, patterns: list[str]) -> bool:
    """Check if a filepath matches any ignore pattern.

    Supports gitignore-style globs:
      *.md          — match by extension
      docs/*        — match directory prefix
      .organization — match exact filename
      **/*.pyc      — match in any subdirectory
    """
    path = PurePosixPath(filepath)
    for pattern in patterns:
        # ** matches across directory boundaries
        if "**" in pattern:
            # docs/** should match docs/anything/at/any/depth
            prefix = pattern.split("**")[0].rstrip("/")
            if prefix and filepath.startswith(prefix + "/"):
                return True
            # **/pattern matches in any directory
            suffix = pattern.split("**")[-1].lstrip("/")
            if suffix and path.match(suffix):
                return True
            continue
        # Pattern with / — match against the full path (single level)
        if "/" in pattern:
            if path.match(pattern):
                return True
            continue
        # Simple pattern (no /) — match against basename only
        if path.match(pattern):
            return True
    return False


def filter_files(files: list[str], patterns: list[str]) -> list[str]:
    """Return only files that are NOT ignored."""
    if not patterns:
        return files
    return [f for f in files if not is_ignored(f, patterns)]


def filter_files_csv(files_csv: str, patterns: list[str]) -> str:
    """Filter a comma-separated file list, returning filtered CSV."""
    if not patterns or not files_csv:
        return files_csv
    files = [f for f in files_csv.split(",") if f]
    filtered = filter_files(files, patterns)
    return ",".join(filtered)
