"""Tests for codeassay.metrics."""

import pytest

from codeassay.db import insert_ai_commit, insert_rework_event
from codeassay.metrics import compute_metrics, compute_trend_data


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


def test_compute_trend_data(db_conn):
    _seed_data(db_conn)
    trend = compute_trend_data(db_conn, repo_path="/tmp/repo")
    assert len(trend) >= 1
    assert trend[0]["month"] == "2026-04"
    assert trend[0]["ai_commits"] == 3
    assert trend[0]["rework_events"] == 2


def test_compute_trend_data_empty(db_conn):
    trend = compute_trend_data(db_conn, repo_path="/tmp/repo")
    assert trend == []


def test_compute_trend_data_multiple_months(db_conn):
    _seed_data(db_conn)
    # Add a commit in a different month
    insert_ai_commit(
        db_conn, commit_hash="ddd444", repo_path="/tmp/repo", author="Test",
        date="2026-03-15T10:00:00", message="feat: march thing",
        tool="claude_code", detection_method="co_author_trailer",
        confidence="high", files_changed="src/march.py",
    )
    trend = compute_trend_data(db_conn, repo_path="/tmp/repo")
    assert len(trend) == 2
    assert trend[0]["month"] == "2026-03"
    assert trend[0]["ai_commits"] == 1
    assert trend[0]["rework_events"] == 0
    assert trend[1]["month"] == "2026-04"


def test_metrics_includes_turnover(db_conn):
    from codeassay.db import insert_ai_commit, insert_commit_line
    # One AI commit with heavy turnover
    insert_ai_commit(
        db_conn, commit_hash="ai1", repo_path="/r", author="a",
        date="2026-04-18T00:00:00Z", message="m", tool="claude_code",
        detection_method="profile", confidence="high",
        files_changed="a.py", source="profile:claude_code",
    )
    insert_commit_line(
        db_conn, commit_sha="ai1", repo_path="/r", file="a.py",
        lines_added=100, lines_survived=40,
        measurement_window_end="2026-04-18",
    )
    # One human commit with low turnover
    insert_commit_line(
        db_conn, commit_sha="h1", repo_path="/r", file="b.py",
        lines_added=100, lines_survived=90,
        measurement_window_end="2026-04-18",
    )
    db_conn.commit()
    m = compute_metrics(db_conn, repo_path="/r", total_commits=2)
    assert "turnover_ai" in m
    assert "turnover_human" in m
    assert "turnover_ratio" in m
    assert m["turnover_ai"] == pytest.approx(0.6, abs=0.01)
    assert m["turnover_human"] == pytest.approx(0.1, abs=0.01)
    assert m["turnover_ratio"] == pytest.approx(6.0, abs=0.01)


def test_trend_data_includes_monthly_turnover(db_conn):
    from codeassay.db import insert_ai_commit, insert_commit_line
    from codeassay.metrics import compute_trend_data
    insert_ai_commit(
        db_conn, commit_hash="ai1", repo_path="/r", author="a",
        date="2026-02-15T00:00:00Z", message="m", tool="claude_code",
        detection_method="profile", confidence="high",
        files_changed="a.py", source="profile:claude_code",
    )
    insert_commit_line(
        db_conn, commit_sha="ai1", repo_path="/r", file="a.py",
        lines_added=100, lines_survived=50,
        measurement_window_end="2026-02-28",
    )
    db_conn.commit()
    trend = compute_trend_data(db_conn, repo_path="/r")
    feb = next((t for t in trend if t["month"] == "2026-02"), None)
    assert feb is not None
    assert "turnover_ai" in feb
    assert feb["turnover_ai"] == pytest.approx(0.5, abs=0.01)
