import subprocess
import sys


def _make_commit(repo, filename, content, message):
    (repo / filename).write_text(content)
    subprocess.run(["git", "add", filename], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo, capture_output=True)


def test_detect_test_reports_profile_hit(tmp_repo):
    _make_commit(
        tmp_repo, "foo.py", "x\n",
        "feat: foo\n\nCo-Authored-By: Claude <x@a.com>",
    )
    hash_ = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_repo, capture_output=True, text=True,
    ).stdout.strip()
    result = subprocess.run(
        [sys.executable, "-m", "codeassay", "detect-test", hash_],
        cwd=tmp_repo, capture_output=True, text=True,
    )
    assert result.returncode == 0
    out = result.stdout.lower()
    assert "claude_code" in out
    assert "profile" in out


def test_detect_test_reports_human(tmp_repo):
    _make_commit(tmp_repo, "foo.py", "x\n", "feat: foo by a human")
    hash_ = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_repo, capture_output=True, text=True,
    ).stdout.strip()
    result = subprocess.run(
        [sys.executable, "-m", "codeassay", "detect-test", hash_],
        cwd=tmp_repo, capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "no match" in result.stdout.lower() or "human" in result.stdout.lower()
