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
