"""CLI and markdown report formatting for AI code quality metrics."""

from datetime import datetime

CATEGORY_LABELS = {
    "bug_fix": "Bug fix",
    "misunderstanding": "Misunderstanding",
    "test_failure": "Test failure",
    "style_violation": "Style/convention",
    "security_issue": "Security issue",
    "incomplete_implementation": "Incomplete",
    "over_engineering": "Over-engineering",
    "unclassified": "Unclassified",
}


def format_cli_report(metrics: dict, repo_name: str = "Repository") -> str:
    if metrics["ai_commit_count"] == 0:
        return f"{repo_name}\n  No AI commits found.\n"

    lines = [
        f"{repo_name}",
        f"  AI Commits: {metrics['ai_commit_count']}/{metrics['total_commits']} ({metrics['ai_commit_rate']}%)",
        f"  First-Pass Success: {metrics['ai_commit_count'] - metrics['reworked_commit_count']}/{metrics['ai_commit_count']} ({metrics['first_pass_success_rate']}%)",
        f"  Rework Events: {metrics['rework_count']}",
    ]

    if metrics["rework_by_category"]:
        cats = []
        for cat, count in sorted(metrics["rework_by_category"].items(), key=lambda x: -x[1]):
            label = CATEGORY_LABELS.get(cat, cat)
            cats.append(f"{label}: {count}")
        lines.append(f"    {' | '.join(cats)}")

    if metrics["rework_by_tool"]:
        tools = []
        for tool, count in sorted(metrics["rework_by_tool"].items(), key=lambda x: -x[1]):
            tools.append(f"{tool}: {count}")
        lines.append(f"  By Tool: {' | '.join(tools)}")

    if metrics["mean_time_to_rework_hours"] > 0:
        lines.append(f"  Mean Time to Rework: {metrics['mean_time_to_rework_hours']}h")

    if metrics["top_rework_files"]:
        top = metrics["top_rework_files"][0]
        lines.append(f"  Top rework file: {top[0]} ({top[1]} events)")

    return "\n".join(lines) + "\n"


def format_markdown_report(metrics: dict, repo_name: str = "Repository") -> str:
    now = datetime.now().strftime("%Y-%m-%d")

    if metrics["ai_commit_count"] == 0:
        return f"# AI Code Quality Report — {repo_name}\n\n**Date:** {now}\n\nNo AI commits found.\n"

    lines = [
        f"# AI Code Quality Report — {repo_name}", "",
        f"**Date:** {now}", "",
        f"## Summary", "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| AI Commits | {metrics['ai_commit_count']}/{metrics['total_commits']} ({metrics['ai_commit_rate']}%) |",
        f"| First-Pass Success Rate | {metrics['first_pass_success_rate']}% |",
        f"| Rework Rate | {metrics['rework_rate']}% |",
        f"| Rework Events | {metrics['rework_count']} |",
        f"| Mean Time to Rework | {metrics['mean_time_to_rework_hours']}h |", "",
    ]

    if metrics["rework_by_category"]:
        lines.extend(["## Rework by Category", "", "| Category | Count |", "|----------|-------|"])
        for cat, count in sorted(metrics["rework_by_category"].items(), key=lambda x: -x[1]):
            label = CATEGORY_LABELS.get(cat, cat)
            lines.append(f"| {label} | {count} |")
        lines.append("")

    if metrics["rework_by_tool"]:
        lines.extend(["## Rework by AI Tool", "", "| Tool | Rework Events |", "|------|---------------|"])
        for tool, count in sorted(metrics["rework_by_tool"].items(), key=lambda x: -x[1]):
            lines.append(f"| {tool} | {count} |")
        lines.append("")

    if metrics["top_rework_files"]:
        lines.extend(["## Top Rework Files", "", "| File | Events |", "|------|--------|"])
        for filepath, count in metrics["top_rework_files"]:
            lines.append(f"| `{filepath}` | {count} |")
        lines.append("")

    return "\n".join(lines)
