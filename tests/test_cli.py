"""Tests for codeassay.cli — end-to-end CLI tests."""

import subprocess
import sys
from unittest.mock import patch

from codeassay.cli import main, build_parser


def test_parser_scan_subcommand():
    parser = build_parser()
    args = parser.parse_args(["scan", "/tmp/repo1", "/tmp/repo2"])
    assert args.command == "scan"
    assert args.repos == ["/tmp/repo1", "/tmp/repo2"]


def test_parser_report_subcommand():
    parser = build_parser()
    args = parser.parse_args(["report", "--format", "markdown", "--project", "myrepo"])
    assert args.command == "report"
    assert args.format == "markdown"
    assert args.project == "myrepo"


def test_parser_report_defaults():
    parser = build_parser()
    args = parser.parse_args(["report"])
    assert args.command == "report"
    assert args.format == "cli"


def test_parser_commits_subcommand():
    parser = build_parser()
    args = parser.parse_args(["commits", "--ai-only", "--tool", "claude_code"])
    assert args.command == "commits"
    assert args.ai_only is True
    assert args.tool == "claude_code"


def test_parser_rework_subcommand():
    parser = build_parser()
    args = parser.parse_args(["rework", "--since", "2026-04-01", "--until", "2026-04-16"])
    assert args.command == "rework"
    assert args.since == "2026-04-01"
    assert args.until == "2026-04-16"


def test_parser_reclassify_subcommand():
    parser = build_parser()
    args = parser.parse_args(["reclassify", "abc123", "misunderstanding"])
    assert args.command == "reclassify"
    assert args.commit == "abc123"
    assert args.category == "misunderstanding"


def test_parser_export_subcommand():
    parser = build_parser()
    args = parser.parse_args(["export", "--format", "json"])
    assert args.command == "export"
    assert args.format == "json"


def test_scan_end_to_end(tmp_repo, db_path, capsys):
    """End-to-end: scan a repo with an AI commit, then report."""
    (tmp_repo / "feature.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "feature.py"], cwd=tmp_repo, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m",
         "feat: add feature\n\nCo-Authored-By: Claude <noreply@anthropic.com>"],
        cwd=tmp_repo, capture_output=True,
    )

    with patch("codeassay.cli.get_db_path", return_value=db_path):
        sys.argv = ["codeassay", "scan", str(tmp_repo)]
        main()

    captured = capsys.readouterr()
    assert "Scanned" in captured.out
    assert "AI commits" in captured.out or "ai" in captured.out.lower()
