# Configurable AI Commit Detection — Design

**Status:** Draft
**Date:** 2026-04-18
**Scope:** Detection pipeline, config schema, CLI, DB migration, testing

## Problem

CodeAssay currently identifies AI-authored commits by scanning commit messages for a small set of `Co-Authored-By:` trailers (Claude, Copilot, GPT, Gemini) and an `AI-Assisted: true` manual tag. Several real-world cases slip through:

1. **Tools that don't emit trailers** — Cursor, Windsurf, Aider, and others leave commits that look ordinary.
2. **Policy-stripped trailers** — projects (including this repo, per commit `89e5e09`) block AI attribution trailers at CI, erasing the signal even when the tool added one.
3. **Historical scans** — existing repos have years of commits, some AI-assisted, with no trailers ever added.

Manual tagging every commit is cumbersome. Without configurable detection, CodeAssay's metrics undercount AI work in exactly the environments most likely to benefit from analyzing it.

## Goals

- Detect AI commits without trailers through configurable, deterministic signals.
- Ship useful defaults so casual users get value out-of-the-box.
- Offer an opt-in probabilistic tier for recall-oriented analysis.
- Provide commit-time tooling that makes reliable tagging trivial going forward.
- Keep the system understandable: TOML config, no plugins, no network, no ML model downloads.

## Non-Goals

- Plugin/entry-point discovery for third-party detectors.
- ML-based classification.
- Cross-repo learning.
- GUI config editor.
- Auto-installing git hooks on `pip install`.

## Detection Posture

Layered, with strict precedence:

1. **User-defined deterministic rules** (highest priority) — explicit author, branch, message, or time-window matches configured per-repo.
2. **Built-in profiles** — curated rule bundles for known AI tools, enabled by default, individually toggleable.
3. **Probabilistic scorer** (opt-in) — weighted-signal 0–1 score for commits that no deterministic rule caught.

First match wins. If no tier matches, the commit is human-authored.

## Configuration

Config file: `.codeassay.toml` at the repo root, alongside `.codeassayignore`. Parsed with stdlib `tomllib`.

### Schema

```toml
# Built-in profiles. Enabled by default; disable individually if noisy for this repo.
[profiles.claude_code]
enabled = true
[profiles.copilot]
enabled = true
[profiles.cursor]
enabled = true
[profiles.aider]
enabled = true
[profiles.windsurf]
enabled = true
[profiles.gpt]
enabled = true
[profiles.gemini]
enabled = true

# User-defined deterministic rules. Evaluated in category order:
# detect.author -> detect.branch -> detect.message -> detect.window.
# First match wins within each category; first category to match wins overall.

[[detect.author]]
pattern = "cursor-agent@.*"   # regex, matched against author email then author name
tool = "cursor"
confidence = "high"

[[detect.branch]]
pattern = "^(ai|claude|copilot)/.*"
tool = "claude_code"
confidence = "medium"

[[detect.message]]
pattern = '^\[AI\]'
tool = "unknown"
confidence = "high"

[[detect.window]]
author = "jeff@example.com"    # required; regex matched against author email
start = "2026-01-01"           # inclusive, ISO date
end = "2026-03-15"             # inclusive, ISO date
tool = "claude_code"
confidence = "high"
note = "AI-heavy sprint"

# Probabilistic scorer. Opt-in. Only runs for commits unmatched by deterministic tiers.
[score]
enabled = false
threshold = 0.7

[score.weights]
diff_wholesale_rewrite = 0.20
message_structured_body = 0.15
commit_velocity = 0.15
emoji_indicator = 0.10
message_boilerplate = 0.15
file_diversity = 0.10
perfect_punctuation = 0.15
```

### Validation rules

- `confidence` must be `"high" | "medium" | "low"`. Default `"medium"` if absent.
- `tool` is free-form; `"unknown"` is the conventional fallback.
- Each regex is compiled at config load; invalid regex fails loudly with file, rule index, and the offending pattern.
- Score weights must sum to a value in `[0.99, 1.01]` (tolerance for float rounding). Out-of-range → warn and normalize.
- Unknown top-level keys warn but do not fail, so configs remain forward-compatible.
- Overlapping `detect.window` ranges for the same author are allowed; first match wins.

## Evaluation pipeline

For each commit in `scan_repo`:

```
detection.classify(commit, config) -> Detection | None

1. Run user rules, ordered by category:
     detect.author[*] -> detect.branch[*] -> detect.message[*] -> detect.window[*]
   First match returns Detection(source="user:detect.<cat>[<idx>]", tool=..., confidence=..., method="rule").

2. If no user match, run enabled profiles in alphabetic order by profile
   filename (config declaration order is ignored — config only toggles
   enabled/disabled). Each profile is itself a set of rules evaluated in the
   same category order as user rules.
   First match returns Detection(source="profile:<name>", tool=<profile>, confidence=..., method="profile").

3. If still no match and config.score.enabled:
   score = scorer.score(commit)
   If score >= threshold:
     Return Detection(source=f"score:{score:.2f}", tool="unknown", confidence="low", method="score").

4. Otherwise return None (commit is human-authored; not stored in ai_commits).
```

`detection.classify` is the single public entry point; `scanner.py` is refactored into a thin orchestrator calling it.

## Built-in profiles

Profiles ship as TOML files in `src/codeassay/profiles/`, auto-discovered at startup. Each profile uses the same schema as user rules (author/branch/message/window) so there is one rule engine, not two. Adding a new AI tool is a single-file PR.

Initial set:

| Profile | Primary signals |
|---|---|
| `claude_code` | Message `Co-Authored-By:.*Claude`; branch `^claude-.*`, `^superpowers-.*`; message `🤖 Generated with \[Claude Code\]` |
| `copilot` | Message `Co-Authored-By:.*Copilot`; author `.*@users\.noreply\.github\.com` combined with Copilot message signatures |
| `cursor` | Author `cursor-agent@.*`, `.*@cursor\.com`; branch `^cursor/.*`; message trailing `Generated by Cursor` |
| `aider` | Message starts with `aider: `; message contains `# Aider` footer |
| `windsurf` | Author `.*@codeium\.com`, `windsurf-.*`; message `Windsurf AI` signature |
| `gpt` | Message `Co-Authored-By:.*GPT` |
| `gemini` | Message `Co-Authored-By:.*Gemini` |

**Caveat:** exact patterns for `cursor`, `windsurf`, and `aider` are inferred from public docs and need verification against real commits before v1 release. Profiles marked with a leading comment noting "placeholder — verify before release."

Users can disable any profile with `enabled = false`. Users can override by declaring a higher-priority `detect.*` rule with a different tool attribution.

## Probabilistic scorer

Only runs when `[score].enabled = true` and all deterministic tiers missed. Produces a 0–1 score via weighted sum of normalized signals.

| Signal | What it measures | Default weight |
|---|---|---|
| `diff_wholesale_rewrite` | `(added + removed) / max(file_size, 1)` averaged across touched files | 0.20 |
| `message_structured_body` | Body has multi-paragraph + bullet lists + consistent tense | 0.15 |
| `commit_velocity` | Seconds since prior commit by same author; `<60s` scores 1.0, `>1h` scores 0.0, linear between | 0.15 |
| `emoji_indicator` | Presence of 🤖 ✨ 🚀 ♻️ in message | 0.10 |
| `message_boilerplate` | Body contains "Summary:", "Changes:", "Test plan:" section headers | 0.15 |
| `file_diversity` | Touches unrelated file types (`.py` + `.md` + `.yaml`) in one commit | 0.10 |
| `perfect_punctuation` | No double spaces; consistent period/capitalization; no obvious typos in message | 0.15 |

Weights sum to 1.0. Threshold default 0.7. Both are tunable in `[score]`.

Output on match: `tool="unknown"`, `confidence="low"`, `method="score"`, `source="score:<value>"` (value rounded to 2 decimals).

**Honesty about limitations** (documented in README and `codeassay config init` comments):

- Heuristic, not a classifier. False positives on disciplined committers with structured templates.
- No training, no ML dependency — pure Python, no model download.
- Intended as a diagnostic. The dashboard visually distinguishes `confidence=low` commits.
- Disabled by default. Users opt in knowingly.

## Database migration

`src/codeassay/db.py` adds one column to `ai_commits`:

```sql
ALTER TABLE ai_commits ADD COLUMN source TEXT;
```

- Added idempotently on connection open (check `PRAGMA table_info`, ALTER if missing).
- Legacy rows show `source = NULL`; new rows populated.
- No backfill. Users wanting populated `source` for historical commits delete `.codeassay/quality.db` and rescan.

`detection_method` stays as a coarse bucket. Legacy rows keep the existing values (`co_author_trailer`, `branch_pattern`, `manual_tag`). New rows written by the refactored pipeline use one of `rule`, `profile`, or `score`. `source` is the fine-grained pointer for new rows (`user:detect.author[0]`, `profile:cursor`, `score:0.82`) and `NULL` for legacy rows.

## CLI additions

**New subcommands:**

| Command | Purpose |
|---|---|
| `codeassay tag [--tool <name>]` | Adds `AI-Assisted: <tool>` trailer to a commit message. Called from a `prepare-commit-msg` hook (uses `$1` path) or run standalone (amends HEAD via `git commit --amend --no-edit --trailer`). Defaults `--tool unknown`. |
| `codeassay install-hook [--tool <name>] [--mode always\|prompt]` | Installs a `prepare-commit-msg` hook into `.git/hooks/`. `always` adds the trailer unconditionally; `prompt` asks interactively per commit. Never overwrites an existing hook without `--force`. |
| `codeassay uninstall-hook` | Removes the CodeAssay hook. Fails loudly if the hook was modified manually (checked via shebang comment marker CodeAssay writes). |
| `codeassay config init` | Writes a starter `.codeassay.toml` with all profiles listed, plus commented-out examples for user rules and the scorer. Fails if file exists (unless `--force`). |
| `codeassay config show` | Prints the merged effective config — profiles, user rules, score settings — as resolved for the current repo. |
| `codeassay detect-test <commit-hash>` | Dry-run: runs the full detection pipeline against one commit and prints which rule / profile / signal matched (or didn't), with reasoning. Essential for debugging false positives and tuning thresholds. |

**Hook idempotency:** before writing a trailer, `codeassay tag` checks for an existing `AI-Assisted:` or `Co-Authored-By:` trailer naming a known AI tool. If found, it no-ops. Safe to run repeatedly on the same commit.

**New flags on existing commands:**

| Flag | Command | Purpose |
|---|---|---|
| `--with-scorer` | `scan` | Force-enables scorer for this run without editing config. |
| `--dry-run` | `scan` | Reports what would be stored without writing to DB. Useful with `--with-scorer` for threshold tuning. |
| `--source <glob>` | `commits`, `rework`, `report` | Filter by detection source (e.g., `--source "profile:*"`, `--source "score:*"`). |

## Code structure

```
src/codeassay/
  detection/
    __init__.py        # public entry: classify(commit, config) -> Detection | None
    config.py          # loads & validates .codeassay.toml via stdlib tomllib
    rules.py           # Rule base + AuthorRule, BranchRule, MessageRule, WindowRule
    profiles.py        # discovers & loads profiles/*.toml
    scorer.py          # probabilistic scorer, isolated behind config.score.enabled
  profiles/
    claude_code.toml
    copilot.toml
    cursor.toml
    aider.toml
    windsurf.toml
    gpt.toml
    gemini.toml
  tag.py               # `codeassay tag` + install-hook / uninstall-hook logic
  scanner.py           # slimmed to orchestration: iterate commits, call detection.classify()
```

`scanner.py` loses its regex constants (they move into seed profiles) and its `detect_ai_tool` / `_get_detection_method` functions. A thin `detect_ai_tool(message)` shim may stay for existing callers during transition.

## Testing

- **Unit tests per rule class** (`tests/detection/test_rules.py`): positive/negative match for each rule type. Invalid regex → validation error at config load, not at scan time.
- **Profile fixture tests** (`tests/detection/test_profiles.py`): one synthetic commit per profile proving the profile catches it and doesn't catch an obviously-human commit.
- **Scorer tests** (`tests/detection/test_scorer.py`): per-signal unit tests plus a small fixture set of realistic commits with expected score ranges (tolerant, not exact).
- **Integration** (`tests/test_scan_integration.py`): build a tiny fixture repo with mixed commits (trailers, cursor-style, human) and run full `scan_repo`, asserting expected `ai_commits` rows and `source` values.
- **CLI tests** (`tests/test_cli_tag.py`): `codeassay tag` idempotency; `install-hook` / `uninstall-hook` round-trip; `config init` creates a valid file; `detect-test` output format.
- **Config loading tests** (`tests/detection/test_config.py`): invalid TOML, bad regex, overlapping windows, unknown fields (warn, not fail), score weight normalization.

## What we deliberately do NOT do

- Auto-install git hooks on `pip install`. Users must explicitly run `codeassay install-hook`.
- Network calls or telemetry.
- Modification of commits outside the user's explicit action.
- Fail-closed on config parse errors in one rule — other rules still load; bad rule is skipped with a warning.

## Open questions for implementation

- Final pattern list for `cursor`, `windsurf`, `aider` profiles needs verification against real commits before v1 release.
- Whether `detect-test` should also accept a range (`--since`, `--until`) or just one hash. (Start with one hash; extend if demand shows up.)
- Whether `--source` filter syntax should be glob (`"profile:*"`) or exact match. (Start with glob; easier UX.)
