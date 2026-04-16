"""Tests for codeassay.db."""

import sqlite3
from pathlib import Path

from codeassay.db import (
    get_connection,
    init_db,
    insert_ai_commit,
    insert_rework_event,
    get_ai_commits,
    get_rework_events,
    get_last_scanned_commit,
    set_last_scanned_commit,
    set_rework_override,
)


def test_init_db_creates_tables(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()
    assert "ai_commits" in tables
    assert "rework_events" in tables
    assert "scan_metadata" in tables


def test_insert_and_get_ai_commit(db_conn):
    insert_ai_commit(
        db_conn,
        commit_hash="abc123",
        repo_path="/tmp/repo",
        author="Test User",
        date="2026-04-16T10:00:00",
        message="feat: add feature",
        tool="claude_code",
        detection_method="co_author_trailer",
        confidence="high",
        files_changed="src/foo.py,src/bar.py",
    )
    commits = get_ai_commits(db_conn, repo_path="/tmp/repo")
    assert len(commits) == 1
    assert commits[0]["commit_hash"] == "abc123"
    assert commits[0]["tool"] == "claude_code"


def test_insert_and_get_rework_event(db_conn):
    insert_ai_commit(
        db_conn,
        commit_hash="abc123",
        repo_path="/tmp/repo",
        author="Test",
        date="2026-04-16T10:00:00",
        message="feat: add thing",
        tool="claude_code",
        detection_method="co_author_trailer",
        confidence="high",
        files_changed="src/foo.py",
    )
    insert_rework_event(
        db_conn,
        original_commit="abc123",
        rework_commit="def456",
        repo_path="/tmp/repo",
        rework_date="2026-04-16T12:00:00",
        category="bug_fix",
        confidence="high",
        files_affected="src/foo.py",
        detection_reason="line_overlap",
    )
    events = get_rework_events(db_conn, repo_path="/tmp/repo")
    assert len(events) == 1
    assert events[0]["category"] == "bug_fix"
    assert events[0]["original_commit"] == "abc123"


def test_last_scanned_commit(db_conn):
    assert get_last_scanned_commit(db_conn, "/tmp/repo") is None
    set_last_scanned_commit(db_conn, "/tmp/repo", "abc123")
    assert get_last_scanned_commit(db_conn, "/tmp/repo") == "abc123"
    set_last_scanned_commit(db_conn, "/tmp/repo", "def456")
    assert get_last_scanned_commit(db_conn, "/tmp/repo") == "def456"


def test_rework_override(db_conn):
    insert_ai_commit(
        db_conn,
        commit_hash="abc123",
        repo_path="/tmp/repo",
        author="Test",
        date="2026-04-16T10:00:00",
        message="feat: thing",
        tool="claude_code",
        detection_method="co_author_trailer",
        confidence="high",
        files_changed="src/foo.py",
    )
    insert_rework_event(
        db_conn,
        original_commit="abc123",
        rework_commit="def456",
        repo_path="/tmp/repo",
        rework_date="2026-04-16T12:00:00",
        category="bug_fix",
        confidence="medium",
        files_affected="src/foo.py",
        detection_reason="line_overlap",
    )
    set_rework_override(db_conn, "def456", "misunderstanding")
    events = get_rework_events(db_conn, repo_path="/tmp/repo")
    assert events[0]["category"] == "misunderstanding"


def test_duplicate_commit_ignored(db_conn):
    for _ in range(2):
        insert_ai_commit(
            db_conn,
            commit_hash="abc123",
            repo_path="/tmp/repo",
            author="Test",
            date="2026-04-16T10:00:00",
            message="feat: thing",
            tool="claude_code",
            detection_method="co_author_trailer",
            confidence="high",
            files_changed="src/foo.py",
        )
    commits = get_ai_commits(db_conn, repo_path="/tmp/repo")
    assert len(commits) == 1
