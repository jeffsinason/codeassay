"""v0.3 end-to-end: turnover + fingerprint both active in a single scan."""

import subprocess

from codeassay.db import get_ai_commits, get_author_baselines, init_db, get_connection
from codeassay.metrics import compute_metrics
from codeassay.scanner import scan_repo


def _commit(repo, filename, content, message, author="Test User <test@test.com>"):
    (repo / filename).write_text(content)
    subprocess.run(["git", "add", filename], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", message, f"--author={author}"],
                   cwd=repo, capture_output=True)


def test_v0_3_full_pipeline(tmp_repo):
    # Enable fingerprinting with lower min_prior so the test can trigger it
    (tmp_repo / ".codeassay.toml").write_text(
        "[fingerprint]\nenabled = true\nmin_prior_commits = 10\n"
    )
    # 12 baseline commits — small, simple, consistent
    for i in range(12):
        _commit(tmp_repo, f"norm{i}.py", "x = 1\n", f"feat: normal {i}")
    # 1 profile-marked AI commit
    _commit(
        tmp_repo, "ai.py", "y = 2\n",
        "feat: ai work\n\nCo-Authored-By: Claude <x@anthropic.com>",
    )
    # 1 outlier likely to trigger fingerprint
    _commit(
        tmp_repo, "out.py",
        "# comment line\n" * 60 + "result_variable = complex_helper_function(arg_alpha, arg_beta, arg_gamma)\n" * 15,
        "feat: outlier.\n\nSummary:\n- big refactor; dozens of changes; lots of documentation.\n"
        "Test plan:\n- comprehensive tests; thorough validation.\n",
    )
    # Rewrite one of the early files to drive turnover
    _commit(tmp_repo, "norm0.py", "totally different content\n", "refactor: rewrite norm0")

    db_path = tmp_repo / ".codeassay" / "quality.db"
    init_db(db_path)
    conn = get_connection(db_path)
    scan_repo(tmp_repo, conn)
    ai = get_ai_commits(conn, repo_path=str(tmp_repo.resolve()))
    metrics = compute_metrics(conn, repo_path=str(tmp_repo.resolve()),
                              total_commits=15)
    conn.close()

    # Assert profile caught the claude commit
    profile_hits = [c for c in ai if c.get("source", "").startswith("profile:claude_code")]
    assert len(profile_hits) == 1

    # Assert fingerprint caught at least one outlier
    fingerprint_hits = [c for c in ai if c.get("source", "").startswith("fingerprint:")]
    assert len(fingerprint_hits) >= 1

    # Assert baselines were built
    baselines = get_author_baselines(
        conn=get_connection(db_path),
        repo_path=str(tmp_repo.resolve()),
        author_email="test@test.com",
    )
    assert len(baselines) == 5
    assert all(b.sample_size >= 10 for b in baselines.values())

    # Assert turnover metrics exist and are sensible
    assert "turnover_ai" in metrics
    assert "turnover_human" in metrics
    assert metrics["turnover_ai"] >= 0
    assert metrics["turnover_human"] >= 0
