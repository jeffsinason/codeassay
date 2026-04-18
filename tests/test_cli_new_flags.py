import subprocess
import sys


def _make_commit(repo, filename, content, message, co_author=None):
    (repo / filename).write_text(content)
    subprocess.run(["git", "add", filename], cwd=repo, capture_output=True)
    msg = message + (f"\n\nCo-Authored-By: {co_author}" if co_author else "")
    subprocess.run(["git", "commit", "-m", msg], cwd=repo, capture_output=True)


def test_scan_dry_run_does_not_write_db(tmp_repo):
    _make_commit(
        tmp_repo, "foo.py", "x\n", "feat: foo",
        co_author="Claude <x@a.com>",
    )
    result = subprocess.run(
        [sys.executable, "-m", "codeassay", "scan", str(tmp_repo), "--dry-run"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    db = tmp_repo / ".codeassay" / "quality.db"
    # DB may or may not exist after init, but the ai_commits table should be empty.
    if db.exists():
        import sqlite3
        conn = sqlite3.connect(db)
        rows = conn.execute("SELECT COUNT(*) FROM ai_commits").fetchone()[0]
        conn.close()
        assert rows == 0


def test_scan_with_scorer_flag_runs_scorer(tmp_repo):
    """--with-scorer should surface commits that profiles miss via probabilistic scoring."""
    # Pre-configure a very low threshold so a realistic message body scores above it.
    (tmp_repo / ".codeassay.toml").write_text(
        '[score]\nenabled = false\n'  # scorer off in config; --with-scorer should force it on
    )
    _make_commit(
        tmp_repo, "foo.py", "a\nb\nc\nd\ne\nf\ng\nh\n",
        "feat: add structured feature 🤖\n\nSummary:\n- x\n- y\n\nTest plan:\n- run",
    )
    result = subprocess.run(
        [sys.executable, "-m", "codeassay", "scan", str(tmp_repo), "--with-scorer"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    db = tmp_repo / ".codeassay" / "quality.db"
    import sqlite3
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT source FROM ai_commits WHERE source LIKE 'score:%'"
    ).fetchall()
    conn.close()
    assert len(rows) >= 1


def test_commits_source_filter(tmp_repo):
    _make_commit(
        tmp_repo, "a.py", "x\n", "feat: a",
        co_author="Claude <x@a.com>",
    )
    subprocess.run(
        [sys.executable, "-m", "codeassay", "scan", str(tmp_repo)],
        capture_output=True, text=True, check=True,
    )
    result = subprocess.run(
        [sys.executable, "-m", "codeassay", "commits", "--source", "profile:*"],
        cwd=tmp_repo, capture_output=True, text=True,
    )
    assert result.returncode == 0
    # Should list the one AI commit
    assert "feat: a" in result.stdout


def test_commits_source_filter_excludes(tmp_repo):
    _make_commit(
        tmp_repo, "a.py", "x\n", "feat: a",
        co_author="Claude <x@a.com>",
    )
    subprocess.run(
        [sys.executable, "-m", "codeassay", "scan", str(tmp_repo)],
        capture_output=True, text=True, check=True,
    )
    result = subprocess.run(
        [sys.executable, "-m", "codeassay", "commits", "--source", "score:*"],
        cwd=tmp_repo, capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "feat: a" not in result.stdout
