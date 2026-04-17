---
name: codeassay
description: Analyze AI-authored code quality — scan repos for AI commits, detect rework, classify root causes, generate reports
---

# AI Code Quality Analysis

Analyze the quality of AI-generated code in git repositories.

## Commands

### Scan a repository
```bash
codeassay scan .
```

### Generate a CLI report
```bash
codeassay report
```

### Generate a markdown report
```bash
codeassay report --format markdown --output docs/codeassay/$(date +%Y-%m-%d)-report.md
```

### List AI-authored commits
```bash
codeassay commits --ai-only
```

### List rework events
```bash
codeassay rework
```

### Reclassify a rework event
```bash
codeassay reclassify <commit-hash> <category>
```

Categories: bug_fix, misunderstanding, test_failure, style_violation, security_issue, incomplete_implementation, over_engineering

### Export raw data
```bash
codeassay export --format json
```

## Filters

All listing commands support:
- `--since YYYY-MM-DD` — start date
- `--until YYYY-MM-DD` — end date
- `--tool <name>` — filter by AI tool (claude_code, copilot, gpt)
- `--project <name>` — filter by repository
