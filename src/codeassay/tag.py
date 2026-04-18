"""`codeassay tag` and related commit-time helpers."""

from __future__ import annotations

import os
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


HOOK_MARKER = "# managed-by-codeassay"

_HOOK_TEMPLATE_ALWAYS = """#!/bin/sh
{marker}
# prepare-commit-msg hook installed by codeassay.
# Mode: always. Adds AI-Assisted trailer unconditionally (idempotent).
# To uninstall: codeassay uninstall-hook
codeassay tag --tool {tool} "$1"
"""

_HOOK_TEMPLATE_PROMPT = """#!/bin/sh
{marker}
# prepare-commit-msg hook installed by codeassay.
# Mode: prompt. Asks whether to add AI-Assisted trailer.
# To uninstall: codeassay uninstall-hook
if [ -t 1 ]; then
    printf "Add AI-Assisted: {tool} trailer? [y/N] " >&2
    read answer < /dev/tty
    case "$answer" in
        y|Y|yes|YES) codeassay tag --tool {tool} "$1" ;;
    esac
fi
"""


def _hook_path(repo_path: Path) -> Path:
    return Path(repo_path) / ".git" / "hooks" / "prepare-commit-msg"


def install_hook(
    repo_path: Path, *, tool: str = "unknown", mode: str = "always", force: bool = False,
) -> None:
    hook = _hook_path(repo_path)
    if hook.exists() and not force:
        if HOOK_MARKER not in hook.read_text():
            raise RuntimeError(
                f"{hook} already exists and was not installed by codeassay. "
                "Use --force to overwrite."
            )
    template = _HOOK_TEMPLATE_ALWAYS if mode == "always" else _HOOK_TEMPLATE_PROMPT
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(template.format(marker=HOOK_MARKER, tool=tool))
    current_mode = os.stat(hook).st_mode
    os.chmod(hook, current_mode | 0o111)


def uninstall_hook(repo_path: Path) -> None:
    hook = _hook_path(repo_path)
    if not hook.exists():
        return
    if HOOK_MARKER not in hook.read_text():
        raise RuntimeError(
            f"{hook} was modified manually; refusing to delete. "
            "Remove it yourself if you're sure."
        )
    hook.unlink()
