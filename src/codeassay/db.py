"""SQLite database schema and data access for codeassay."""

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_commits (
    commit_hash TEXT NOT NULL,
    repo_path TEXT NOT NULL,
    author TEXT NOT NULL,
    date TEXT NOT NULL,
    message TEXT NOT NULL,
    tool TEXT NOT NULL,
    detection_method TEXT NOT NULL,
    confidence TEXT NOT NULL,
    detection_confidence INTEGER,
    files_changed TEXT NOT NULL,
    source TEXT,
    PRIMARY KEY (commit_hash, repo_path)
);

CREATE TABLE IF NOT EXISTS rework_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    original_commit TEXT NOT NULL,
    rework_commit TEXT NOT NULL,
    repo_path TEXT NOT NULL,
    rework_date TEXT NOT NULL,
    category TEXT NOT NULL,
    confidence TEXT NOT NULL,
    files_affected TEXT NOT NULL,
    detection_reason TEXT NOT NULL,
    UNIQUE(original_commit, rework_commit, repo_path)
);

CREATE TABLE IF NOT EXISTS scan_metadata (
    repo_path TEXT PRIMARY KEY,
    last_scanned_commit TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS commit_lines (
    commit_sha TEXT NOT NULL,
    repo_path TEXT NOT NULL,
    file TEXT NOT NULL,
    lines_added INTEGER NOT NULL,
    lines_survived INTEGER NOT NULL,
    measurement_window_end TEXT NOT NULL,
    PRIMARY KEY (commit_sha, repo_path, file)
);

CREATE TABLE IF NOT EXISTS author_baselines (
    repo_path TEXT NOT NULL,
    author_email TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    mean_value REAL NOT NULL,
    stddev_value REAL NOT NULL,
    sample_size INTEGER NOT NULL,
    last_updated_sha TEXT NOT NULL,
    PRIMARY KEY (repo_path, author_email, metric_name)
);
"""


def init_db(db_path: Path) -> None:
    """Create the database and tables if they don't exist. Applies idempotent migrations."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    # Idempotent migration: ensure ai_commits.source exists for legacy DBs.
    cols = [r[1] for r in conn.execute("PRAGMA table_info(ai_commits)")]
    if "source" not in cols:
        conn.execute("ALTER TABLE ai_commits ADD COLUMN source TEXT")
    if "detection_confidence" not in cols:
        conn.execute("ALTER TABLE ai_commits ADD COLUMN detection_confidence INTEGER")
    conn.commit()
    conn.close()


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Return a connection with Row factory enabled."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def insert_ai_commit(
    conn: sqlite3.Connection,
    *,
    commit_hash: str,
    repo_path: str,
    author: str,
    date: str,
    message: str,
    tool: str,
    detection_method: str,
    confidence: str,
    files_changed: str,
    source: str | None = None,
    detection_confidence: int | None = None,
) -> None:
    """Insert an AI commit, ignoring duplicates."""
    conn.execute(
        """INSERT OR IGNORE INTO ai_commits
           (commit_hash, repo_path, author, date, message, tool,
            detection_method, confidence, detection_confidence, files_changed, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (commit_hash, repo_path, author, date, message, tool,
         detection_method, confidence, detection_confidence, files_changed, source),
    )
    conn.commit()


def insert_rework_event(
    conn: sqlite3.Connection,
    *,
    original_commit: str,
    rework_commit: str,
    repo_path: str,
    rework_date: str,
    category: str,
    confidence: str,
    files_affected: str,
    detection_reason: str,
) -> None:
    """Insert a rework event, ignoring duplicates."""
    conn.execute(
        """INSERT OR IGNORE INTO rework_events
           (original_commit, rework_commit, repo_path, rework_date,
            category, confidence, files_affected, detection_reason)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (original_commit, rework_commit, repo_path, rework_date,
         category, confidence, files_affected, detection_reason),
    )
    conn.commit()


def get_ai_commits(
    conn: sqlite3.Connection, *, repo_path: str | None = None
) -> list[dict]:
    """Get AI commits, optionally filtered by repo."""
    if repo_path:
        rows = conn.execute(
            "SELECT * FROM ai_commits WHERE repo_path = ? ORDER BY date",
            (repo_path,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM ai_commits ORDER BY date"
        ).fetchall()
    return [dict(row) for row in rows]


def get_rework_events(
    conn: sqlite3.Connection, *, repo_path: str | None = None
) -> list[dict]:
    """Get rework events, optionally filtered by repo."""
    if repo_path:
        rows = conn.execute(
            "SELECT * FROM rework_events WHERE repo_path = ? ORDER BY rework_date",
            (repo_path,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM rework_events ORDER BY rework_date"
        ).fetchall()
    return [dict(row) for row in rows]


def get_last_scanned_commit(conn: sqlite3.Connection, repo_path: str) -> str | None:
    """Get the last scanned commit hash for a repo."""
    row = conn.execute(
        "SELECT last_scanned_commit FROM scan_metadata WHERE repo_path = ?",
        (repo_path,),
    ).fetchone()
    return row["last_scanned_commit"] if row else None


def set_last_scanned_commit(
    conn: sqlite3.Connection, repo_path: str, commit_hash: str
) -> None:
    """Set the last scanned commit for a repo (upsert)."""
    conn.execute(
        """INSERT INTO scan_metadata (repo_path, last_scanned_commit)
           VALUES (?, ?)
           ON CONFLICT(repo_path) DO UPDATE SET last_scanned_commit = ?""",
        (repo_path, commit_hash, commit_hash),
    )
    conn.commit()


def set_rework_override(
    conn: sqlite3.Connection, rework_commit: str, new_category: str
) -> None:
    """Override the classification of a rework event."""
    conn.execute(
        "UPDATE rework_events SET category = ? WHERE rework_commit = ?",
        (new_category, rework_commit),
    )
    conn.commit()


def insert_commit_line(
    conn: sqlite3.Connection,
    *,
    commit_sha: str,
    repo_path: str,
    file: str,
    lines_added: int,
    lines_survived: int,
    measurement_window_end: str,
) -> None:
    """Insert (or replace) a per-commit per-file line-survival record."""
    conn.execute(
        """INSERT OR REPLACE INTO commit_lines
           (commit_sha, repo_path, file, lines_added,
            lines_survived, measurement_window_end)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (commit_sha, repo_path, file, lines_added, lines_survived,
         measurement_window_end),
    )
    conn.commit()
