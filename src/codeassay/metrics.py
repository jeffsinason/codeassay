"""Metric computation from the AI quality database."""

from collections import Counter
from datetime import datetime


def compute_metrics(conn, *, repo_path: str | None = None, total_commits: int = 0) -> dict:
    if repo_path:
        ai_commits = conn.execute(
            "SELECT * FROM ai_commits WHERE repo_path = ?", (repo_path,)
        ).fetchall()
        rework_events = conn.execute(
            "SELECT * FROM rework_events WHERE repo_path = ?", (repo_path,)
        ).fetchall()
    else:
        ai_commits = conn.execute("SELECT * FROM ai_commits").fetchall()
        rework_events = conn.execute("SELECT * FROM rework_events").fetchall()

    ai_count = len(ai_commits)
    rework_count = len(rework_events)
    reworked_commits = {r["original_commit"] for r in rework_events}
    reworked_count = len(reworked_commits)

    ai_commit_rate = (ai_count / total_commits * 100) if total_commits > 0 else 0.0
    rework_rate = (reworked_count / ai_count * 100) if ai_count > 0 else 0.0
    first_pass_rate = ((ai_count - reworked_count) / ai_count * 100) if ai_count > 0 else 0.0

    category_counts = Counter(r["category"] for r in rework_events)

    commit_tool_map = {c["commit_hash"]: c["tool"] for c in ai_commits}
    tool_rework = Counter()
    for r in rework_events:
        tool = commit_tool_map.get(r["original_commit"], "unknown")
        tool_rework[tool] += 1
    for tool in {c["tool"] for c in ai_commits}:
        if tool not in tool_rework:
            tool_rework[tool] = 0

    time_deltas = []
    commit_dates = {c["commit_hash"]: c["date"] for c in ai_commits}
    for r in rework_events:
        orig_date = commit_dates.get(r["original_commit"])
        if orig_date:
            try:
                delta = datetime.fromisoformat(r["rework_date"]) - datetime.fromisoformat(orig_date)
                time_deltas.append(delta.total_seconds() / 3600)
            except (ValueError, TypeError):
                pass
    mean_time_hours = sum(time_deltas) / len(time_deltas) if time_deltas else 0.0

    file_counts = Counter()
    for r in rework_events:
        for f in r["files_affected"].split(","):
            if f:
                file_counts[f] += 1
    top_files = file_counts.most_common(5)

    return {
        "ai_commit_count": ai_count,
        "human_commit_count": total_commits - ai_count,
        "total_commits": total_commits,
        "ai_commit_rate": round(ai_commit_rate, 1),
        "rework_count": rework_count,
        "reworked_commit_count": reworked_count,
        "rework_rate": round(rework_rate, 1),
        "first_pass_success_rate": round(first_pass_rate, 1),
        "rework_by_category": dict(category_counts),
        "rework_by_tool": dict(tool_rework),
        "mean_time_to_rework_hours": round(mean_time_hours, 1),
        "top_rework_files": top_files,
    }


def compute_trend_data(conn, *, repo_path: str | None = None) -> list[dict]:
    """Group AI commits and rework events by month for trend charting.

    Returns list of dicts: [{"month": "2026-01", "ai_commits": 12, "rework_events": 3}, ...]
    """
    if repo_path:
        ai_rows = conn.execute(
            "SELECT strftime('%Y-%m', date) as month, COUNT(*) as cnt "
            "FROM ai_commits WHERE repo_path = ? GROUP BY month ORDER BY month",
            (repo_path,),
        ).fetchall()
        rework_rows = conn.execute(
            "SELECT strftime('%Y-%m', rework_date) as month, COUNT(*) as cnt "
            "FROM rework_events WHERE repo_path = ? GROUP BY month ORDER BY month",
            (repo_path,),
        ).fetchall()
    else:
        ai_rows = conn.execute(
            "SELECT strftime('%Y-%m', date) as month, COUNT(*) as cnt "
            "FROM ai_commits GROUP BY month ORDER BY month",
        ).fetchall()
        rework_rows = conn.execute(
            "SELECT strftime('%Y-%m', rework_date) as month, COUNT(*) as cnt "
            "FROM rework_events GROUP BY month ORDER BY month",
        ).fetchall()

    ai_by_month = {r["month"]: r["cnt"] for r in ai_rows}
    rework_by_month = {r["month"]: r["cnt"] for r in rework_rows}

    all_months = sorted(set(ai_by_month) | set(rework_by_month))
    return [
        {
            "month": m,
            "ai_commits": ai_by_month.get(m, 0),
            "rework_events": rework_by_month.get(m, 0),
        }
        for m in all_months
    ]
