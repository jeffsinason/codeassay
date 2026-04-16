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
| `codeassay scan <paths>` | Scan repos for AI commits and rework |
| `codeassay report` | Generate quality report (CLI or markdown) |
| `codeassay commits` | List AI-authored commits |
| `codeassay rework` | List rework events with classification |
| `codeassay reclassify <commit> <category>` | Override a classification |
| `codeassay export --format json` | Export raw data |

## How It Works

**AI Commit Detection** identifies AI-authored commits via:
1. `Co-Authored-By` trailers (Claude, Copilot, GPT)
2. Branch naming patterns (Superpowers worktrees)
3. Manual `AI-Assisted: true` trailers

**Rework Detection** traces subsequent commits that modify AI-authored lines using `git blame` ancestry within a configurable time window (default: 14 days).

**Classification** categorizes rework into 7 types using commit message keywords and diff shape analysis:
- Bug fix, Misunderstanding, Test failure, Style/convention violation
- Security issue, Incomplete implementation, Over-engineering

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
