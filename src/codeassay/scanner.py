"""Git history scanning. AI commit detection is delegated to codeassay.detection."""

from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path

from codeassay.db import (
    get_last_scanned_commit,
    insert_ai_commit,
    set_last_scanned_commit,
)
from codeassay.detection import classify
from codeassay.detection.config import load_config
from codeassay.detection.profiles import load_profiles
from codeassay.ignore import filter_files_csv, load_ignore_patterns

DELIMITER = "---AIQUALITY---"
LOG_FORMAT = f"%H{DELIMITER}%an{DELIMITER}%ae{DELIMITER}%aI{DELIMITER}%B{DELIMITER}"


# ---- Back-compat shims (kept so old tests still pass) ----

_LEGACY_TOOL_PATTERNS = [
    (re.compile(r"Co-Authored-By:.*Claude", re.IGNORECASE), "claude_code"),
    (re.compile(r"Co-Authored-By:.*Copilot", re.IGNORECASE), "copilot"),
    (re.compile(r"Co-Authored-By:.*GPT", re.IGNORECASE), "gpt"),
    (re.compile(r"Co-Authored-By:.*Gemini", re.IGNORECASE), "gemini"),
]
_MANUAL_TAG_PATTERN = re.compile(r"AI-Assisted:\s*true", re.IGNORECASE)
_LEGACY_CONFIDENCE = {
    "co_author_trailer": "high",
    "branch_pattern": "medium",
    "manual_tag": "high",
}


def detect_ai_tool(message: str) -> str | None:
    """Back-compat shim; new code should use codeassay.detection.classify()."""
    for pattern, tool in _LEGACY_TOOL_PATTERNS:
        if pattern.search(message):
            return tool
    if _MANUAL_TAG_PATTERN.search(message):
        return "unknown"
    return None


def get_detection_confidence(method: str) -> str:
    return _LEGACY_CONFIDENCE.get(method, "low")


# ---- Log parsing ----

def parse_commit_log(repo_path: Path, since_commit: str | None = None) -> list[dict]:
    cmd = ["git", "log", f"--format={LOG_FORMAT}"]
    if since_commit:
        cmd.append(f"{since_commit}..HEAD")
    result = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True)
    if result.returncode != 0:
        return []
    raw = result.stdout.strip()
    if not raw:
        return []
    commits = []
    for entry in raw.split(f"{DELIMITER}\n"):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(DELIMITER)
        if len(parts) < 5:
            continue
        commit_hash, author, author_email, date, message = (p.strip() for p in parts[:5])
        if not commit_hash:
            continue
        commits.append({
            "hash": commit_hash,
            "author": author,
            "author_email": author_email,
            "date": date,
            "message": message,
        })
    return commits


def _get_changed_files(repo_path: Path, commit_hash: str) -> str:
    result = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit_hash],
        cwd=repo_path, capture_output=True, text=True,
    )
    files = [f for f in result.stdout.strip().split("\n") if f]
    return ",".join(files)


def _branches_containing(repo_path: Path, commit_hash: str) -> set[str]:
    result = subprocess.run(
        ["git", "branch", "--contains", commit_hash, "--format=%(refname:short)"],
        cwd=repo_path, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return set()
    return {b.strip() for b in result.stdout.splitlines() if b.strip()}


def _diff_stats(repo_path: Path, commit_hash: str) -> list[dict]:
    """Per-file numstat for a commit, plus file size after the commit."""
    numstat = subprocess.run(
        ["git", "show", "--numstat", "--format=", commit_hash],
        cwd=repo_path, capture_output=True, text=True,
    )
    stats = []
    if numstat.returncode != 0:
        return stats
    for line in numstat.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added_s, removed_s, path = parts
        if added_s == "-" or removed_s == "-":
            continue  # binary file
        cat = subprocess.run(
            ["git", "show", f"{commit_hash}:{path}"],
            cwd=repo_path, capture_output=True, text=True,
        )
        size = len(cat.stdout.splitlines()) if cat.returncode == 0 else 0
        stats.append({
            "path": path,
            "added": int(added_s),
            "removed": int(removed_s),
            "file_size": size,
        })
    return stats


def _seconds_between(commit_later: dict, commit_earlier: dict | None) -> int | None:
    if commit_earlier is None:
        return None
    try:
        a = datetime.fromisoformat(commit_later["date"])
        b = datetime.fromisoformat(commit_earlier["date"])
    except (ValueError, TypeError, KeyError):
        return None
    return int((a - b).total_seconds())


# ---- Scan orchestration ----

def scan_repo(
    repo_path: Path, conn, branch: str | None = None,
    *, dry_run: bool = False, force_scorer: bool = False,
) -> dict:
    repo_path = Path(repo_path).resolve()
    repo_str = str(repo_path)
    ignore_patterns = load_ignore_patterns(repo_path)
    config = load_config(repo_path)
    if force_scorer:
        config.score.enabled = True
    profiles = load_profiles(disabled=config.disabled_profiles)

    last_commit = get_last_scanned_commit(conn, repo_str) if not dry_run else None
    commits = parse_commit_log(repo_path, since_commit=last_commit)
    ai_count = 0

    needs_branches = bool(config.branch_rules) or any(p.branch_rules for p in profiles)
    scorer_on = config.score.enabled

    chronological = list(reversed(commits))
    prior = None
    for commit in chronological:
        commit["branches"] = (
            _branches_containing(repo_path, commit["hash"]) if needs_branches else set()
        )
        diff_stats = _diff_stats(repo_path, commit["hash"]) if scorer_on else []
        seconds_since_prior = _seconds_between(commit, prior) if scorer_on else None
        detection = classify(
            commit, config=config, profiles=profiles,
            diff_stats=diff_stats, seconds_since_prior=seconds_since_prior,
        )
        prior = commit
        if detection is None:
            continue

        files = _get_changed_files(repo_path, commit["hash"])
        files = filter_files_csv(files, ignore_patterns)
        if not files:
            continue
        ai_count += 1
        if dry_run:
            print(
                f"would store: {commit['hash'][:8]} tool={detection.tool} "
                f"source={detection.source}"
            )
            continue
        insert_ai_commit(
            conn,
            commit_hash=commit["hash"],
            repo_path=repo_str,
            author=commit["author"],
            date=commit["date"],
            message=commit["message"],
            tool=detection.tool,
            detection_method=detection.method,
            confidence=detection.confidence,
            files_changed=files,
            source=detection.source,
        )

    if commits and not dry_run:
        set_last_scanned_commit(conn, repo_str, commits[0]["hash"])
    return {"total_commits": len(commits), "ai_commits": ai_count}
