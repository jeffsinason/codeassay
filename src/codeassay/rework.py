"""Rework detection engine — identifies commits that modify AI-authored code."""

import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from codeassay.db import get_ai_commits, insert_rework_event

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
        if len(parts) >= 3 and len(parts[0]) == 40:
            current_origin = parts[0]
            current_blame_line = int(parts[2])
        if current_origin and current_blame_line in changed_lines:
            origins.add(current_origin)

    return origins


def _get_commit_files(repo_path: Path, commit_hash: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit_hash],
        cwd=repo_path, capture_output=True, text=True,
    )
    return [f for f in result.stdout.strip().split("\n") if f]


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


def detect_rework(
    repo_path: Path, conn,
    time_window_days: int = DEFAULT_TIME_WINDOW_DAYS,
    refactor_threshold: int = DEFAULT_REFACTOR_THRESHOLD,
) -> dict:
    repo_path = Path(repo_path).resolve()
    repo_str = str(repo_path)
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
        ai_date = datetime.fromisoformat(ai_commit["date"])
        if ai_date.tzinfo is not None:
            ai_date = datetime(*ai_date.utctimetuple()[:6])
        window_end = ai_date + timedelta(days=time_window_days)
        later_commits = _get_commits_since(repo_path, ai_commit["commit_hash"])

        for later in later_commits:
            later_date = datetime.fromisoformat(later["date"])
            # Normalize to naive UTC for comparison
            if later_date.tzinfo is not None:
                later_date = later_date.utctimetuple()
                later_date = datetime(*later_date[:6])
            if later_date > window_end.replace(tzinfo=None):
                continue
            if later["hash"] in ai_hashes:
                continue

            files = _get_commit_files(repo_path, later["hash"])
            file_count = len(files)

            if is_excluded_commit(files, later["message"], file_count, refactor_threshold):
                continue

            overlapping_files = []
            for f in files:
                if f in ai_files_map and ai_commit["commit_hash"] in ai_files_map[f]:
                    origins = get_blame_origins(repo_path, later["hash"], f)
                    if ai_commit["commit_hash"] in origins:
                        overlapping_files.append(f)

            if overlapping_files:
                insert_rework_event(
                    conn, original_commit=ai_commit["commit_hash"],
                    rework_commit=later["hash"], repo_path=repo_str,
                    rework_date=later["date"], category="unclassified",
                    confidence="medium", files_affected=",".join(overlapping_files),
                    detection_reason="line_overlap",
                )
                rework_count += 1

    return {"rework_events": rework_count}
