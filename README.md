# CodeAssay

Git forensics tool for analyzing AI-authored code quality. Detects AI-generated commits, identifies rework, classifies root causes, and generates quality reports.

## Install

```bash
pip install codeassay
```

## Quick Start

```bash
# Scan a repository
codeassay scan /path/to/repo

# View a report
codeassay report

# Scan multiple repos with combined output
codeassay scan ../repo1 ../repo2 ../repo3
```

## Commands

| Command | Purpose |
|---------|---------|
| `codeassay scan <paths>` | Scan repos (supports `--with-scorer`, `--dry-run`, `--fail-on=turnover-red`) |
| `codeassay report` | Generate quality report (CLI or markdown) |
| `codeassay commits` | List AI-authored commits (supports `--source <glob>`, `--tool`) |
| `codeassay rework` | List rework events with classification |
| `codeassay reclassify <commit> <category>` | Override a classification |
| `codeassay export --format json` | Export raw data |
| `codeassay dashboard` | Open interactive HTML dashboard in browser |
| `codeassay config init` | Scaffold `.codeassay.toml` in the current repo |
| `codeassay config show` | Print merged effective config |
| `codeassay detect-test <hash>` | Dry-run detection pipeline against one commit |
| `codeassay tag [--tool <name>]` | Add `AI-Assisted:` trailer to a commit (hook or amend) |
| `codeassay install-hook [--tool <name>] [--mode always\|prompt]` | Install `prepare-commit-msg` hook |
| `codeassay uninstall-hook` | Remove the hook |

## How It Works

**AI Commit Detection** is layered — configurable in `.codeassay.toml`:

1. **User-defined rules** (highest priority) — match commits by author regex, branch pattern, commit-message regex, or author-plus-date-window.
2. **Built-in profiles** — shipped detectors for Claude Code, GitHub Copilot, Cursor, Aider, Windsurf, ChatGPT, and Gemini. Enabled by default, disable individually.
3. **Probabilistic scorer** (opt-in) — weights weak signals (diff shape, message structure, commit velocity, emoji, boilerplate headers, file diversity, punctuation) for commits no deterministic rule caught.

First match wins. Run `codeassay config init` to scaffold a starter config, `codeassay config show` to inspect the effective config, and `codeassay detect-test <hash>` to dry-run detection against a single commit.

**Per-author fingerprint detection** (opt-in) catches AI commits from authors with ≥20 prior commits by comparing each commit against the author's historical baseline on 5 metrics (diff size, comment ratio, identifier entropy, punctuation density, message length). Flags when ≥3 metrics diverge ≥2σ. Enable in `.codeassay.toml`:

```toml
[fingerprint]
enabled = true
min_prior_commits = 20
sigma_threshold = 2.0
min_divergent_metrics = 3
```

Use `codeassay detect-test <hash>` to see per-metric Z-scores when tuning thresholds.

To reliably tag AI commits going forward, install a git hook:

```bash
codeassay install-hook --tool cursor --mode always
```

This appends `AI-Assisted: cursor` to each commit message (idempotent — skips if a Co-Authored-By AI trailer is already present).

**Rework Detection** traces subsequent commits that modify AI-authored lines using `git blame` ancestry within a configurable time window (default: 14 days).

**Classification** categorizes rework into 7 types using commit message keywords and diff shape analysis:
- Bug fix, Misunderstanding, Test failure, Style/convention violation
- Security issue, Incomplete implementation, Over-engineering

## Turnover Rate

**Turnover Rate** measures the fraction of lines added in a lookback window that are subsequently discarded or rewritten. Computed separately for AI and human cohorts; the **AI/human ratio** is the headline number. CodeAssay ships `benchmarks.json` with industry baselines (pre-AI 3.3%, 2026 avg 5.7%, healthy target <4%) so your report can show percentile vs industry.

Configure thresholds in `.codeassay.toml`:

```toml
[turnover]
lookback_days = 90
rewrite_window_days = 30
yellow_threshold = 0.04
red_threshold = 0.06
```

Fail CI builds on excessive turnover:

```bash
codeassay scan . --fail-on=turnover-red
```

## Dashboard

Generate an interactive HTML dashboard with charts and visualizations:

```bash
codeassay dashboard
```

Opens a self-contained HTML file in your browser with:
- Summary metric cards (AI commit rate, first-pass success, rework rate, MTTR)
- Rework category doughnut chart with percentages
- Monthly trend line chart (AI commits vs rework events)
- Top rework file hotspots
- Rework by AI tool comparison

The dashboard works offline, requires no server, and is shareable — copy the HTML file to screenshot or embed in publications. Use `--no-open` to generate without opening the browser, or `--output path.html` to save to a custom location.

## Ignoring Files

Create a `.codeassayignore` file in your repo root to exclude files from analysis. Uses gitignore-style patterns:

```
# Exclude documentation and config noise
*.md
.DS_Store
.organization

# Exclude a directory (one level)
docs/*

# Exclude a directory (recursive)
docs/**
```

Ignored files are filtered from both AI commit tracking and rework detection, giving you cleaner metrics focused on actual code quality.

## Data Storage

Scan data is stored in `.codeassay/quality.db` (SQLite) inside each scanned repo. Query it directly with any SQL tool:

```bash
sqlite3 .codeassay/quality.db "SELECT tool, COUNT(*) FROM ai_commits GROUP BY tool"
```

## Claude Code Plugin

Install as a Claude Code plugin to use `/codeassay` within Claude Code sessions.

## License

MIT
