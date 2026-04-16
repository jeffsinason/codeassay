"""Tests for codeassay.rework."""

import subprocess
from datetime import datetime, timedelta

from codeassay.db import get_ai_commits, get_rework_events, insert_ai_commit
from codeassay.rework import (
    detect_rework,
    is_excluded_commit,
    get_blame_origins,
)


def _commit(repo, filename, content, message, co_author=None):
    (repo / filename).write_text(content)
    subprocess.run(["git", "add", filename], cwd=repo, capture_output=True)
    full_msg = message
    if co_author:
        full_msg += f"\n\nCo-Authored-By: {co_author}"
    subprocess.run(
        ["git", "commit", "-m", full_msg], cwd=repo, capture_output=True
    )
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    )
    return result.stdout.strip()


def test_is_excluded_dependency_update():
    assert is_excluded_commit(["requirements.txt"], "chore: update deps", 1) is True
    assert is_excluded_commit(["package-lock.json"], "chore: npm update", 1) is True


def test_is_excluded_refactoring_sweep():
    files = [f"src/file{i}.py" for i in range(12)]
    assert is_excluded_commit(files, "refactor: rename across codebase", 12) is True


def test_is_not_excluded_normal_fix():
    assert is_excluded_commit(["src/foo.py"], "fix: bug in foo", 1) is False


def test_detect_rework_finds_line_overlap(tmp_repo, db_conn):
    ai_hash = _commit(
        tmp_repo, "feature.py", "def greet():\n    return 'hello'\n",
        "feat: add greet",
        co_author="Claude <noreply@anthropic.com>",
    )
    insert_ai_commit(
        db_conn, commit_hash=ai_hash, repo_path=str(tmp_repo),
        author="Test", date=datetime.now().isoformat(),
        message="feat: add greet", tool="claude_code",
        detection_method="co_author_trailer", confidence="high",
        files_changed="feature.py",
    )
    _commit(
        tmp_repo, "feature.py", "def greet():\n    return 'hi there'\n",
        "fix: correct greeting",
    )
    result = detect_rework(tmp_repo, db_conn)
    assert result["rework_events"] >= 1


def test_detect_rework_ignores_excluded(tmp_repo, db_conn):
    ai_hash = _commit(
        tmp_repo, "requirements.txt", "flask==2.0\n",
        "chore: add deps",
        co_author="Claude <noreply@anthropic.com>",
    )
    insert_ai_commit(
        db_conn, commit_hash=ai_hash, repo_path=str(tmp_repo),
        author="Test", date=datetime.now().isoformat(),
        message="chore: add deps", tool="claude_code",
        detection_method="co_author_trailer", confidence="high",
        files_changed="requirements.txt",
    )
    _commit(
        tmp_repo, "requirements.txt", "flask==2.1\n",
        "chore: bump flask",
    )
    result = detect_rework(tmp_repo, db_conn)
    assert result["rework_events"] == 0


def test_detect_rework_ai_on_ai(tmp_repo, db_conn):
    """AI commit that modifies another AI commit's lines is tracked as rework."""
    ai_hash1 = _commit(
        tmp_repo, "feature.py", "def greet():\n    return 'hello'\n",
        "feat: add greet",
        co_author="Claude <noreply@anthropic.com>",
    )
    insert_ai_commit(
        db_conn, commit_hash=ai_hash1, repo_path=str(tmp_repo),
        author="Test", date=datetime.now().isoformat(),
        message="feat: add greet", tool="claude_code",
        detection_method="co_author_trailer", confidence="high",
        files_changed="feature.py",
    )
    # Second AI commit fixes the first
    ai_hash2 = _commit(
        tmp_repo, "feature.py", "def greet():\n    return 'hi there'\n",
        "fix: correct greeting",
        co_author="Claude <noreply@anthropic.com>",
    )
    insert_ai_commit(
        db_conn, commit_hash=ai_hash2, repo_path=str(tmp_repo),
        author="Test", date=datetime.now().isoformat(),
        message="fix: correct greeting", tool="claude_code",
        detection_method="co_author_trailer", confidence="high",
        files_changed="feature.py",
    )
    result = detect_rework(tmp_repo, db_conn)
    assert result["rework_events"] >= 1
    events = get_rework_events(db_conn, repo_path=str(tmp_repo))
    assert any("ai_on_ai" in e["detection_reason"] for e in events)


def test_detect_rework_file_rewrite(tmp_repo, db_conn):
    """Large file rewrite is detected as rework (via blame or rewrite heuristic)."""
    # AI writes a file with substantial content
    original = "\n".join([f"line_{i} = {i}" for i in range(20)]) + "\n"
    ai_hash = _commit(
        tmp_repo, "big_file.py", original,
        "feat: add big file",
        co_author="Claude <noreply@anthropic.com>",
    )
    insert_ai_commit(
        db_conn, commit_hash=ai_hash, repo_path=str(tmp_repo),
        author="Test", date=datetime.now().isoformat(),
        message="feat: add big file", tool="claude_code",
        detection_method="co_author_trailer", confidence="high",
        files_changed="big_file.py",
    )
    # Complete rewrite — all lines replaced
    rewritten = "\n".join([f"new_line_{i} = '{i}'" for i in range(20)]) + "\n"
    _commit(
        tmp_repo, "big_file.py", rewritten,
        "refactor: completely rewrite big file",
    )
    result = detect_rework(tmp_repo, db_conn)
    assert result["rework_events"] >= 1
    events = get_rework_events(db_conn, repo_path=str(tmp_repo))
    # Detected via line_overlap (blame traces back) or file_rewrite fallback
    assert any(
        "line_overlap" in e["detection_reason"] or "file_rewrite" in e["detection_reason"]
        for e in events
    )


def test_detect_rework_file_delete_recreate(tmp_repo, db_conn):
    """File deleted and recreated is caught by file_rewrite heuristic."""
    # AI writes a file
    original = "\n".join([f"line_{i} = {i}" for i in range(20)]) + "\n"
    ai_hash = _commit(
        tmp_repo, "module.py", original,
        "feat: add module",
        co_author="Claude <noreply@anthropic.com>",
    )
    insert_ai_commit(
        db_conn, commit_hash=ai_hash, repo_path=str(tmp_repo),
        author="Test", date=datetime.now().isoformat(),
        message="feat: add module", tool="claude_code",
        detection_method="co_author_trailer", confidence="high",
        files_changed="module.py",
    )
    # Delete and recreate with completely different content
    import os
    os.remove(tmp_repo / "module.py")
    subprocess.run(["git", "add", "module.py"], cwd=tmp_repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "remove module"], cwd=tmp_repo, capture_output=True)
    # Recreate
    new_content = "\n".join([f"class New{i}: pass" for i in range(20)]) + "\n"
    (tmp_repo / "module.py").write_text(new_content)
    subprocess.run(["git", "add", "module.py"], cwd=tmp_repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "recreate module differently"], cwd=tmp_repo, capture_output=True)
    result = detect_rework(tmp_repo, db_conn)
    # The delete commit should be caught — it removes all AI-authored lines
    assert result["rework_events"] >= 1
