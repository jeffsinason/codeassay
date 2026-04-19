import subprocess

from codeassay.db import get_ai_commits, init_db, get_connection
from codeassay.scanner import scan_repo


def _commit(repo, filename: str, content: str, message: str) -> None:
    (repo / filename).write_text(content)
    subprocess.run(["git", "add", filename], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo, capture_output=True)


def test_scan_with_mixed_signals(tmp_repo):
    # 1. Human commit (should not match).
    _commit(tmp_repo, "a.py", "print(1)\n", "feat: add a")

    # 2. Profile match (Claude co-author trailer).
    _commit(
        tmp_repo, "b.py", "print(2)\n",
        "feat: add b\n\nCo-Authored-By: Claude <x@anthropic.com>",
    )

    # 3. User-rule match — team convention: "[AI]" prefix → custom tool.
    (tmp_repo / ".codeassay.toml").write_text(
        '[[detect.message]]\n'
        'pattern = "^\\\\[AI\\\\]"\n'
        'tool = "team_ai"\n'
        'confidence = "high"\n\n'
        '[score]\n'
        'enabled = true\n'
        'threshold = 0.6\n'
    )
    _commit(tmp_repo, "c.py", "print(3)\n", "[AI] feat: add c")

    # 4. Scorer-only match: structured message + emoji, no deterministic signal.
    structured_msg = (
        "feat: comprehensive refactor 🤖\n\n"
        "Summary:\n- replace module\n- update tests\n\n"
        "Test plan:\n- run pytest\n"
    )
    _commit(tmp_repo, "d.py", "x\n" * 20, structured_msg)

    # Run scan end-to-end
    db_path = tmp_repo / ".codeassay" / "quality.db"
    init_db(db_path)
    conn = get_connection(db_path)
    result = scan_repo(tmp_repo, conn)
    rows = get_ai_commits(conn, repo_path=str(tmp_repo))
    conn.close()

    sources = {r["source"] for r in rows}
    tools = {r["tool"] for r in rows}

    # Expect the 3 AI commits (profile, user-rule, scorer); skip the human one.
    assert any(s == "profile:claude_code" for s in sources), sources
    assert any(s == "user:detect.message[0]" for s in sources), sources
    assert any(s and s.startswith("score:") for s in sources), sources
    assert "claude_code" in tools
    assert "team_ai" in tools
    assert "unknown" in tools  # scorer hit
    assert result["ai_commits"] == 3
