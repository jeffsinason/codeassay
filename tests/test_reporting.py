"""Tests for codeassay.reporting."""

from codeassay.reporting import format_cli_report, format_markdown_report


SAMPLE_METRICS = {
    "ai_commit_count": 47,
    "total_commits": 112,
    "ai_commit_rate": 42.0,
    "rework_count": 9,
    "reworked_commit_count": 8,
    "rework_rate": 17.0,
    "first_pass_success_rate": 83.0,
    "rework_by_category": {
        "bug_fix": 3, "misunderstanding": 2, "test_failure": 2,
        "style_violation": 1, "over_engineering": 1,
    },
    "rework_by_tool": {"claude_code": 6, "copilot": 3},
    "mean_time_to_rework_hours": 18.5,
    "top_rework_files": [("src/classify.py", 3), ("src/routes.py", 2)],
}


def test_format_cli_report_contains_key_metrics():
    output = format_cli_report(SAMPLE_METRICS, repo_name="EchoForge Hub")
    assert "EchoForge Hub" in output
    assert "47/112" in output or "47" in output
    assert "42.0%" in output or "42%" in output
    assert "83.0%" in output or "83%" in output
    assert "bug_fix" in output or "Bug fix" in output


def test_format_cli_report_handles_empty():
    empty = {
        "ai_commit_count": 0, "total_commits": 0, "ai_commit_rate": 0.0,
        "rework_count": 0, "reworked_commit_count": 0, "rework_rate": 0.0,
        "first_pass_success_rate": 0.0, "rework_by_category": {},
        "rework_by_tool": {}, "mean_time_to_rework_hours": 0.0,
        "top_rework_files": [],
    }
    output = format_cli_report(empty, repo_name="Empty Repo")
    assert "Empty Repo" in output
    assert "No AI commits" in output


def test_format_markdown_report_structure():
    output = format_markdown_report(SAMPLE_METRICS, repo_name="EchoForge Hub")
    assert output.startswith("#")
    assert "| Metric |" in output
    assert "bug_fix" in output or "Bug fix" in output
    assert "claude_code" in output or "Claude Code" in output


def test_format_markdown_report_handles_empty():
    empty = {
        "ai_commit_count": 0, "total_commits": 0, "ai_commit_rate": 0.0,
        "rework_count": 0, "reworked_commit_count": 0, "rework_rate": 0.0,
        "first_pass_success_rate": 0.0, "rework_by_category": {},
        "rework_by_tool": {}, "mean_time_to_rework_hours": 0.0,
        "top_rework_files": [],
    }
    output = format_markdown_report(empty, repo_name="Empty Repo")
    assert "No AI commits" in output


def test_cli_report_shows_turnover():
    metrics = {**SAMPLE_METRICS,
        "turnover_ai": 0.08, "turnover_human": 0.03, "turnover_ratio": 2.67,
        "turnover_ai_lines_added": 500, "turnover_ai_lines_discarded": 40,
        "turnover_human_lines_added": 2000, "turnover_human_lines_discarded": 60,
    }
    out = format_cli_report(metrics, repo_name="r")
    assert "Turnover" in out
    assert "8.0" in out or "8%" in out  # AI turnover 8%
    assert "2.67" in out  # ratio


def test_markdown_report_shows_turnover():
    metrics = {**SAMPLE_METRICS,
        "turnover_ai": 0.08, "turnover_human": 0.03, "turnover_ratio": 2.67,
        "turnover_ai_lines_added": 500, "turnover_ai_lines_discarded": 40,
        "turnover_human_lines_added": 2000, "turnover_human_lines_discarded": 60,
    }
    out = format_markdown_report(metrics, repo_name="r")
    assert "Turnover" in out
    assert "|" in out  # still a markdown table
