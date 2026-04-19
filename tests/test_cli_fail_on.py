import subprocess
import sys


def _make_commit(repo, filename, content, message, co_author=None):
    (repo / filename).write_text(content)
    subprocess.run(["git", "add", filename], cwd=repo, capture_output=True)
    msg = message + (f"\n\nCo-Authored-By: {co_author}" if co_author else "")
    subprocess.run(["git", "commit", "-m", msg], cwd=repo, capture_output=True)


def test_fail_on_turnover_red_exits_1_when_exceeded(tmp_repo):
    # Config with aggressive red threshold
    (tmp_repo / ".codeassay.toml").write_text(
        "[turnover]\nred_threshold = 0.01\n"
    )
    # Create AI commit whose lines will be mostly discarded
    _make_commit(
        tmp_repo, "a.py", "a\nb\nc\nd\ne\n",
        "feat: add a", co_author="Claude <x@anthropic.com>",
    )
    _make_commit(tmp_repo, "a.py", "x\ny\nz\n", "rewrite a")
    r = subprocess.run(
        [sys.executable, "-m", "codeassay", "scan", str(tmp_repo),
         "--fail-on=turnover-red"],
        capture_output=True, text=True,
    )
    assert r.returncode == 1
    assert "turnover" in r.stderr.lower() or "turnover" in r.stdout.lower()


def test_fail_on_turnover_red_exits_0_when_below(tmp_repo):
    (tmp_repo / ".codeassay.toml").write_text(
        "[turnover]\nred_threshold = 0.9\n"
    )
    _make_commit(
        tmp_repo, "a.py", "a\nb\nc\n",
        "feat: a", co_author="Claude <x@anthropic.com>",
    )
    r = subprocess.run(
        [sys.executable, "-m", "codeassay", "scan", str(tmp_repo),
         "--fail-on=turnover-red"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
