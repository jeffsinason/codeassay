"""Line-survival and turnover-rate computation.

Core primitive: given a commit C that added lines to a file, how many of
those lines still exist verbatim at a later reference point R? If R is
HEAD, this is "how much of what C wrote survives today?"

Aggregated across commits in a window, this produces the turnover_rate
metric. Computed separately for AI vs human cohorts.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


def lines_added_by_commit(repo_path: Path, commit_sha: str, file: str) -> int:
    """Number of lines added by `commit_sha` to `file` (per git numstat).

    Returns 0 for binary files and files that were only deleted/renamed.
    """
    result = subprocess.run(
        ["git", "show", "--numstat", "--format=", commit_sha, "--", file],
        cwd=repo_path, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return 0
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added_s, _removed, _path = parts
        if added_s == "-":
            return 0  # binary
        return int(added_s)
    return 0


def lines_survived_for_commit(
    repo_path: Path, commit_sha: str, file: str, *, as_of: str = "HEAD",
) -> int:
    """Count lines at `as_of` that trace back to `commit_sha` in `file`.

    Uses `git blame --line-porcelain` at the reference point; counts blame
    entries whose originating commit equals `commit_sha`. Returns 0 if file
    does not exist at `as_of`.
    """
    check = subprocess.run(
        ["git", "cat-file", "-e", f"{as_of}:{file}"],
        cwd=repo_path, capture_output=True, text=True,
    )
    if check.returncode != 0:
        return 0
    result = subprocess.run(
        ["git", "blame", "--line-porcelain", as_of, "--", file],
        cwd=repo_path, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return 0
    count = 0
    prefix = commit_sha[:40]
    for line in result.stdout.splitlines():
        if line.startswith(prefix) and len(line) > 40 and line[40] == " ":
            count += 1
    return count


@dataclass(frozen=True)
class CommitLineRecord:
    commit_sha: str
    file: str
    lines_added: int
    lines_survived: int


@dataclass(frozen=True)
class TurnoverSummary:
    ai_lines_added: int
    ai_lines_discarded: int
    human_lines_added: int
    human_lines_discarded: int
    ai_turnover: float
    human_turnover: float
    ai_turnover_ratio: float | None  # None if human_turnover == 0


def compute_turnover_metrics(
    records: Iterable[CommitLineRecord],
    *,
    ai_shas: set[str],
) -> TurnoverSummary:
    """Aggregate per-commit line records into AI vs human turnover rates.

    Args:
        records: per-(commit, file) survival data.
        ai_shas: set of commit SHAs classified as AI-authored.

    Returns:
        TurnoverSummary with both cohort rates plus the AI/human ratio.
        ratio is None when human_turnover is 0 (division guard).
    """
    ai_added = ai_discarded = 0
    hu_added = hu_discarded = 0
    for r in records:
        discarded = max(0, r.lines_added - r.lines_survived)
        if r.commit_sha in ai_shas:
            ai_added += r.lines_added
            ai_discarded += discarded
        else:
            hu_added += r.lines_added
            hu_discarded += discarded
    ai_rate = (ai_discarded / ai_added) if ai_added else 0.0
    hu_rate = (hu_discarded / hu_added) if hu_added else 0.0
    ratio = (ai_rate / hu_rate) if hu_rate > 0 else None
    return TurnoverSummary(
        ai_lines_added=ai_added,
        ai_lines_discarded=ai_discarded,
        human_lines_added=hu_added,
        human_lines_discarded=hu_discarded,
        ai_turnover=ai_rate,
        human_turnover=hu_rate,
        ai_turnover_ratio=ratio,
    )
