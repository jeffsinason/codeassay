"""Rework detection engine — identifies commits that modify AI-authored code."""

import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from codeassay.db import get_ai_commits, insert_rework_event
from codeassay.ignore import filter_files, load_ignore_patterns

DEPENDENCY_FILE_PATTERNS = [
    re.compile(r"requirements.*\.txt$"),
    re.compile(r"Pipfile(\.lock)?$"),
    re.compile(r"poetry\.lock$"),
    re.compile(r"pyproject\.toml$"),
    re.compile(r"package(-lock)?\.json$"),
    re.compile(r"yarn\.lock$"),
    re.compile(r"Gemfile(\.lock)?$"),
    re.compile(r"go\.(mod|sum)$"),
    re.compile(r"Cargo\.(toml|lock)$"),
]

DEFAULT_REFACTOR_THRESHOLD = 10
DEFAULT_TIME_WINDOW_DAYS = 14
DEFAULT_REWRITE_THRESHOLD = 0.5  # If >50% of lines are replaced, it's a file-level rewrite


def is_excluded_commit(
    files: list[str], message: str, file_count: int,
    refactor_threshold: int = DEFAULT_REFACTOR_THRESHOLD,
) -> bool:
    if files and all(
        any(p.search(f) for p in DEPENDENCY_FILE_PATTERNS)
        for f in files
    ):
        return True
    if file_count >= refactor_threshold:
        return True
    return False


def get_blame_origins(repo_path: Path, commit_hash: str, file_path: str) -> set[str]:
    result = subprocess.run(
        ["git", "diff", f"{commit_hash}~1..{commit_hash}", "--", file_path],
        cwd=repo_path, capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout:
        return set()

    changed_lines = []
    current_line = 0
    for line in result.stdout.split("\n"):
        if line.startswith("@@"):
            match = re.search(r"-(\d+)", line)
            if match:
                current_line = int(match.group(1))
            continue
        if line.startswith("-") and not line.startswith("---"):
            changed_lines.append(current_line)
            current_line += 1
        elif line.startswith("+") and not line.startswith("+++"):
            pass
        else:
            current_line += 1

    if not changed_lines:
        return set()

    blame_result = subprocess.run(
        ["git", "blame", "--porcelain", f"{commit_hash}~1", "--", file_path],
        cwd=repo_path, capture_output=True, text=True,
    )
    if blame_result.returncode != 0:
        return set()

    origins = set()
    current_origin = None
    current_blame_line = 0
    for bline in blame_result.stdout.split("\n"):
        parts = bline.split()
        # Blame header line: <40-char hex hash> <orig_line> <final_line> [<num_lines>]
        if len(parts) >= 3 and len(parts[0]) == 40 and all(c in "0123456789abcdef" for c in parts[0]):
            try:
                current_origin = parts[0]
                current_blame_line = int(parts[2])
            except ValueError:
                continue
        if current_origin and current_blame_line in changed_lines:
            origins.add(current_origin)

    return origins


def _get_commit_files(repo_path: Path, commit_hash: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit_hash],
        cwd=repo_path, capture_output=True, text=True,
    )
    return [f for f in result.stdout.strip().split("\n") if f]


def _get_file_diff_stats(repo_path: Path, commit_hash: str, file_path: str) -> tuple[int, int]:
    """Get (lines_added, lines_removed) for a specific file in a commit."""
    result = subprocess.run(
        ["git", "diff", "--numstat", f"{commit_hash}~1..{commit_hash}", "--", file_path],
        cwd=repo_path, capture_output=True, text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return (0, 0)
    parts = result.stdout.strip().split("\t")
    if len(parts) >= 2:
        try:
            return (int(parts[0]), int(parts[1]))
        except ValueError:
            return (0, 0)
    return (0, 0)


def _get_file_line_count(repo_path: Path, commit_hash: str, file_path: str) -> int:
    """Get the number of lines in a file at a specific commit's parent."""
    result = subprocess.run(
        ["git", "show", f"{commit_hash}~1:{file_path}"],
        cwd=repo_path, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return 0
    return len(result.stdout.split("\n"))


def _get_commits_since(repo_path: Path, since_hash: str, until_date_limit: str | None = None) -> list[dict]:
    cmd = ["git", "log", f"{since_hash}..HEAD", "--format=%H %aI %s"]
    result = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True)
    if result.returncode != 0:
        return []
    commits = []
    for line in result.stdout.strip().split("\n"):
        if not line:
            continue
        parts = line.split(" ", 2)
        if len(parts) >= 3:
            commits.append({"hash": parts[0], "date": parts[1], "message": parts[2]})
    return commits


def _normalize_date(date_str: str) -> datetime:
    """Parse an ISO date string and normalize to naive datetime for comparison."""
    dt = datetime.fromisoformat(date_str)
    if dt.tzinfo is not None:
        dt = datetime(*dt.utctimetuple()[:6])
    return dt


def detect_rework(
    repo_path: Path, conn,
    time_window_days: int = DEFAULT_TIME_WINDOW_DAYS,
    refactor_threshold: int = DEFAULT_REFACTOR_THRESHOLD,
    rewrite_threshold: float = DEFAULT_REWRITE_THRESHOLD,
) -> dict:
    repo_path = Path(repo_path).resolve()
    repo_str = str(repo_path)
    ignore_patterns = load_ignore_patterns(repo_path)
    ai_commits = get_ai_commits(conn, repo_path=repo_str)

    if not ai_commits:
        return {"rework_events": 0}

    ai_hashes = {c["commit_hash"] for c in ai_commits}
    ai_files_map = {}
    for c in ai_commits:
        for f in c["files_changed"].split(","):
            if f:
                ai_files_map.setdefault(f, set()).add(c["commit_hash"])

    rework_count = 0

    for ai_commit in ai_commits:
        ai_date = _normalize_date(ai_commit["date"])
        window_end = ai_date + timedelta(days=time_window_days)
        later_commits = _get_commits_since(repo_path, ai_commit["commit_hash"])

        for later in later_commits:
            later_date = _normalize_date(later["date"])
            if later_date > window_end:
                continue
            # Don't count a commit as rework on itself
            if later["hash"] == ai_commit["commit_hash"]:
                continue

            files = _get_commit_files(repo_path, later["hash"])
            files = filter_files(files, ignore_patterns)
            file_count = len(files)

            if not files:
                continue

            if is_excluded_commit(files, later["message"], file_count, refactor_threshold):
                continue

            # Determine if this is AI-on-AI rework
            is_ai_on_ai = later["hash"] in ai_hashes

            overlapping_files = []
            rewrite_files = []

            for f in files:
                if f not in ai_files_map or ai_commit["commit_hash"] not in ai_files_map[f]:
                    continue

                # Check 1: Line-level overlap via git blame
                origins = get_blame_origins(repo_path, later["hash"], f)
                if ai_commit["commit_hash"] in origins:
                    overlapping_files.append(f)
                    continue

                # Check 2: File-level rewrite detection
                # If a large portion of the file is replaced, it's a rewrite
                # even if blame can't trace individual lines back
                added, removed = _get_file_diff_stats(repo_path, later["hash"], f)
                original_lines = _get_file_line_count(repo_path, later["hash"], f)
                if original_lines > 0 and removed > 0:
                    removal_ratio = removed / original_lines
                    if removal_ratio >= rewrite_threshold:
                        rewrite_files.append(f)

            all_affected = overlapping_files + rewrite_files
            if all_affected:
                if overlapping_files and rewrite_files:
                    reason = "line_overlap+file_rewrite"
                elif rewrite_files:
                    reason = "file_rewrite"
                else:
                    reason = "line_overlap"

                confidence = "medium"
                if is_ai_on_ai:
                    reason = f"ai_on_ai:{reason}"

                insert_rework_event(
                    conn, original_commit=ai_commit["commit_hash"],
                    rework_commit=later["hash"], repo_path=repo_str,
                    rework_date=later["date"], category="unclassified",
                    confidence=confidence,
                    files_affected=",".join(all_affected),
                    detection_reason=reason,
                )
                rework_count += 1

    return {"rework_events": rework_count}
