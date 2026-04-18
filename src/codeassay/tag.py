"""`codeassay tag` and related commit-time helpers."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_AI_TRAILER = re.compile(r"^AI-Assisted:", re.MULTILINE)
_CO_AUTHOR_AI = re.compile(
    r"Co-Authored-By:.*(Claude|Copilot|GPT|ChatGPT|Gemini|Cursor|Windsurf|Aider)",
    re.IGNORECASE,
)


def already_tagged(message: str) -> bool:
    """True if an AI-Assisted or Co-Authored-By AI-tool trailer is present."""
    return bool(_AI_TRAILER.search(message) or _CO_AUTHOR_AI.search(message))


def _append_trailer(message: str, tool: str) -> str:
    trimmed = message.rstrip("\n")
    return f"{trimmed}\n\nAI-Assisted: {tool}\n"


def add_trailer_to_message_file(path: Path, *, tool: str) -> None:
    """Hook mode: rewrite the message file at `path` to include the trailer.

    Idempotent: skips if any AI trailer is already present.
    """
    message = path.read_text()
    if already_tagged(message):
        return
    path.write_text(_append_trailer(message, tool))


def amend_head_with_trailer(*, tool: str, cwd: Path | None = None) -> None:
    """Standalone mode: amend HEAD commit to add the trailer."""
    log = subprocess.run(
        ["git", "log", "-1", "--format=%B"],
        cwd=cwd, capture_output=True, text=True,
    )
    if log.returncode != 0:
        raise RuntimeError(f"git log failed: {log.stderr}")
    message = log.stdout
    if already_tagged(message):
        return
    new_message = _append_trailer(message, tool)
    subprocess.run(
        ["git", "commit", "--amend", "-m", new_message.rstrip("\n")],
        cwd=cwd, check=True,
    )
