"""Tests for codeassay.metrics."""

import pytest

from codeassay.db import insert_ai_commit, insert_rework_event
from codeassay.metrics import compute_metrics


def _seed_data(conn, repo="/tmp/repo"):
    for i, (hash_, tool) in enumerate([
        ("aaa111", "claude_code"),
        ("bbb222", "claude_code"),
        ("ccc333", "copilot"),
    ]):
        insert_ai_commit(
            conn, commit_hash=hash_, repo_path=repo, author="Test",
            date=f"2026-04-{10+i}T10:00:00", message=f"feat: thing {i}",
            tool=tool, detection_method="co_author_trailer", confidence="high",
            files_changed=f"src/file{i}.py",
        )
    insert_rework_event(
        conn, original_commit="aaa111", rework_commit="fix111", repo_path=repo,
        rework_date="2026-04-11T14:00:00", category="bug_fix", confidence="high",
        files_affected="src/file0.py", detection_reason="line_overlap",
    )
    insert_rework_event(
        conn, original_commit="bbb222", rework_commit="fix222", repo_path=repo,
        rework_date="2026-04-13T09:00:00", category="misunderstanding", confidence="medium",
        files_affected="src/file1.py", detection_reason="line_overlap",
    )


def test_compute_metrics_basic(db_conn):
    _seed_data(db_conn)
    m = compute_metrics(db_conn, repo_path="/tmp/repo", total_commits=10)
    assert m["ai_commit_count"] == 3
    assert m["total_commits"] == 10
    assert m["ai_commit_rate"] == 30.0
    assert m["rework_count"] == 2
    assert m["rework_rate"] == pytest.approx(66.7, abs=0.1)
    assert m["first_pass_success_rate"] == pytest.approx(33.3, abs=0.1)


def test_compute_metrics_by_category(db_conn):
    _seed_data(db_conn)
    m = compute_metrics(db_conn, repo_path="/tmp/repo", total_commits=10)
    assert m["rework_by_category"]["bug_fix"] == 1
    assert m["rework_by_category"]["misunderstanding"] == 1


def test_compute_metrics_by_tool(db_conn):
    _seed_data(db_conn)
    m = compute_metrics(db_conn, repo_path="/tmp/repo", total_commits=10)
    assert m["rework_by_tool"]["claude_code"] == 2
    assert m["rework_by_tool"]["copilot"] == 0


def test_compute_metrics_empty(db_conn):
    m = compute_metrics(db_conn, repo_path="/tmp/repo", total_commits=0)
    assert m["ai_commit_count"] == 0
    assert m["rework_count"] == 0
    assert m["ai_commit_rate"] == 0.0


def test_compute_metrics_top_rework_files(db_conn):
    _seed_data(db_conn)
    m = compute_metrics(db_conn, repo_path="/tmp/repo", total_commits=10)
    assert len(m["top_rework_files"]) >= 1
