import subprocess
import sys
from pathlib import Path
import pytest

from codeassay.tag import add_trailer_to_message_file, already_tagged


def test_add_trailer_plain_message(tmp_path):
    msg = tmp_path / "MSG"
    msg.write_text("feat: add thing\n")
    add_trailer_to_message_file(msg, tool="cursor")
    out = msg.read_text()
    assert "AI-Assisted: cursor" in out
    assert out.startswith("feat: add thing")


def test_add_trailer_strips_trailing_newline_before_appending(tmp_path):
    msg = tmp_path / "MSG"
    msg.write_text("feat: x\n\n")
    add_trailer_to_message_file(msg, tool="claude_code")
    assert msg.read_text().count("AI-Assisted:") == 1


def test_already_tagged_with_ai_assisted():
    assert already_tagged("feat: x\n\nAI-Assisted: cursor") is True


def test_already_tagged_with_co_author_claude():
    assert already_tagged("feat: x\n\nCo-Authored-By: Claude <x@a.com>") is True


def test_already_tagged_with_co_author_copilot():
    assert already_tagged("feat: x\n\nCo-Authored-By: GitHub Copilot <c@g.com>") is True


def test_already_tagged_none():
    assert already_tagged("feat: plain") is False


def test_add_trailer_idempotent(tmp_path):
    msg = tmp_path / "MSG"
    msg.write_text("feat: x\n\nAI-Assisted: cursor")
    add_trailer_to_message_file(msg, tool="cursor")
    assert msg.read_text().count("AI-Assisted:") == 1


def test_add_trailer_skips_when_co_author_present(tmp_path):
    msg = tmp_path / "MSG"
    msg.write_text("feat: x\n\nCo-Authored-By: Claude <x@a.com>")
    add_trailer_to_message_file(msg, tool="cursor")
    assert "AI-Assisted: cursor" not in msg.read_text()


def test_cli_tag_amend(tmp_repo):
    """End-to-end via CLI: tag amends the last commit."""
    subprocess.run(
        [sys.executable, "-m", "codeassay", "tag", "--tool", "cursor"],
        cwd=tmp_repo, capture_output=True, text=True,
    )
    log = subprocess.run(
        ["git", "log", "-1", "--format=%B"],
        cwd=tmp_repo, capture_output=True, text=True,
    ).stdout
    assert "AI-Assisted: cursor" in log


from codeassay.tag import install_hook, uninstall_hook, HOOK_MARKER


def _init_plain_repo(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init", "--template=/dev/null"], cwd=repo, capture_output=True)
    return repo


def test_install_hook_writes_hook_with_marker(tmp_path):
    repo = _init_plain_repo(tmp_path)
    install_hook(repo, tool="cursor", mode="always")
    hook = repo / ".git" / "hooks" / "prepare-commit-msg"
    assert hook.exists()
    content = hook.read_text()
    assert HOOK_MARKER in content
    assert "cursor" in content
    import os
    assert os.access(hook, os.X_OK)


def test_install_hook_fails_if_existing_unmanaged(tmp_path):
    repo = _init_plain_repo(tmp_path)
    hook = repo / ".git" / "hooks" / "prepare-commit-msg"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\n# handmade hook\n")
    with pytest.raises(RuntimeError, match="already exists"):
        install_hook(repo, tool="cursor", mode="always")


def test_install_hook_force_overwrites(tmp_path):
    repo = _init_plain_repo(tmp_path)
    hook = repo / ".git" / "hooks" / "prepare-commit-msg"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\n# handmade\n")
    install_hook(repo, tool="cursor", mode="always", force=True)
    assert HOOK_MARKER in hook.read_text()


def test_uninstall_hook_removes_managed(tmp_path):
    repo = _init_plain_repo(tmp_path)
    install_hook(repo, tool="cursor", mode="always")
    uninstall_hook(repo)
    hook = repo / ".git" / "hooks" / "prepare-commit-msg"
    assert not hook.exists()


def test_uninstall_hook_refuses_modified(tmp_path):
    repo = _init_plain_repo(tmp_path)
    install_hook(repo, tool="cursor", mode="always")
    hook = repo / ".git" / "hooks" / "prepare-commit-msg"
    # Remove the marker to simulate hand editing
    hook.write_text("#!/bin/sh\necho hi\n")
    with pytest.raises(RuntimeError, match="modified"):
        uninstall_hook(repo)


def test_uninstall_hook_noop_when_absent(tmp_path):
    repo = _init_plain_repo(tmp_path)
    uninstall_hook(repo)  # should not raise


def test_install_hook_rejects_shell_injection_in_tool(tmp_path):
    repo = _init_plain_repo(tmp_path)
    malicious = 'x"; rm -rf "$HOME'
    with pytest.raises(ValueError, match="invalid tool name"):
        install_hook(repo, tool=malicious, mode="always")


def test_install_hook_rejects_empty_tool(tmp_path):
    repo = _init_plain_repo(tmp_path)
    with pytest.raises(ValueError, match="invalid tool name"):
        install_hook(repo, tool="", mode="always")


def test_install_hook_accepts_standard_tool_names(tmp_path):
    repo = _init_plain_repo(tmp_path)
    # All seven profile names should pass.
    for name in ("claude_code", "copilot", "cursor", "aider", "windsurf", "gpt", "gemini"):
        install_hook(repo, tool=name, mode="always", force=True)
