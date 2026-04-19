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
from codeassay.detection import classify
from codeassay.detection.config import load_config
from codeassay.detection.profiles import load_profiles
from codeassay.detection.scorer import per_signal_contributions
from codeassay.scanner import scan_repo, _branches_containing
from codeassay.tag import (
    add_trailer_to_message_file, amend_head_with_trailer,
    install_hook, uninstall_hook,
)


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
    scan_p.add_argument("--with-scorer", action="store_true",
                        help="Force-enable probabilistic scorer for this scan")
    scan_p.add_argument("--dry-run", action="store_true",
                        help="Report matches without writing to DB")
    scan_p.add_argument(
        "--fail-on", choices=["turnover-red"],
        help="Exit non-zero when a threshold is exceeded (e.g. turnover-red)",
    )

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
    commits_p.add_argument("--source", help="Filter by detection source glob (e.g. 'profile:*')")

    rework_p = sub.add_parser("rework", help="List rework events")
    rework_p.add_argument("--since", help="Start date")
    rework_p.add_argument("--until", help="End date")
    rework_p.add_argument("--category", help="Filter by category")
    rework_p.add_argument("--source", help="Filter rework's original-commit source by glob")

    reclass_p = sub.add_parser("reclassify", help="Override rework classification")
    reclass_p.add_argument("commit", help="Rework commit hash")
    reclass_p.add_argument("category", choices=CATEGORIES, help="New category")

    export_p = sub.add_parser("export", help="Export raw data")
    export_p.add_argument("--format", choices=["json"], default="json")

    dash_p = sub.add_parser("dashboard", help="Open interactive HTML dashboard")
    dash_p.add_argument("--output", help="Output file path (default: .codeassay/dashboard.html)")
    dash_p.add_argument("--no-open", action="store_true", help="Don't open browser automatically")

    tag_p = sub.add_parser("tag", help="Add AI-Assisted trailer to a commit message")
    tag_p.add_argument("--tool", default="unknown", help="AI tool name (default: unknown)")
    tag_p.add_argument("message_file", nargs="?", help="Hook-mode: path to commit message file")

    hook_p = sub.add_parser("install-hook", help="Install prepare-commit-msg hook")
    hook_p.add_argument("--tool", default="unknown")
    hook_p.add_argument("--mode", choices=["always", "prompt"], default="always")
    hook_p.add_argument("--force", action="store_true", help="Overwrite existing hook")

    uninst_p = sub.add_parser("uninstall-hook", help="Remove codeassay-managed hook")

    config_p = sub.add_parser("config", help="Manage .codeassay.toml")
    config_sub = config_p.add_subparsers(dest="config_action")
    config_init_p = config_sub.add_parser("init", help="Write starter .codeassay.toml")
    config_init_p.add_argument("--force", action="store_true")
    config_show_p = config_sub.add_parser("show", help="Print merged effective config")

    dt_p = sub.add_parser("detect-test", help="Dry-run detection against one commit")
    dt_p.add_argument("commit", help="Commit hash")

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
        scan_result = scan_repo(
            repo_path, conn,
            dry_run=args.dry_run,
            force_scorer=args.with_scorer,
        )
        rework_result = {"rework_events": 0} if args.dry_run else detect_rework(repo_path, conn)
        name = _get_repo_name(repo_path)
        suffix = " (dry-run)" if args.dry_run else ""
        print(
            f"Scanned {name}{suffix}: "
            f"{scan_result['total_commits']} commits, "
            f"{scan_result['ai_commits']} AI commits, "
            f"{rework_result['rework_events']} rework events"
        )
        conn.close()

    # Evaluate --fail-on threshold (after all repos scanned)
    if getattr(args, "fail_on", None) == "turnover-red":
        any_red = False
        for repo_str in args.repos:
            repo_path = Path(repo_str).resolve()
            if not (repo_path / ".git").exists():
                continue
            db_path = get_db_path(repo_path)
            if not db_path.exists():
                continue
            cfg = load_config(repo_path)
            conn = get_connection(db_path)
            try:
                total = _get_total_commit_count(repo_path)
                m = compute_metrics(conn, repo_path=str(repo_path), total_commits=total)
            finally:
                conn.close()
            ai_turnover = m.get("turnover_ai", 0.0)
            if ai_turnover > cfg.turnover.red_threshold:
                print(
                    f"FAIL: {repo_path.name} AI turnover "
                    f"{ai_turnover*100:.1f}% exceeds red threshold "
                    f"{cfg.turnover.red_threshold*100:.1f}%",
                    file=sys.stderr,
                )
                any_red = True
        if any_red:
            sys.exit(1)


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
    import fnmatch
    repo_path = Path.cwd().resolve()
    db_path = get_db_path(repo_path)
    if not db_path.exists():
        print("No scan data found. Run 'codeassay scan .' first.", file=sys.stderr)
        sys.exit(1)
    conn = get_connection(db_path)
    commits = get_ai_commits(conn, repo_path=str(repo_path))
    if args.tool:
        commits = [c for c in commits if c["tool"] == args.tool]
    if args.source:
        commits = [
            c for c in commits
            if c.get("source") and fnmatch.fnmatch(c["source"], args.source)
        ]
    for c in commits:
        tool_tag = f"[{c['tool']}]"
        print(f"{c['commit_hash'][:8]} {c['date'][:10]} {tool_tag:16s} {c['message'][:60]}")
    conn.close()


def cmd_rework(args) -> None:
    import fnmatch
    repo_path = Path.cwd().resolve()
    db_path = get_db_path(repo_path)
    if not db_path.exists():
        print("No scan data found. Run 'codeassay scan .' first.", file=sys.stderr)
        sys.exit(1)
    conn = get_connection(db_path)
    events = get_rework_events(conn, repo_path=str(repo_path))
    if args.category:
        events = [e for e in events if e["category"] == args.category]
    if args.source:
        ai_commits = {c["commit_hash"]: c.get("source") for c in get_ai_commits(conn, repo_path=str(repo_path))}
        events = [
            e for e in events
            if ai_commits.get(e["original_commit"])
            and fnmatch.fnmatch(ai_commits[e["original_commit"]], args.source)
        ]
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


def cmd_tag(args) -> None:
    if args.message_file:
        add_trailer_to_message_file(Path(args.message_file), tool=args.tool)
    else:
        amend_head_with_trailer(tool=args.tool, cwd=Path.cwd())


def cmd_install_hook(args) -> None:
    try:
        install_hook(Path.cwd(), tool=args.tool, mode=args.mode, force=args.force)
    except (ValueError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)
    print(f"Installed prepare-commit-msg hook (tool={args.tool}, mode={args.mode})")


def cmd_config(args) -> None:
    if args.config_action == "init":
        _config_init(Path.cwd(), force=args.force)
    elif args.config_action == "show":
        _config_show(Path.cwd())
    else:
        print("Usage: codeassay config {init,show}", file=sys.stderr)
        sys.exit(1)


def _config_init(repo_path: Path, *, force: bool) -> None:
    from codeassay.detection.config_init import STARTER_TEMPLATE
    cfg = repo_path / ".codeassay.toml"
    if cfg.exists() and not force:
        print(f"{cfg} exists (use --force to overwrite)", file=sys.stderr)
        sys.exit(1)
    cfg.write_text(STARTER_TEMPLATE)
    print(f"Wrote {cfg}")


def _config_show(repo_path: Path) -> None:
    from codeassay.detection.config import load_config
    from codeassay.detection.profiles import load_profiles
    cfg = load_config(repo_path)
    profiles = load_profiles(disabled=cfg.disabled_profiles)
    print("User rules:")
    for cat in ("author_rules", "branch_rules", "message_rules", "window_rules"):
        rules = getattr(cfg, cat)
        print(f"  {cat}: {len(rules)}")
    print(f"Disabled profiles: {sorted(cfg.disabled_profiles) or '(none)'}")
    print(f"Enabled profiles: {[p.name for p in profiles]}")
    print(f"Scorer enabled: {cfg.score.enabled} (threshold={cfg.score.threshold})")


def cmd_detect_test(args) -> None:
    repo_path = Path.cwd().resolve()
    result = subprocess.run(
        ["git", "log", "-1", f"--format=%H%n%an%n%ae%n%aI%n%B", args.commit],
        cwd=repo_path, capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"commit {args.commit} not found", file=sys.stderr)
        sys.exit(1)
    lines = result.stdout.splitlines()
    if len(lines) < 5:
        print("unexpected git log output", file=sys.stderr)
        sys.exit(1)
    commit = {
        "hash": lines[0],
        "author": lines[1],
        "author_email": lines[2],
        "date": lines[3],
        "message": "\n".join(lines[4:]),
        "branches": _branches_containing(repo_path, args.commit),
    }
    config = load_config(repo_path)
    profiles = load_profiles(disabled=config.disabled_profiles)
    detection = classify(commit, config=config, profiles=profiles)
    print(f"Commit: {commit['hash'][:12]} by {commit['author']} <{commit['author_email']}>")
    print(f"Branches containing this commit: {sorted(commit['branches']) or '(none)'}")
    if detection is None:
        print("Result: no match (human-authored)")
        if config.score.enabled:
            contributions = per_signal_contributions(
                commit=commit, diff_stats=[], seconds_since_prior=None,
                config=config.score,
            )
            print("Scorer breakdown (disabled or below threshold):")
            for name, data in contributions.items():
                print(f"  {name}: raw={data['raw']:.2f} weighted={data['weighted']:.3f}")
        _print_fingerprint_breakdown(repo_path=repo_path, commit=commit, config=config)
        return
    print(f"Result: AI ({detection.tool}, confidence={detection.confidence})")
    print(f"  method: {detection.method}")
    print(f"  source: {detection.source}")
    print(f"  detection_confidence: {detection.detection_confidence}/100")
    if detection.method == "fingerprint":
        _print_fingerprint_breakdown(repo_path=repo_path, commit=commit, config=config)


def _print_fingerprint_breakdown(*, repo_path: Path, commit: dict, config) -> None:
    """Print each fingerprint metric with its Z-score vs the author's baseline."""
    if not config.fingerprint.enabled:
        return
    from codeassay.db import get_author_baselines
    from codeassay.detection.fingerprint import (
        METRIC_NAMES, metric_avg_diff_size, metric_comment_ratio,
        metric_identifier_entropy, metric_punctuation_density, metric_message_length,
    )
    from codeassay.scanner import _added_lines_for_commit

    db_path = get_db_path(repo_path)
    if not db_path.exists():
        print("  (no scan data; run `codeassay scan .` first to build baselines)")
        return
    conn2 = get_connection(db_path)
    try:
        email = commit.get("author_email", "")
        baselines = get_author_baselines(conn2, repo_path=str(repo_path), author_email=email)
    finally:
        conn2.close()
    if not baselines:
        print(f"  (no baselines for {email})")
        return
    added_lines = _added_lines_for_commit(repo_path, commit["hash"])
    fp_metrics = {
        "avg_diff_size": metric_avg_diff_size(lines_added=len(added_lines)),
        "comment_ratio": metric_comment_ratio(added_lines),
        "identifier_entropy": metric_identifier_entropy(added_lines),
        "punctuation_density": metric_punctuation_density(commit["message"]),
        "message_length": float(metric_message_length(commit["message"])),
    }
    print("Fingerprint breakdown (z-scores vs author baseline):")
    for name in METRIC_NAMES:
        b = baselines.get(name)
        if b is None:
            print(f"  {name}: no baseline")
            continue
        v = fp_metrics[name]
        if b.stddev == 0:
            z = float("inf") if v != b.mean else 0.0
        else:
            z = (v - b.mean) / b.stddev
        flag = "**" if abs(z) >= config.fingerprint.sigma_threshold else "  "
        print(f"  {flag} {name}: value={v:.3f} mean={b.mean:.3f} z={z:+.2f}")


def cmd_uninstall_hook(args) -> None:
    try:
        uninstall_hook(Path.cwd())
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)
    print("Uninstalled prepare-commit-msg hook (if present)")


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
    "tag": cmd_tag,
    "install-hook": cmd_install_hook,
    "uninstall-hook": cmd_uninstall_hook,
    "config": cmd_config,
    "detect-test": cmd_detect_test,
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
