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


def test_detect_test_fingerprint_breakdown(tmp_repo):
    (tmp_repo / ".codeassay.toml").write_text(
        "[fingerprint]\nenabled = true\nmin_prior_commits = 5\n"
    )
    # Seed 10 baseline commits
    for i in range(10):
        (tmp_repo / f"f{i}.py").write_text("x = 1\n")
        subprocess.run(["git", "add", f"f{i}.py"], cwd=tmp_repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", f"feat: f{i}"],
                       cwd=tmp_repo, capture_output=True)
    # Now an outlier
    (tmp_repo / "outlier.py").write_text(
        "# doc\n" * 80 + "x = 1\n" * 5
    )
    subprocess.run(["git", "add", "outlier.py"], cwd=tmp_repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "feat: outlier.\n\nSummary:\n- lots.\n"],
                   cwd=tmp_repo, capture_output=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_repo,
                         capture_output=True, text=True).stdout.strip()
    # Must have scanned first so baselines exist
    subprocess.run([sys.executable, "-m", "codeassay", "scan", str(tmp_repo)],
                   capture_output=True, text=True, check=True)
    r = subprocess.run(
        [sys.executable, "-m", "codeassay", "detect-test", sha],
        cwd=tmp_repo, capture_output=True, text=True,
    )
    # Whether fingerprint fires depends on baselines, but the command MUST succeed
    assert r.returncode == 0
    # If it fired, output should contain Z-scores
    if "fingerprint" in r.stdout.lower():
        assert "z=" in r.stdout.lower() or "sigma" in r.stdout.lower()
