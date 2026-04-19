"""Unit tests for turnover line-survival computation."""

import subprocess
from pathlib import Path

from codeassay.turnover import lines_added_by_commit, lines_survived_for_commit


def _commit(repo: Path, filename: str, content: str, message: str) -> str:
    (repo / filename).write_text(content)
    subprocess.run(["git", "add", filename], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo, capture_output=True)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    return sha


def test_lines_added_by_commit_new_file(tmp_repo):
    sha = _commit(tmp_repo, "a.py", "line1\nline2\nline3\n", "add a.py")
    added = lines_added_by_commit(tmp_repo, sha, "a.py")
    assert added == 3


def test_lines_added_by_commit_modified(tmp_repo):
    _commit(tmp_repo, "a.py", "x\ny\n", "initial")
    sha = _commit(tmp_repo, "a.py", "x\ny\nz\nw\n", "append")
    added = lines_added_by_commit(tmp_repo, sha, "a.py")
    assert added == 2


def test_lines_survived_full_survival(tmp_repo):
    sha = _commit(tmp_repo, "a.py", "alpha\nbravo\ncharlie\n", "add a.py")
    survived = lines_survived_for_commit(tmp_repo, sha, "a.py", as_of="HEAD")
    assert survived == 3


def test_lines_survived_partial(tmp_repo):
    sha = _commit(tmp_repo, "a.py", "alpha\nbravo\ncharlie\n", "add a.py")
    _commit(tmp_repo, "a.py", "alpha\nreplaced\ncharlie\n", "replace bravo")
    survived = lines_survived_for_commit(tmp_repo, sha, "a.py", as_of="HEAD")
    assert survived == 2  # alpha and charlie still trace back to sha


def test_lines_survived_zero_if_file_deleted(tmp_repo):
    sha = _commit(tmp_repo, "a.py", "x\ny\n", "add a.py")
    subprocess.run(["git", "rm", "a.py"], cwd=tmp_repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "rm a.py"],
                   cwd=tmp_repo, capture_output=True)
    survived = lines_survived_for_commit(tmp_repo, sha, "a.py", as_of="HEAD")
    assert survived == 0


def test_lines_survived_full_rewrite(tmp_repo):
    sha = _commit(tmp_repo, "a.py", "a\nb\nc\n", "add a.py")
    _commit(tmp_repo, "a.py", "x\ny\nz\n", "rewrite a.py")
    survived = lines_survived_for_commit(tmp_repo, sha, "a.py", as_of="HEAD")
    assert survived == 0


from datetime import date, timedelta
from codeassay.turnover import (
    CommitLineRecord, compute_turnover_metrics, TurnoverSummary,
)


def test_turnover_zero_commits():
    summary = compute_turnover_metrics([], ai_shas=set())
    assert summary.ai_turnover == 0.0
    assert summary.human_turnover == 0.0
    assert summary.ai_turnover_ratio is None  # no human baseline


def test_turnover_all_survived():
    records = [
        CommitLineRecord(commit_sha="a", file="f", lines_added=10, lines_survived=10),
        CommitLineRecord(commit_sha="b", file="f", lines_added=5, lines_survived=5),
    ]
    summary = compute_turnover_metrics(records, ai_shas={"a"})
    assert summary.human_turnover == 0.0
    assert summary.ai_turnover == 0.0


def test_turnover_half_discarded():
    records = [
        CommitLineRecord(commit_sha="ai1", file="f", lines_added=100, lines_survived=50),
        CommitLineRecord(commit_sha="h1", file="f", lines_added=100, lines_survived=80),
    ]
    summary = compute_turnover_metrics(records, ai_shas={"ai1"})
    assert summary.ai_turnover == 0.5
    assert summary.human_turnover == 0.2
    assert summary.ai_turnover_ratio == 2.5


def test_turnover_aggregates_multiple_files_per_commit():
    records = [
        CommitLineRecord(commit_sha="ai1", file="a.py", lines_added=50, lines_survived=0),
        CommitLineRecord(commit_sha="ai1", file="b.py", lines_added=50, lines_survived=50),
    ]
    summary = compute_turnover_metrics(records, ai_shas={"ai1"})
    assert summary.ai_turnover == 0.5  # 50 of 100 discarded
    assert summary.human_turnover == 0.0
    assert summary.ai_turnover_ratio is None  # no human lines


def test_turnover_ratio_none_when_human_zero_turnover():
    records = [
        CommitLineRecord(commit_sha="ai1", file="f", lines_added=10, lines_survived=5),
        CommitLineRecord(commit_sha="h1", file="f", lines_added=10, lines_survived=10),
    ]
    summary = compute_turnover_metrics(records, ai_shas={"ai1"})
    assert summary.ai_turnover == 0.5
    assert summary.human_turnover == 0.0
    assert summary.ai_turnover_ratio is None  # division by zero guarded
