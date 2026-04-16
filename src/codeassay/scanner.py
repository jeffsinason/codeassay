"""Git history scanning and AI commit detection."""

import re
import subprocess
from pathlib import Path

from codeassay.db import (
    get_last_scanned_commit,
    insert_ai_commit,
    set_last_scanned_commit,
)
from codeassay.ignore import filter_files_csv, load_ignore_patterns

AI_TOOL_PATTERNS = [
    (re.compile(r"Co-Authored-By:.*Claude", re.IGNORECASE), "claude_code"),
    (re.compile(r"Co-Authored-By:.*Copilot", re.IGNORECASE), "copilot"),
    (re.compile(r"Co-Authored-By:.*GPT", re.IGNORECASE), "gpt"),
    (re.compile(r"Co-Authored-By:.*Gemini", re.IGNORECASE), "gemini"),
]

MANUAL_TAG_PATTERN = re.compile(r"AI-Assisted:\s*true", re.IGNORECASE)

CONFIDENCE_MAP = {
    "co_author_trailer": "high",
    "branch_pattern": "medium",
    "manual_tag": "high",
}

DELIMITER = "---AIQUALITY---"
LOG_FORMAT = f"%H{DELIMITER}%an{DELIMITER}%aI{DELIMITER}%B{DELIMITER}"


def detect_ai_tool(message: str) -> str | None:
    for pattern, tool in AI_TOOL_PATTERNS:
        if pattern.search(message):
            return tool
    if MANUAL_TAG_PATTERN.search(message):
        return "unknown"
    return None


def get_detection_confidence(method: str) -> str:
    return CONFIDENCE_MAP.get(method, "low")


def _get_detection_method(message: str) -> str:
    for pattern, _ in AI_TOOL_PATTERNS:
        if pattern.search(message):
            return "co_author_trailer"
    if MANUAL_TAG_PATTERN.search(message):
        return "manual_tag"
    return "heuristic"


def _get_changed_files(repo_path: Path, commit_hash: str) -> str:
    result = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit_hash],
        cwd=repo_path, capture_output=True, text=True,
    )
    files = [f for f in result.stdout.strip().split("\n") if f]
    return ",".join(files)


def parse_commit_log(repo_path: Path, since_commit: str | None = None) -> list[dict]:
    cmd = ["git", "log", f"--format={LOG_FORMAT}"]
    if since_commit:
        cmd.append(f"{since_commit}..HEAD")
    result = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True)
    if result.returncode != 0:
        return []
    commits = []
    raw = result.stdout.strip()
    if not raw:
        return []
    entries = raw.split(f"{DELIMITER}\n")
    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(DELIMITER)
        if len(parts) < 4:
            continue
        commit_hash = parts[0].strip()
        author = parts[1].strip()
        date = parts[2].strip()
        message = parts[3].strip()
        if not commit_hash:
            continue
        commits.append({"hash": commit_hash, "author": author, "date": date, "message": message})
    return commits


def scan_repo(repo_path: Path, conn, branch: str | None = None) -> dict:
    repo_path = Path(repo_path).resolve()
    repo_str = str(repo_path)
    ignore_patterns = load_ignore_patterns(repo_path)
    last_commit = get_last_scanned_commit(conn, repo_str)
    commits = parse_commit_log(repo_path, since_commit=last_commit)
    ai_count = 0
    for commit in commits:
        tool = detect_ai_tool(commit["message"])
        if tool is not None:
            method = _get_detection_method(commit["message"])
            confidence = get_detection_confidence(method)
            files = _get_changed_files(repo_path, commit["hash"])
            files = filter_files_csv(files, ignore_patterns)
            if not files:
                continue
            insert_ai_commit(
                conn, commit_hash=commit["hash"], repo_path=repo_str,
                author=commit["author"], date=commit["date"], message=commit["message"],
                tool=tool, detection_method=method, confidence=confidence, files_changed=files,
            )
            ai_count += 1
    if commits:
        set_last_scanned_commit(conn, repo_str, commits[0]["hash"])
    return {"total_commits": len(commits), "ai_commits": ai_count}
