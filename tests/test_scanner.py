"""Tests for codeassay.scanner."""

import subprocess

from codeassay.scanner import (
    detect_ai_tool,
    get_detection_confidence,
    parse_commit_log,
    scan_repo,
)


def _make_commit(repo, filename, content, message, co_author=None, trailer=None):
    """Helper: create a commit in the test repo."""
    (repo / filename).write_text(content)
    subprocess.run(["git", "add", filename], cwd=repo, capture_output=True)
    full_message = message
    if co_author:
        full_message += f"\n\nCo-Authored-By: {co_author}"
    if trailer:
        full_message += f"\n\n{trailer}"
    subprocess.run(
        ["git", "commit", "-m", full_message], cwd=repo, capture_output=True
    )


def test_detect_ai_tool_claude():
    assert detect_ai_tool("Co-Authored-By: Claude <noreply@anthropic.com>") == "claude_code"


def test_detect_ai_tool_copilot():
    assert detect_ai_tool("Co-Authored-By: GitHub Copilot <copilot@github.com>") == "copilot"


def test_detect_ai_tool_gpt():
    assert detect_ai_tool("Co-Authored-By: ChatGPT <noreply@openai.com>") == "gpt"


def test_detect_ai_tool_manual_trailer():
    assert detect_ai_tool("AI-Assisted: true") == "unknown"


def test_detect_ai_tool_none():
    assert detect_ai_tool("just a normal commit message") is None


def test_get_detection_confidence_trailer():
    assert get_detection_confidence("co_author_trailer") == "high"


def test_get_detection_confidence_branch():
    assert get_detection_confidence("branch_pattern") == "medium"


def test_get_detection_confidence_manual():
    assert get_detection_confidence("manual_tag") == "high"


def test_parse_commit_log(tmp_repo):
    _make_commit(
        tmp_repo, "foo.py", "print('hello')\n",
        "feat: add foo",
        co_author="Claude Opus 4 <noreply@anthropic.com>",
    )
    _make_commit(
        tmp_repo, "bar.py", "print('world')\n",
        "feat: add bar (human)",
    )
    _make_commit(
        tmp_repo, "baz.py", "x = 1\n",
        "feat: add baz",
        trailer="AI-Assisted: true",
    )
    commits = parse_commit_log(tmp_repo)
    assert len(commits) >= 3


def test_scan_repo_finds_ai_commits(tmp_repo, db_conn):
    _make_commit(
        tmp_repo, "foo.py", "print('hello')\n",
        "feat: add foo",
        co_author="Claude Opus 4 <noreply@anthropic.com>",
    )
    _make_commit(
        tmp_repo, "bar.py", "print('world')\n",
        "feat: add bar (human only)",
    )
    result = scan_repo(tmp_repo, db_conn)
    assert result["total_commits"] >= 2
    assert result["ai_commits"] == 1


def test_scan_repo_incremental(tmp_repo, db_conn):
    _make_commit(
        tmp_repo, "foo.py", "x = 1\n",
        "feat: first",
        co_author="Claude <noreply@anthropic.com>",
    )
    scan_repo(tmp_repo, db_conn)
    _make_commit(
        tmp_repo, "bar.py", "y = 2\n",
        "feat: second",
        co_author="Claude <noreply@anthropic.com>",
    )
    result = scan_repo(tmp_repo, db_conn)
    assert result["ai_commits"] == 1
    from codeassay.db import get_ai_commits
    all_commits = get_ai_commits(db_conn, repo_path=str(tmp_repo))
    assert len(all_commits) == 2


def test_scan_repo_records_source(tmp_repo, db_conn):
    _make_commit(
        tmp_repo, "foo.py", "print('hi')\n",
        "feat: foo",
        co_author="Claude <x@anthropic.com>",
    )
    scan_repo(tmp_repo, db_conn)
    from codeassay.db import get_ai_commits
    rows = get_ai_commits(db_conn, repo_path=str(tmp_repo))
    assert len(rows) == 1
    assert rows[0]["source"] == "profile:claude_code"
    assert rows[0]["tool"] == "claude_code"


def test_scan_repo_records_detection_confidence(tmp_repo, db_conn):
    _make_commit(
        tmp_repo, "foo.py", "x\n",
        "feat: foo",
        co_author="Claude <x@anthropic.com>",
    )
    scan_repo(tmp_repo, db_conn)
    from codeassay.db import get_ai_commits
    rows = get_ai_commits(db_conn, repo_path=str(tmp_repo))
    assert rows[0]["detection_confidence"] == 90  # "high" → 90


def test_scan_repo_respects_user_config_override(tmp_repo, db_conn):
    (tmp_repo / ".codeassay.toml").write_text(
        '[[detect.message]]\n'
        'pattern = "Co-Authored-By:.*Claude"\n'
        'tool = "custom_brand"\n'
        'confidence = "high"\n'
    )
    _make_commit(
        tmp_repo, "foo.py", "x\n",
        "feat: foo",
        co_author="Claude <x@anthropic.com>",
    )
    scan_repo(tmp_repo, db_conn)
    from codeassay.db import get_ai_commits
    rows = get_ai_commits(db_conn, repo_path=str(tmp_repo))
    assert rows[0]["tool"] == "custom_brand"
    assert rows[0]["source"] == "user:detect.message[0]"


def test_scan_repo_populates_commit_lines(tmp_repo, db_conn):
    _make_commit(
        tmp_repo, "foo.py", "a\nb\nc\n",
        "feat: foo",
        co_author="Claude <x@anthropic.com>",
    )
    _make_commit(tmp_repo, "bar.py", "x\ny\n", "feat: human add bar")
    scan_repo(tmp_repo, db_conn)
    rows = db_conn.execute(
        "SELECT commit_sha, file, lines_added, lines_survived FROM commit_lines ORDER BY file"
    ).fetchall()
    # Should have at least 2 rows — one per file added by the two commits.
    # (Initial commit from fixture is Test User, also human, also counted.)
    files = {r["file"] for r in rows}
    assert "foo.py" in files
    assert "bar.py" in files
    # foo.py: 3 lines added, all survived (HEAD unchanged for that file)
    foo = next(r for r in rows if r["file"] == "foo.py")
    assert foo["lines_added"] == 3
    assert foo["lines_survived"] == 3
