import subprocess

from codeassay.db import get_ai_commits, get_author_baselines
from codeassay.scanner import scan_repo


def _commit(repo, filename, content, message, author_name="Test User",
            author_email="test@test.com"):
    (repo / filename).write_text(content)
    subprocess.run(["git", "add", filename], cwd=repo, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", message,
         f"--author={author_name} <{author_email}>"],
        cwd=repo, capture_output=True,
    )


def test_scan_updates_baselines_for_known_author(tmp_repo, db_conn):
    # Make 25 small commits by the same author
    for i in range(25):
        _commit(tmp_repo, f"f{i}.py", "x = 1\n", f"feat: normal commit {i}")
    scan_repo(tmp_repo, db_conn)
    baselines = get_author_baselines(
        db_conn, repo_path=str(tmp_repo.resolve()),
        author_email="test@test.com",
    )
    assert len(baselines) == 5  # all 5 metrics populated
    for name in ("avg_diff_size", "comment_ratio", "identifier_entropy",
                 "punctuation_density", "message_length"):
        assert name in baselines
        assert baselines[name].sample_size >= 20


def test_scan_fingerprint_disabled_by_default_no_detection(tmp_repo, db_conn):
    """With default config (fingerprint disabled), unusual commits are NOT flagged."""
    # Human-normal commits to establish baseline
    for i in range(25):
        _commit(tmp_repo, f"f{i}.py", "x = 1\n", f"feat: normal commit {i}")
    # An outlier commit
    outlier = (
        "# extensive doc\n" * 50 +
        "result_identifier = some_function_name(arg_one, arg_two_here)\n" * 20
    )
    _commit(tmp_repo, "outlier.py", outlier,
            "feat: comprehensive refactor.\n\nSummary:\n- rewrite everything; add docs; expand; expand; expand.\n"
            "Test plan:\n- tests, tests, tests.")
    scan_repo(tmp_repo, db_conn)
    ai = get_ai_commits(db_conn, repo_path=str(tmp_repo.resolve()))
    # Fingerprint is off; no detection
    fingerprint_hits = [c for c in ai if c.get("source", "").startswith("fingerprint:")]
    assert fingerprint_hits == []


def test_scan_fingerprint_enabled_flags_outlier(tmp_repo, db_conn):
    """Flip fingerprint on; outlier commit is flagged."""
    (tmp_repo / ".codeassay.toml").write_text("[fingerprint]\nenabled = true\n")
    for i in range(25):
        _commit(tmp_repo, f"f{i}.py", "x = 1\n", f"feat: normal commit {i}")
    outlier = (
        "# extensive doc\n" * 50 +
        "result_identifier = some_function_name(arg_one, arg_two_here)\n" * 20
    )
    _commit(tmp_repo, "outlier.py", outlier,
            "feat: comprehensive refactor.\n\nSummary:\n- rewrite everything; add docs; expand; expand; expand.\n"
            "Test plan:\n- tests, tests, tests.")
    scan_repo(tmp_repo, db_conn)
    ai = get_ai_commits(db_conn, repo_path=str(tmp_repo.resolve()))
    fingerprint_hits = [c for c in ai if c.get("source", "").startswith("fingerprint:")]
    assert len(fingerprint_hits) >= 1
