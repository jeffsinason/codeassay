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


def test_ai_commits_has_source_column(tmp_path):
    db_path = tmp_path / "q.db"
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(ai_commits)")]
    assert "source" in cols


def test_legacy_db_gets_source_column_on_init(tmp_path):
    db_path = tmp_path / "q.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    legacy = sqlite3.connect(db_path)
    legacy.executescript(
        """CREATE TABLE ai_commits (
            commit_hash TEXT NOT NULL,
            repo_path TEXT NOT NULL,
            author TEXT NOT NULL,
            date TEXT NOT NULL,
            message TEXT NOT NULL,
            tool TEXT NOT NULL,
            detection_method TEXT NOT NULL,
            confidence TEXT NOT NULL,
            files_changed TEXT NOT NULL,
            PRIMARY KEY (commit_hash, repo_path)
        );"""
    )
    legacy.commit()
    legacy.close()
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(ai_commits)")]
    assert "source" in cols


def test_insert_ai_commit_accepts_source(db_conn):
    insert_ai_commit(
        db_conn, commit_hash="abc", repo_path="/r", author="a",
        date="2026-04-18T00:00:00Z", message="m", tool="claude_code",
        detection_method="profile", confidence="high",
        files_changed="a.py", source="profile:claude_code",
    )
    rows = get_ai_commits(db_conn, repo_path="/r")
    assert rows[0]["source"] == "profile:claude_code"


def test_insert_ai_commit_source_defaults_to_none(db_conn):
    insert_ai_commit(
        db_conn, commit_hash="def", repo_path="/r", author="a",
        date="2026-04-18T00:00:00Z", message="m", tool="claude_code",
        detection_method="co_author_trailer", confidence="high",
        files_changed="a.py",
    )
    rows = get_ai_commits(db_conn, repo_path="/r")
    assert rows[0]["source"] is None


def test_ai_commits_has_detection_confidence_column(tmp_path):
    db_path = tmp_path / "q.db"
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(ai_commits)")]
    assert "detection_confidence" in cols


def test_legacy_db_gets_detection_confidence_on_init(tmp_path):
    db_path = tmp_path / "q.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    legacy = sqlite3.connect(db_path)
    legacy.executescript(
        """CREATE TABLE ai_commits (
            commit_hash TEXT NOT NULL,
            repo_path TEXT NOT NULL,
            author TEXT NOT NULL,
            date TEXT NOT NULL,
            message TEXT NOT NULL,
            tool TEXT NOT NULL,
            detection_method TEXT NOT NULL,
            confidence TEXT NOT NULL,
            files_changed TEXT NOT NULL,
            source TEXT,
            PRIMARY KEY (commit_hash, repo_path)
        );"""
    )
    legacy.commit()
    legacy.close()
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(ai_commits)")]
    assert "detection_confidence" in cols


def test_insert_ai_commit_accepts_detection_confidence(db_conn):
    insert_ai_commit(
        db_conn, commit_hash="xyz", repo_path="/r", author="a",
        date="2026-04-18T00:00:00Z", message="m", tool="claude_code",
        detection_method="profile", confidence="high",
        files_changed="a.py", source="profile:claude_code",
        detection_confidence=90,
    )
    rows = get_ai_commits(db_conn, repo_path="/r")
    assert rows[0]["detection_confidence"] == 90


def test_commit_lines_table_exists(tmp_path):
    db_path = tmp_path / "q.db"
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(commit_lines)")]
    finally:
        conn.close()
    for expected in ["commit_sha", "repo_path", "file", "lines_added",
                     "lines_survived", "measurement_window_end"]:
        assert expected in cols, f"missing column: {expected}"


def test_author_baselines_table_exists(tmp_path):
    db_path = tmp_path / "q.db"
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(author_baselines)")]
    finally:
        conn.close()
    for expected in ["repo_path", "author_email", "metric_name",
                     "mean_value", "stddev_value", "sample_size",
                     "last_updated_sha"]:
        assert expected in cols, f"missing column: {expected}"


def test_legacy_db_gets_new_tables(tmp_path):
    """A DB created before v0.3 must get the new tables on re-init."""
    db_path = tmp_path / "q.db"
    legacy = sqlite3.connect(db_path)
    legacy.executescript("""
        CREATE TABLE ai_commits (
            commit_hash TEXT NOT NULL,
            repo_path TEXT NOT NULL,
            author TEXT, date TEXT, message TEXT,
            tool TEXT, detection_method TEXT, confidence TEXT,
            files_changed TEXT, source TEXT, detection_confidence INTEGER,
            PRIMARY KEY (commit_hash, repo_path)
        );
    """)
    legacy.commit()
    legacy.close()
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    finally:
        conn.close()
    assert "commit_lines" in tables
    assert "author_baselines" in tables
