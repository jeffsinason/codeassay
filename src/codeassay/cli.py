"""CLI entrypoint for codeassay."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from codeassay.classifier import CATEGORIES
from codeassay.db import (
    get_connection, get_rework_events, get_ai_commits,
    init_db, set_rework_override,
)
from codeassay.dashboard import generate_dashboard
from codeassay.metrics import compute_metrics, compute_trend_data
from codeassay.reporting import format_cli_report, format_markdown_report
from codeassay.rework import detect_rework
from codeassay.scanner import scan_repo


def get_db_path(repo_path: Path) -> Path:
    return repo_path / ".codeassay" / "quality.db"


def _ensure_gitignore(repo_path: Path) -> None:
    gitignore = repo_path / ".gitignore"
    entry = ".codeassay/"
    if gitignore.exists():
        content = gitignore.read_text()
        if entry not in content:
            with gitignore.open("a") as f:
                f.write(f"\n{entry}\n")
    else:
        gitignore.write_text(f"{entry}\n")


def _get_total_commit_count(repo_path: Path) -> int:
    result = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=repo_path, capture_output=True, text=True,
    )
    if result.returncode == 0:
        return int(result.stdout.strip())
    return 0


def _get_repo_name(repo_path: Path) -> str:
    return repo_path.name


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codeassay",
        description="Analyze AI-authored code quality via git forensics",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    scan_p = sub.add_parser("scan", help="Scan repos for AI commits and rework")
    scan_p.add_argument("repos", nargs="+", help="Paths to git repos to scan")

    report_p = sub.add_parser("report", help="Generate quality report")
    report_p.add_argument("--format", choices=["cli", "markdown"], default="cli")
    report_p.add_argument("--project", help="Filter to a specific repo name")
    report_p.add_argument("--sprint", help="Filter to a sprint ID")
    report_p.add_argument("--since", help="Start date (YYYY-MM-DD)")
    report_p.add_argument("--until", help="End date (YYYY-MM-DD)")
    report_p.add_argument("--tool", help="Filter by AI tool")
    report_p.add_argument("--output", help="Output file path (markdown only)")

    commits_p = sub.add_parser("commits", help="List AI-authored commits")
    commits_p.add_argument("--ai-only", action="store_true", help="Only show AI commits")
    commits_p.add_argument("--tool", help="Filter by AI tool")
    commits_p.add_argument("--since", help="Start date")
    commits_p.add_argument("--until", help="End date")

    rework_p = sub.add_parser("rework", help="List rework events")
    rework_p.add_argument("--since", help="Start date")
    rework_p.add_argument("--until", help="End date")
    rework_p.add_argument("--category", help="Filter by category")

    reclass_p = sub.add_parser("reclassify", help="Override rework classification")
    reclass_p.add_argument("commit", help="Rework commit hash")
    reclass_p.add_argument("category", choices=CATEGORIES, help="New category")

    export_p = sub.add_parser("export", help="Export raw data")
    export_p.add_argument("--format", choices=["json"], default="json")

    dash_p = sub.add_parser("dashboard", help="Open interactive HTML dashboard")
    dash_p.add_argument("--output", help="Output file path (default: .codeassay/dashboard.html)")
    dash_p.add_argument("--no-open", action="store_true", help="Don't open browser automatically")

    return parser


def cmd_scan(args) -> None:
    for repo_str in args.repos:
        repo_path = Path(repo_str).resolve()
        if not (repo_path / ".git").exists():
            print(f"Skipping {repo_str}: not a git repository", file=sys.stderr)
            continue

        db_path = get_db_path(repo_path)
        init_db(db_path)
        _ensure_gitignore(repo_path)
        conn = get_connection(db_path)

        scan_result = scan_repo(repo_path, conn)
        rework_result = detect_rework(repo_path, conn)

        name = _get_repo_name(repo_path)
        print(
            f"Scanned {name}: "
            f"{scan_result['total_commits']} commits, "
            f"{scan_result['ai_commits']} AI commits, "
            f"{rework_result['rework_events']} rework events"
        )
        conn.close()


def cmd_report(args) -> None:
    repo_path = Path.cwd().resolve()
    db_path = get_db_path(repo_path)
    if not db_path.exists():
        print("No scan data found. Run 'codeassay scan .' first.", file=sys.stderr)
        sys.exit(1)

    conn = get_connection(db_path)
    total = _get_total_commit_count(repo_path)
    repo_filter = str(repo_path) if not args.project else None

    if args.project:
        all_commits = get_ai_commits(conn)
        matching = [c for c in all_commits if args.project in c["repo_path"]]
        if matching:
            repo_filter = matching[0]["repo_path"]

    metrics = compute_metrics(conn, repo_path=repo_filter, total_commits=total)
    name = args.project or _get_repo_name(repo_path)

    if args.format == "markdown":
        output = format_markdown_report(metrics, repo_name=name)
        if args.output:
            Path(args.output).write_text(output)
            print(f"Report saved to {args.output}")
        else:
            print(output)
    else:
        print(format_cli_report(metrics, repo_name=name))

    conn.close()


def cmd_commits(args) -> None:
    repo_path = Path.cwd().resolve()
    db_path = get_db_path(repo_path)
    if not db_path.exists():
        print("No scan data found. Run 'codeassay scan .' first.", file=sys.stderr)
        sys.exit(1)

    conn = get_connection(db_path)
    commits = get_ai_commits(conn, repo_path=str(repo_path))

    if args.tool:
        commits = [c for c in commits if c["tool"] == args.tool]

    for c in commits:
        tool_tag = f"[{c['tool']}]"
        print(f"{c['commit_hash'][:8]} {c['date'][:10]} {tool_tag:16s} {c['message'][:60]}")

    conn.close()


def cmd_rework(args) -> None:
    repo_path = Path.cwd().resolve()
    db_path = get_db_path(repo_path)
    if not db_path.exists():
        print("No scan data found. Run 'codeassay scan .' first.", file=sys.stderr)
        sys.exit(1)

    conn = get_connection(db_path)
    events = get_rework_events(conn, repo_path=str(repo_path))

    if args.category:
        events = [e for e in events if e["category"] == args.category]

    for e in events:
        print(
            f"{e['rework_commit'][:8]} -> {e['original_commit'][:8]} "
            f"[{e['category']:24s}] {e['confidence']:6s} {e['files_affected']}"
        )

    conn.close()


def cmd_reclassify(args) -> None:
    repo_path = Path.cwd().resolve()
    db_path = get_db_path(repo_path)
    if not db_path.exists():
        print("No scan data found.", file=sys.stderr)
        sys.exit(1)

    conn = get_connection(db_path)
    set_rework_override(conn, args.commit, args.category)
    print(f"Reclassified {args.commit[:8]} as {args.category}")
    conn.close()


def cmd_export(args) -> None:
    repo_path = Path.cwd().resolve()
    db_path = get_db_path(repo_path)
    if not db_path.exists():
        print("No scan data found.", file=sys.stderr)
        sys.exit(1)

    conn = get_connection(db_path)
    data = {
        "ai_commits": get_ai_commits(conn, repo_path=str(repo_path)),
        "rework_events": get_rework_events(conn, repo_path=str(repo_path)),
    }
    print(json.dumps(data, indent=2))
    conn.close()


def cmd_dashboard(args) -> None:
    """Generate and open an interactive HTML dashboard."""
    import webbrowser

    repo_path = Path.cwd().resolve()
    db_path = get_db_path(repo_path)
    if not db_path.exists():
        print("No scan data found. Run 'codeassay scan .' first.", file=sys.stderr)
        sys.exit(1)

    conn = get_connection(db_path)
    total = _get_total_commit_count(repo_path)
    metrics = compute_metrics(conn, repo_path=str(repo_path), total_commits=total)
    trend = compute_trend_data(conn, repo_path=str(repo_path))
    name = _get_repo_name(repo_path)

    html = generate_dashboard(metrics, trend, repo_name=name)

    output_path = Path(args.output) if args.output else db_path.parent / "dashboard.html"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html)

    print(f"Dashboard saved to {output_path}")
    if not args.no_open:
        webbrowser.open(f"file://{output_path.resolve()}")

    conn.close()


COMMANDS = {
    "scan": cmd_scan,
    "report": cmd_report,
    "commits": cmd_commits,
    "rework": cmd_rework,
    "reclassify": cmd_reclassify,
    "export": cmd_export,
    "dashboard": cmd_dashboard,
}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    handler = COMMANDS.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()
        sys.exit(1)
