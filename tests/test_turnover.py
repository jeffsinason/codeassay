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
