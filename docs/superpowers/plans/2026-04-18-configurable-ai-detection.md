# Configurable AI Commit Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hard-coded commit-message regex detection with a layered, configurable pipeline (user rules → built-in profiles → opt-in probabilistic scorer) so CodeAssay catches AI commits that lack `Co-Authored-By:` trailers.

**Architecture:** New `src/codeassay/detection/` package owns all detection logic. `scanner.py` becomes a thin orchestrator that calls `detection.classify()`. Built-in AI-tool profiles ship as TOML files in `src/codeassay/profiles/`. User rules and scorer settings live in `.codeassay.toml` at the repo root. A new `source` column in `ai_commits` records which rule/profile/signal matched. New CLI: `codeassay tag`, `install-hook`, `uninstall-hook`, `config init`, `config show`, `detect-test`, plus `--with-scorer`, `--dry-run`, `--source` flags on existing commands.

**Tech Stack:** Python 3.11+ (stdlib `tomllib`), stdlib `sqlite3`, `subprocess` for git, `pytest` for tests. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-04-18-configurable-ai-detection-design.md`

---

## Task 1: Bump Python minimum to 3.11

The detection module uses `tomllib` from stdlib, which is only available in 3.11+. Bump the project requirement.

**Files:**
- Modify: `pyproject.toml:11`

- [ ] **Step 1: Edit pyproject.toml**

Change `requires-python = ">=3.10"` to `requires-python = ">=3.11"`.

- [ ] **Step 2: Add classifier for 3.11**

Ensure `pyproject.toml` lists Python 3.11 explicitly:

```toml
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Topic :: Software Development :: Quality Assurance",
]
```

- [ ] **Step 3: Verify test suite still runs**

Run: `pytest -q`
Expected: All existing tests pass.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: require Python 3.11 for stdlib tomllib support"
```

---

## Task 2: Add `source` column to `ai_commits` (DB migration)

Add the fine-grained detection pointer column. Migration must be idempotent — old DBs open without re-init.

**Files:**
- Modify: `src/codeassay/db.py:6-37` (SCHEMA), `src/codeassay/db.py:40-46` (`init_db`), `src/codeassay/db.py:56-78` (`insert_ai_commit`)
- Test: `tests/test_db.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_db.py`:

```python
import sqlite3
from codeassay.db import init_db, insert_ai_commit, get_ai_commits


def test_ai_commits_has_source_column(tmp_path):
    db_path = tmp_path / "q.db"
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(ai_commits)")]
    assert "source" in cols


def test_legacy_db_gets_source_column_on_init(tmp_path):
    db_path = tmp_path / "q.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    legacy = sqlite3.connect(db_path)
    legacy.executescript(
        """CREATE TABLE ai_commits (
            commit_hash TEXT NOT NULL,
            repo_path TEXT NOT NULL,
            author TEXT NOT NULL,
            date TEXT NOT NULL,
            message TEXT NOT NULL,
            tool TEXT NOT NULL,
            detection_method TEXT NOT NULL,
            confidence TEXT NOT NULL,
            files_changed TEXT NOT NULL,
            PRIMARY KEY (commit_hash, repo_path)
        );"""
    )
    legacy.commit()
    legacy.close()
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(ai_commits)")]
    assert "source" in cols


def test_insert_ai_commit_accepts_source(db_conn):
    insert_ai_commit(
        db_conn, commit_hash="abc", repo_path="/r", author="a",
        date="2026-04-18T00:00:00Z", message="m", tool="claude_code",
        detection_method="profile", confidence="high",
        files_changed="a.py", source="profile:claude_code",
    )
    rows = get_ai_commits(db_conn, repo_path="/r")
    assert rows[0]["source"] == "profile:claude_code"


def test_insert_ai_commit_source_defaults_to_none(db_conn):
    insert_ai_commit(
        db_conn, commit_hash="def", repo_path="/r", author="a",
        date="2026-04-18T00:00:00Z", message="m", tool="claude_code",
        detection_method="co_author_trailer", confidence="high",
        files_changed="a.py",
    )
    rows = get_ai_commits(db_conn, repo_path="/r")
    assert rows[0]["source"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_db.py -v -k "source"`
Expected: FAIL — column `source` does not exist.

- [ ] **Step 3: Update SCHEMA**

In `src/codeassay/db.py`, change the `ai_commits` table definition in `SCHEMA` to include `source TEXT` before the PRIMARY KEY:

```python
SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_commits (
    commit_hash TEXT NOT NULL,
    repo_path TEXT NOT NULL,
    author TEXT NOT NULL,
    date TEXT NOT NULL,
    message TEXT NOT NULL,
    tool TEXT NOT NULL,
    detection_method TEXT NOT NULL,
    confidence TEXT NOT NULL,
    files_changed TEXT NOT NULL,
    source TEXT,
    PRIMARY KEY (commit_hash, repo_path)
);
```

(Keep the rest of `SCHEMA` — `rework_events` and `scan_metadata` — unchanged.)

- [ ] **Step 4: Add idempotent migration to `init_db`**

Replace the body of `init_db` in `src/codeassay/db.py`:

```python
def init_db(db_path: Path) -> None:
    """Create the database and tables if they don't exist. Applies idempotent migrations."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    # Idempotent migration: ensure ai_commits.source exists for legacy DBs.
    cols = [r[1] for r in conn.execute("PRAGMA table_info(ai_commits)")]
    if "source" not in cols:
        conn.execute("ALTER TABLE ai_commits ADD COLUMN source TEXT")
    conn.commit()
    conn.close()
```

- [ ] **Step 5: Update `insert_ai_commit` to accept `source`**

Replace `insert_ai_commit` in `src/codeassay/db.py`:

```python
def insert_ai_commit(
    conn: sqlite3.Connection,
    *,
    commit_hash: str,
    repo_path: str,
    author: str,
    date: str,
    message: str,
    tool: str,
    detection_method: str,
    confidence: str,
    files_changed: str,
    source: str | None = None,
) -> None:
    """Insert an AI commit, ignoring duplicates."""
    conn.execute(
        """INSERT OR IGNORE INTO ai_commits
           (commit_hash, repo_path, author, date, message, tool,
            detection_method, confidence, files_changed, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (commit_hash, repo_path, author, date, message, tool,
         detection_method, confidence, files_changed, source),
    )
    conn.commit()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_db.py -v`
Expected: All pass, including new source-related tests and pre-existing ones.

- [ ] **Step 7: Commit**

```bash
git add src/codeassay/db.py tests/test_db.py
git commit -m "feat(db): add source column to ai_commits with idempotent migration"
```

---

## Task 3: Detection package skeleton + `Detection` dataclass

Create the new module and the result type that every detector returns.

**Files:**
- Create: `src/codeassay/detection/__init__.py`
- Create: `tests/detection/__init__.py` (empty)
- Create: `tests/detection/test_detection_types.py`

- [ ] **Step 1: Write the failing test**

Create `tests/detection/__init__.py` as an empty file, then create `tests/detection/test_detection_types.py`:

```python
from codeassay.detection import Detection


def test_detection_dataclass_fields():
    d = Detection(
        tool="claude_code",
        confidence="high",
        method="profile",
        source="profile:claude_code",
    )
    assert d.tool == "claude_code"
    assert d.confidence == "high"
    assert d.method == "profile"
    assert d.source == "profile:claude_code"


def test_detection_is_frozen():
    import dataclasses
    d = Detection(tool="t", confidence="high", method="rule", source="s")
    with __import__("pytest").raises(dataclasses.FrozenInstanceError):
        d.tool = "other"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/detection/ -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'codeassay.detection'`.

- [ ] **Step 3: Create the detection package**

Create `src/codeassay/detection/__init__.py`:

```python
"""Configurable AI commit detection pipeline."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Detection:
    """Result of classifying a single commit as AI-authored.

    Attributes:
        tool: AI tool name (e.g. "claude_code", "cursor", "unknown").
        confidence: One of "high", "medium", "low".
        method: Coarse bucket — "rule", "profile", or "score".
        source: Fine-grained pointer — e.g. "user:detect.author[0]",
                "profile:cursor", "score:0.82".
    """

    tool: str
    confidence: str
    method: str
    source: str


__all__ = ["Detection"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/detection/ -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codeassay/detection/__init__.py tests/detection/__init__.py tests/detection/test_detection_types.py
git commit -m "feat(detection): add Detection dataclass and package skeleton"
```

---

## Task 4: Config loader (`.codeassay.toml`)

Load and validate user config from the repo root. Compile regex patterns at load time so invalid patterns fail fast.

**Files:**
- Create: `src/codeassay/detection/config.py`
- Create: `tests/detection/test_config.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/detection/test_config.py`:

```python
import re
from pathlib import Path
import pytest

from codeassay.detection.config import (
    DetectionConfig, RuleSpec, ScoreConfig, WindowSpec, load_config,
)


def _write(tmp_path: Path, body: str) -> Path:
    f = tmp_path / ".codeassay.toml"
    f.write_text(body)
    return tmp_path


def test_load_config_missing_file_returns_defaults(tmp_path):
    cfg = load_config(tmp_path)
    assert isinstance(cfg, DetectionConfig)
    assert cfg.author_rules == []
    assert cfg.branch_rules == []
    assert cfg.message_rules == []
    assert cfg.window_rules == []
    assert cfg.disabled_profiles == set()
    assert cfg.score.enabled is False
    assert cfg.score.threshold == 0.7


def test_load_config_parses_author_rule(tmp_path):
    _write(tmp_path, """
[[detect.author]]
pattern = "cursor-agent@.*"
tool = "cursor"
confidence = "high"
""")
    cfg = load_config(tmp_path)
    assert len(cfg.author_rules) == 1
    rule = cfg.author_rules[0]
    assert isinstance(rule, RuleSpec)
    assert rule.pattern.pattern == "cursor-agent@.*"
    assert rule.tool == "cursor"
    assert rule.confidence == "high"


def test_load_config_parses_branch_message_window_rules(tmp_path):
    _write(tmp_path, """
[[detect.branch]]
pattern = "^ai/.*"
tool = "claude_code"

[[detect.message]]
pattern = '^\\\\[AI\\\\]'
tool = "unknown"

[[detect.window]]
author = "jeff@example.com"
start = "2026-01-01"
end = "2026-03-15"
tool = "claude_code"
""")
    cfg = load_config(tmp_path)
    assert len(cfg.branch_rules) == 1
    assert len(cfg.message_rules) == 1
    assert len(cfg.window_rules) == 1
    w = cfg.window_rules[0]
    assert isinstance(w, WindowSpec)
    assert w.author.pattern == "jeff@example.com"
    assert w.start == "2026-01-01"
    assert w.end == "2026-03-15"
    assert w.tool == "claude_code"


def test_confidence_defaults_to_medium(tmp_path):
    _write(tmp_path, """
[[detect.author]]
pattern = "x@y.com"
tool = "cursor"
""")
    cfg = load_config(tmp_path)
    assert cfg.author_rules[0].confidence == "medium"


def test_invalid_regex_raises(tmp_path):
    _write(tmp_path, """
[[detect.author]]
pattern = "[unclosed"
tool = "cursor"
""")
    with pytest.raises(ValueError) as exc:
        load_config(tmp_path)
    assert "detect.author[0]" in str(exc.value)


def test_disabled_profiles(tmp_path):
    _write(tmp_path, """
[profiles.cursor]
enabled = false
[profiles.aider]
enabled = true
""")
    cfg = load_config(tmp_path)
    assert "cursor" in cfg.disabled_profiles
    assert "aider" not in cfg.disabled_profiles


def test_score_config_loaded(tmp_path):
    _write(tmp_path, """
[score]
enabled = true
threshold = 0.65

[score.weights]
diff_wholesale_rewrite = 0.5
message_structured_body = 0.5
""")
    cfg = load_config(tmp_path)
    assert cfg.score.enabled is True
    assert cfg.score.threshold == 0.65
    assert cfg.score.weights["diff_wholesale_rewrite"] == 0.5


def test_score_weights_warn_on_bad_sum(tmp_path, capsys):
    _write(tmp_path, """
[score]
enabled = true

[score.weights]
diff_wholesale_rewrite = 0.3
message_structured_body = 0.3
""")
    cfg = load_config(tmp_path)
    captured = capsys.readouterr()
    assert "weights" in captured.err.lower()
    # Should normalize
    total = sum(cfg.score.weights.values())
    assert abs(total - 1.0) < 0.01


def test_unknown_top_level_key_warns(tmp_path, capsys):
    _write(tmp_path, """
[something_unknown]
key = "value"
""")
    cfg = load_config(tmp_path)
    captured = capsys.readouterr()
    assert "unknown" in captured.err.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/detection/test_config.py -v`
Expected: FAIL — `codeassay.detection.config` does not exist.

- [ ] **Step 3: Implement the config module**

Create `src/codeassay/detection/config.py`:

```python
"""Load and validate .codeassay.toml into typed config objects."""

from __future__ import annotations

import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_THRESHOLD = 0.7
DEFAULT_WEIGHTS = {
    "diff_wholesale_rewrite": 0.20,
    "message_structured_body": 0.15,
    "commit_velocity": 0.15,
    "emoji_indicator": 0.10,
    "message_boilerplate": 0.15,
    "file_diversity": 0.10,
    "perfect_punctuation": 0.15,
}
VALID_CONFIDENCE = {"high", "medium", "low"}
KNOWN_TOP_LEVEL_KEYS = {"profiles", "detect", "score"}


@dataclass(frozen=True)
class RuleSpec:
    pattern: re.Pattern
    tool: str
    confidence: str = "medium"


@dataclass(frozen=True)
class WindowSpec:
    author: re.Pattern
    start: str  # ISO date YYYY-MM-DD, inclusive
    end: str    # ISO date YYYY-MM-DD, inclusive
    tool: str
    confidence: str = "medium"
    note: str = ""


@dataclass
class ScoreConfig:
    enabled: bool = False
    threshold: float = DEFAULT_THRESHOLD
    weights: dict = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))


@dataclass
class DetectionConfig:
    author_rules: list[RuleSpec] = field(default_factory=list)
    branch_rules: list[RuleSpec] = field(default_factory=list)
    message_rules: list[RuleSpec] = field(default_factory=list)
    window_rules: list[WindowSpec] = field(default_factory=list)
    disabled_profiles: set[str] = field(default_factory=set)
    score: ScoreConfig = field(default_factory=ScoreConfig)


def _warn(msg: str) -> None:
    print(f"codeassay: warning: {msg}", file=sys.stderr)


def _compile(pattern: str, location: str) -> re.Pattern:
    try:
        return re.compile(pattern)
    except re.error as e:
        raise ValueError(f"invalid regex at {location}: {e}") from e


def _parse_confidence(raw: dict, location: str) -> str:
    c = raw.get("confidence", "medium")
    if c not in VALID_CONFIDENCE:
        _warn(f"{location}: unknown confidence {c!r}, defaulting to 'medium'")
        return "medium"
    return c


def _parse_rule_list(rules_raw: list, category: str) -> list[RuleSpec]:
    out = []
    for i, entry in enumerate(rules_raw):
        location = f"detect.{category}[{i}]"
        if "pattern" not in entry or "tool" not in entry:
            _warn(f"{location}: missing required field (pattern or tool); skipping")
            continue
        out.append(RuleSpec(
            pattern=_compile(entry["pattern"], location),
            tool=entry["tool"],
            confidence=_parse_confidence(entry, location),
        ))
    return out


def _parse_window_list(rules_raw: list) -> list[WindowSpec]:
    out = []
    for i, entry in enumerate(rules_raw):
        location = f"detect.window[{i}]"
        required = ("author", "start", "end", "tool")
        missing = [k for k in required if k not in entry]
        if missing:
            _warn(f"{location}: missing required fields {missing}; skipping")
            continue
        out.append(WindowSpec(
            author=_compile(entry["author"], location),
            start=entry["start"],
            end=entry["end"],
            tool=entry["tool"],
            confidence=_parse_confidence(entry, location),
            note=entry.get("note", ""),
        ))
    return out


def _parse_score(score_raw: dict) -> ScoreConfig:
    weights = dict(DEFAULT_WEIGHTS)
    user_weights = score_raw.get("weights", {})
    if user_weights:
        weights = dict(user_weights)
        total = sum(weights.values())
        if not (0.99 <= total <= 1.01):
            _warn(f"score.weights sum to {total:.3f}, not ~1.0; normalizing")
            if total > 0:
                weights = {k: v / total for k, v in weights.items()}
    return ScoreConfig(
        enabled=bool(score_raw.get("enabled", False)),
        threshold=float(score_raw.get("threshold", DEFAULT_THRESHOLD)),
        weights=weights,
    )


def _parse_disabled_profiles(profiles_raw: dict) -> set[str]:
    disabled = set()
    for name, settings in profiles_raw.items():
        if isinstance(settings, dict) and settings.get("enabled") is False:
            disabled.add(name)
    return disabled


def load_config(repo_path: Path) -> DetectionConfig:
    """Load .codeassay.toml from repo_path. Returns defaults if absent."""
    cfg_file = Path(repo_path) / ".codeassay.toml"
    if not cfg_file.exists():
        return DetectionConfig()

    with cfg_file.open("rb") as f:
        raw = tomllib.load(f)

    unknown = set(raw.keys()) - KNOWN_TOP_LEVEL_KEYS
    for key in unknown:
        _warn(f".codeassay.toml: unknown top-level key {key!r} (ignored)")

    detect = raw.get("detect", {})
    return DetectionConfig(
        author_rules=_parse_rule_list(detect.get("author", []), "author"),
        branch_rules=_parse_rule_list(detect.get("branch", []), "branch"),
        message_rules=_parse_rule_list(detect.get("message", []), "message"),
        window_rules=_parse_window_list(detect.get("window", [])),
        disabled_profiles=_parse_disabled_profiles(raw.get("profiles", {})),
        score=_parse_score(raw.get("score", {})),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/detection/test_config.py -v`
Expected: PASS — all 9 tests.

- [ ] **Step 5: Commit**

```bash
git add src/codeassay/detection/config.py tests/detection/test_config.py
git commit -m "feat(detection): add .codeassay.toml config loader with validation"
```

---

## Task 5: Rule evaluation — `AuthorRule`, `BranchRule`, `MessageRule`, `WindowRule`

All rule matching lives in one module. Each rule type gets a `match(commit, ctx) -> bool` function. The commit dict contains `{hash, author, author_email, date, message}`. `ctx` supplies extras needed only by some rules (e.g. branch lookup).

**Files:**
- Create: `src/codeassay/detection/rules.py`
- Create: `tests/detection/test_rules.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/detection/test_rules.py`:

```python
import re
from datetime import date
import pytest

from codeassay.detection.config import RuleSpec, WindowSpec
from codeassay.detection.rules import (
    match_author, match_branch, match_message, match_window,
)


def _commit(**overrides):
    base = {
        "hash": "abc123",
        "author": "Jane Dev",
        "author_email": "jane@example.com",
        "date": "2026-02-15T12:00:00+00:00",
        "message": "feat: add foo",
    }
    base.update(overrides)
    return base


def _rule(pattern: str, tool="x", confidence="high") -> RuleSpec:
    return RuleSpec(pattern=re.compile(pattern), tool=tool, confidence=confidence)


# ---- author rule ----

def test_match_author_by_email():
    assert match_author(_rule("jane@.*"), _commit()) is True


def test_match_author_by_name():
    assert match_author(_rule("Jane Dev"), _commit()) is True


def test_match_author_no_match():
    assert match_author(_rule("alice@.*"), _commit()) is False


# ---- branch rule ----

def test_match_branch_hit():
    rule = _rule("^cursor/.*")
    assert match_branch(rule, _commit(), branches={"cursor/feature-x"}) is True


def test_match_branch_multiple_branches_any_hit():
    rule = _rule("^ai/.*")
    assert match_branch(rule, _commit(), branches={"main", "ai/foo"}) is True


def test_match_branch_no_match():
    rule = _rule("^cursor/.*")
    assert match_branch(rule, _commit(), branches={"main"}) is False


def test_match_branch_empty_branches():
    rule = _rule("^cursor/.*")
    assert match_branch(rule, _commit(), branches=set()) is False


# ---- message rule ----

def test_match_message_hit():
    rule = _rule(r"^\[AI\]")
    assert match_message(rule, _commit(message="[AI] feat: thing")) is True


def test_match_message_multiline_trailer():
    rule = _rule(r"Co-Authored-By:.*Claude")
    assert match_message(
        rule,
        _commit(message="feat: x\n\nCo-Authored-By: Claude <x@y>"),
    ) is True


def test_match_message_no_match():
    rule = _rule(r"^\[AI\]")
    assert match_message(rule, _commit(message="feat: thing")) is False


# ---- window rule ----

def _wspec(author_pat="jane@.*", start="2026-01-01", end="2026-03-15") -> WindowSpec:
    return WindowSpec(
        author=re.compile(author_pat),
        start=start, end=end, tool="claude_code", confidence="high",
    )


def test_match_window_in_range():
    assert match_window(_wspec(), _commit(date="2026-02-10T00:00:00+00:00")) is True


def test_match_window_before_start():
    assert match_window(_wspec(), _commit(date="2025-12-31T23:59:59+00:00")) is False


def test_match_window_after_end():
    assert match_window(_wspec(), _commit(date="2026-03-16T00:00:00+00:00")) is False


def test_match_window_boundary_inclusive():
    assert match_window(_wspec(), _commit(date="2026-01-01T00:00:00+00:00")) is True
    assert match_window(_wspec(), _commit(date="2026-03-15T23:59:59+00:00")) is True


def test_match_window_author_mismatch():
    assert match_window(
        _wspec(author_pat="bob@.*"),
        _commit(date="2026-02-10T00:00:00+00:00"),
    ) is False


def test_match_window_malformed_date_returns_false():
    assert match_window(_wspec(), _commit(date="not-a-date")) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/detection/test_rules.py -v`
Expected: FAIL — `codeassay.detection.rules` does not exist.

- [ ] **Step 3: Implement rule matching**

Create `src/codeassay/detection/rules.py`:

```python
"""Rule matching primitives for the detection pipeline."""

from __future__ import annotations

from datetime import date, datetime
from typing import Iterable

from codeassay.detection.config import RuleSpec, WindowSpec


def match_author(rule: RuleSpec, commit: dict) -> bool:
    """Match against author email, then author name."""
    email = commit.get("author_email", "") or ""
    name = commit.get("author", "") or ""
    return bool(rule.pattern.search(email) or rule.pattern.search(name))


def match_branch(rule: RuleSpec, commit: dict, *, branches: Iterable[str]) -> bool:
    """Match if any branch that contains this commit matches the rule pattern."""
    for b in branches:
        if rule.pattern.search(b):
            return True
    return False


def match_message(rule: RuleSpec, commit: dict) -> bool:
    msg = commit.get("message", "") or ""
    return bool(rule.pattern.search(msg))


def _parse_commit_date(raw: str) -> date | None:
    try:
        return datetime.fromisoformat(raw).date()
    except (ValueError, TypeError):
        return None


def match_window(rule: WindowSpec, commit: dict) -> bool:
    email = commit.get("author_email", "") or ""
    name = commit.get("author", "") or ""
    if not (rule.author.search(email) or rule.author.search(name)):
        return False
    d = _parse_commit_date(commit.get("date", "") or "")
    if d is None:
        return False
    try:
        start = date.fromisoformat(rule.start)
        end = date.fromisoformat(rule.end)
    except ValueError:
        return False
    return start <= d <= end
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/detection/test_rules.py -v`
Expected: PASS — all 16 tests.

- [ ] **Step 5: Commit**

```bash
git add src/codeassay/detection/rules.py tests/detection/test_rules.py
git commit -m "feat(detection): add author/branch/message/window rule matchers"
```

---

## Task 6: Profile loader — discover built-in profiles

Built-in profiles live in `src/codeassay/profiles/*.toml`. Each profile reuses the same schema as `detect.*` user rules. The loader returns a list of `Profile` objects ordered alphabetically by filename.

**Files:**
- Create: `src/codeassay/detection/profiles.py`
- Create: `src/codeassay/profiles/__init__.py` (empty placeholder — profiles live alongside)
- Create: `tests/detection/test_profiles_loader.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/detection/test_profiles_loader.py`:

```python
from pathlib import Path
import pytest

from codeassay.detection.profiles import Profile, load_profiles


def _write_profile(dir_path: Path, name: str, body: str) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / f"{name}.toml").write_text(body)


def test_load_profiles_empty_directory(tmp_path):
    assert load_profiles(profiles_dir=tmp_path) == []


def test_load_profile_basic(tmp_path):
    _write_profile(tmp_path, "claude_code", """
[[detect.message]]
pattern = "Co-Authored-By:.*Claude"
tool = "claude_code"
confidence = "high"
""")
    profiles = load_profiles(profiles_dir=tmp_path)
    assert len(profiles) == 1
    p = profiles[0]
    assert isinstance(p, Profile)
    assert p.name == "claude_code"
    assert len(p.message_rules) == 1
    assert p.message_rules[0].tool == "claude_code"


def test_load_profiles_ordered_alphabetically(tmp_path):
    _write_profile(tmp_path, "zeta", "[[detect.message]]\npattern='z'\ntool='z'\n")
    _write_profile(tmp_path, "alpha", "[[detect.message]]\npattern='a'\ntool='a'\n")
    _write_profile(tmp_path, "mu", "[[detect.message]]\npattern='m'\ntool='m'\n")
    names = [p.name for p in load_profiles(profiles_dir=tmp_path)]
    assert names == ["alpha", "mu", "zeta"]


def test_load_profiles_skips_disabled(tmp_path):
    _write_profile(tmp_path, "cursor", "[[detect.author]]\npattern='c'\ntool='cursor'\n")
    _write_profile(tmp_path, "aider", "[[detect.author]]\npattern='a'\ntool='aider'\n")
    profiles = load_profiles(profiles_dir=tmp_path, disabled={"cursor"})
    names = [p.name for p in profiles]
    assert names == ["aider"]


def test_load_profile_all_rule_categories(tmp_path):
    _write_profile(tmp_path, "all", """
[[detect.author]]
pattern = "a"
tool = "x"
[[detect.branch]]
pattern = "b"
tool = "x"
[[detect.message]]
pattern = "m"
tool = "x"
[[detect.window]]
author = "w@y.com"
start = "2026-01-01"
end = "2026-12-31"
tool = "x"
""")
    p = load_profiles(profiles_dir=tmp_path)[0]
    assert len(p.author_rules) == 1
    assert len(p.branch_rules) == 1
    assert len(p.message_rules) == 1
    assert len(p.window_rules) == 1


def test_load_profiles_uses_bundled_default_dir():
    """Default dir is src/codeassay/profiles/; this test just verifies the call
    signature works without raising — content-level assertions come later."""
    profiles = load_profiles()
    assert isinstance(profiles, list)


def test_load_profile_invalid_regex_raises(tmp_path):
    _write_profile(tmp_path, "bad", "[[detect.message]]\npattern='[unclosed'\ntool='x'\n")
    with pytest.raises(ValueError) as exc:
        load_profiles(profiles_dir=tmp_path)
    assert "bad" in str(exc.value)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/detection/test_profiles_loader.py -v`
Expected: FAIL — `codeassay.detection.profiles` does not exist.

- [ ] **Step 3: Create the profiles package placeholder**

Create an empty file at `src/codeassay/profiles/__init__.py`:

```python
"""Built-in AI tool detection profiles (TOML files in this directory)."""
```

- [ ] **Step 4: Implement the profile loader**

Create `src/codeassay/detection/profiles.py`:

```python
"""Discover and load built-in detection profiles from src/codeassay/profiles/."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

from codeassay.detection.config import (
    RuleSpec, WindowSpec, _parse_rule_list, _parse_window_list,
)


@dataclass
class Profile:
    name: str
    author_rules: list[RuleSpec] = field(default_factory=list)
    branch_rules: list[RuleSpec] = field(default_factory=list)
    message_rules: list[RuleSpec] = field(default_factory=list)
    window_rules: list[WindowSpec] = field(default_factory=list)


def _default_profiles_dir() -> Path:
    """Locate the bundled profiles/ directory inside the installed package."""
    pkg_root = resources.files("codeassay")
    return Path(str(pkg_root)) / "profiles"


def _load_single(path: Path) -> Profile:
    with path.open("rb") as f:
        raw = tomllib.load(f)
    detect = raw.get("detect", {})
    name = path.stem
    # Re-use config.py's private parsers; bad regex surfaces with "detect.author[0]" etc.
    # Prefix the location hint with the profile name for debuggability.
    try:
        return Profile(
            name=name,
            author_rules=_parse_rule_list(detect.get("author", []), f"{name}:author"),
            branch_rules=_parse_rule_list(detect.get("branch", []), f"{name}:branch"),
            message_rules=_parse_rule_list(detect.get("message", []), f"{name}:message"),
            window_rules=_parse_window_list(detect.get("window", [])),
        )
    except ValueError as e:
        raise ValueError(f"profile {name!r}: {e}") from e


def load_profiles(
    *,
    profiles_dir: Path | None = None,
    disabled: set[str] | None = None,
) -> list[Profile]:
    """Return all enabled profiles, ordered alphabetically by filename."""
    disabled = disabled or set()
    root = Path(profiles_dir) if profiles_dir else _default_profiles_dir()
    if not root.exists():
        return []
    profiles = []
    for toml_file in sorted(root.glob("*.toml")):
        name = toml_file.stem
        if name in disabled:
            continue
        profiles.append(_load_single(toml_file))
    return profiles
```

Note: the test `test_load_profile_invalid_regex_raises` expects "bad" in the error message; `_parse_rule_list` raises with `detect.<cat>[<idx>]` location — so we wrap in `_load_single` to prepend the profile name. The assertion checks for `"bad"` in the string because the filename stem is `"bad"`, which we include.

Wait — re-check: our `_load_single` catches `ValueError` and re-raises with `f"profile {name!r}: {e}"`, so the string contains `'bad'`. Good.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/detection/test_profiles_loader.py -v`
Expected: PASS — all 6 tests.

- [ ] **Step 6: Commit**

```bash
git add src/codeassay/detection/profiles.py src/codeassay/profiles/__init__.py tests/detection/test_profiles_loader.py
git commit -m "feat(detection): add profile loader with alphabetic ordering"
```

---

## Task 7: Seed built-in profile TOML files

Ship initial profiles for the seven supported tools. Patterns for `cursor`, `windsurf`, `aider` are marked as placeholder — they need field-verification before v1.

**Files:**
- Create: `src/codeassay/profiles/claude_code.toml`
- Create: `src/codeassay/profiles/copilot.toml`
- Create: `src/codeassay/profiles/cursor.toml`
- Create: `src/codeassay/profiles/aider.toml`
- Create: `src/codeassay/profiles/windsurf.toml`
- Create: `src/codeassay/profiles/gpt.toml`
- Create: `src/codeassay/profiles/gemini.toml`
- Create: `tests/detection/test_builtin_profiles.py`

- [ ] **Step 1: Write the failing fixture test**

Create `tests/detection/test_builtin_profiles.py`:

```python
from codeassay.detection.profiles import load_profiles


def test_all_expected_profiles_load():
    names = {p.name for p in load_profiles()}
    expected = {"claude_code", "copilot", "cursor", "aider", "windsurf", "gpt", "gemini"}
    assert expected <= names


def test_claude_code_matches_co_author_trailer():
    profiles = {p.name: p for p in load_profiles()}
    p = profiles["claude_code"]
    from codeassay.detection.rules import match_message
    commit = {"message": "feat: x\n\nCo-Authored-By: Claude <c@anthropic.com>"}
    assert any(match_message(r, commit) for r in p.message_rules)


def test_copilot_matches_trailer():
    profiles = {p.name: p for p in load_profiles()}
    p = profiles["copilot"]
    from codeassay.detection.rules import match_message
    commit = {"message": "feat: x\n\nCo-Authored-By: GitHub Copilot <copilot@github.com>"}
    assert any(match_message(r, commit) for r in p.message_rules)


def test_gpt_and_gemini_trailers():
    from codeassay.detection.rules import match_message
    profiles = {p.name: p for p in load_profiles()}
    assert any(match_message(r, {"message": "x\n\nCo-Authored-By: ChatGPT <x@openai.com>"})
               for r in profiles["gpt"].message_rules)
    assert any(match_message(r, {"message": "x\n\nCo-Authored-By: Gemini <g@google.com>"})
               for r in profiles["gemini"].message_rules)


def test_cursor_matches_author_email():
    from codeassay.detection.rules import match_author
    profiles = {p.name: p for p in load_profiles()}
    p = profiles["cursor"]
    commit = {"author": "Cursor Agent", "author_email": "cursor-agent@cursor.com"}
    assert any(match_author(r, commit) for r in p.author_rules)


def test_aider_matches_message_prefix():
    from codeassay.detection.rules import match_message
    profiles = {p.name: p for p in load_profiles()}
    p = profiles["aider"]
    assert any(match_message(r, {"message": "aider: refactor foo"}) for r in p.message_rules)


def test_human_commit_matches_no_profile():
    from codeassay.detection.rules import match_message, match_author
    commit = {
        "message": "feat: ordinary human commit",
        "author": "Jane Dev",
        "author_email": "jane@example.com",
    }
    for p in load_profiles():
        assert not any(match_message(r, commit) for r in p.message_rules)
        assert not any(match_author(r, commit) for r in p.author_rules)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/detection/test_builtin_profiles.py -v`
Expected: FAIL — profiles don't exist yet.

- [ ] **Step 3: Create `claude_code.toml`**

Create `src/codeassay/profiles/claude_code.toml`:

```toml
# Claude Code — https://claude.com/claude-code
# Detects via the official Co-Authored-By trailer and Superpowers branch conventions.

[[detect.message]]
pattern = 'Co-Authored-By:.*Claude'
tool = "claude_code"
confidence = "high"

[[detect.message]]
pattern = '🤖 Generated with \[Claude Code\]'
tool = "claude_code"
confidence = "high"

[[detect.branch]]
pattern = '^claude-'
tool = "claude_code"
confidence = "medium"

[[detect.branch]]
pattern = '^superpowers-'
tool = "claude_code"
confidence = "medium"
```

- [ ] **Step 4: Create `copilot.toml`**

Create `src/codeassay/profiles/copilot.toml`:

```toml
# GitHub Copilot — https://github.com/features/copilot

[[detect.message]]
pattern = 'Co-Authored-By:.*Copilot'
tool = "copilot"
confidence = "high"

[[detect.author]]
pattern = 'copilot@github\.com'
tool = "copilot"
confidence = "high"
```

- [ ] **Step 5: Create `cursor.toml`**

Create `src/codeassay/profiles/cursor.toml`:

```toml
# Cursor — https://cursor.com
# Placeholder patterns — verify against real cursor-authored commits before v1 release.

[[detect.author]]
pattern = 'cursor-agent@'
tool = "cursor"
confidence = "high"

[[detect.author]]
pattern = '@cursor\.com'
tool = "cursor"
confidence = "high"

[[detect.branch]]
pattern = '^cursor/'
tool = "cursor"
confidence = "medium"

[[detect.message]]
pattern = 'Generated by Cursor'
tool = "cursor"
confidence = "high"
```

- [ ] **Step 6: Create `aider.toml`**

Create `src/codeassay/profiles/aider.toml`:

```toml
# Aider — https://aider.chat
# Placeholder patterns — verify against real aider-authored commits before v1 release.

[[detect.message]]
pattern = '^aider: '
tool = "aider"
confidence = "high"

[[detect.message]]
pattern = '# Aider'
tool = "aider"
confidence = "high"
```

- [ ] **Step 7: Create `windsurf.toml`**

Create `src/codeassay/profiles/windsurf.toml`:

```toml
# Windsurf / Codeium — https://codeium.com/windsurf
# Placeholder patterns — verify against real windsurf-authored commits before v1 release.

[[detect.author]]
pattern = '@codeium\.com'
tool = "windsurf"
confidence = "medium"

[[detect.author]]
pattern = '^windsurf-'
tool = "windsurf"
confidence = "medium"

[[detect.message]]
pattern = 'Windsurf AI'
tool = "windsurf"
confidence = "high"
```

- [ ] **Step 8: Create `gpt.toml`**

Create `src/codeassay/profiles/gpt.toml`:

```toml
# ChatGPT / OpenAI Codex CLI

[[detect.message]]
pattern = 'Co-Authored-By:.*GPT'
tool = "gpt"
confidence = "high"

[[detect.message]]
pattern = 'Co-Authored-By:.*ChatGPT'
tool = "gpt"
confidence = "high"
```

- [ ] **Step 9: Create `gemini.toml`**

Create `src/codeassay/profiles/gemini.toml`:

```toml
# Gemini CLI / Gemini Code

[[detect.message]]
pattern = 'Co-Authored-By:.*Gemini'
tool = "gemini"
confidence = "high"
```

- [ ] **Step 10: Ensure setuptools bundles the profiles**

Append to `pyproject.toml` after the `[tool.setuptools.packages.find]` block:

```toml
[tool.setuptools.package-data]
"codeassay.profiles" = ["*.toml"]
```

- [ ] **Step 11: Run tests to verify they pass**

Run: `pytest tests/detection/test_builtin_profiles.py -v`
Expected: PASS — all 7 tests.

- [ ] **Step 12: Commit**

```bash
git add src/codeassay/profiles/*.toml pyproject.toml tests/detection/test_builtin_profiles.py
git commit -m "feat(detection): seed built-in profiles for claude/copilot/cursor/aider/windsurf/gpt/gemini"
```

---

## Task 8: Scorer — individual signal functions

Implement each probabilistic signal as a pure function returning a float in `[0.0, 1.0]`. Keep them testable in isolation; aggregation comes in Task 9.

**Files:**
- Create: `src/codeassay/detection/scorer.py`
- Create: `tests/detection/test_scorer_signals.py`

- [ ] **Step 1: Write the failing signal tests**

Create `tests/detection/test_scorer_signals.py`:

```python
from codeassay.detection.scorer import (
    signal_diff_wholesale_rewrite,
    signal_message_structured_body,
    signal_commit_velocity,
    signal_emoji_indicator,
    signal_message_boilerplate,
    signal_file_diversity,
    signal_perfect_punctuation,
)


# ---- diff_wholesale_rewrite ----

def test_diff_wholesale_rewrite_full_replacement():
    stats = [{"path": "a.py", "added": 50, "removed": 50, "file_size": 50}]
    assert signal_diff_wholesale_rewrite(stats) > 0.9


def test_diff_wholesale_rewrite_small_edit():
    stats = [{"path": "a.py", "added": 2, "removed": 1, "file_size": 100}]
    assert signal_diff_wholesale_rewrite(stats) < 0.1


def test_diff_wholesale_rewrite_no_files():
    assert signal_diff_wholesale_rewrite([]) == 0.0


def test_diff_wholesale_rewrite_clamped_to_one():
    stats = [{"path": "a.py", "added": 500, "removed": 0, "file_size": 10}]
    assert signal_diff_wholesale_rewrite(stats) == 1.0


# ---- message_structured_body ----

def test_structured_body_high():
    msg = (
        "feat: add foo\n\n"
        "This adds the foo feature.\n\n"
        "- does X\n"
        "- does Y\n"
        "- does Z\n\n"
        "Also refactors bar."
    )
    assert signal_message_structured_body(msg) > 0.6


def test_structured_body_flat_message():
    assert signal_message_structured_body("fix typo") < 0.2


# ---- commit_velocity ----

def test_velocity_very_fast():
    assert signal_commit_velocity(seconds_since_prior=30) > 0.8


def test_velocity_slow():
    assert signal_commit_velocity(seconds_since_prior=7200) == 0.0


def test_velocity_none_prior():
    assert signal_commit_velocity(seconds_since_prior=None) == 0.0


# ---- emoji_indicator ----

def test_emoji_hit():
    assert signal_emoji_indicator("feat: add thing 🤖") == 1.0


def test_emoji_multiple_hits():
    assert signal_emoji_indicator("✨ feat ♻️ refactor") == 1.0


def test_emoji_no_hit():
    assert signal_emoji_indicator("feat: add thing") == 0.0


# ---- message_boilerplate ----

def test_boilerplate_hit():
    msg = "feat: x\n\nSummary:\n- a\n\nTest plan:\n- b"
    assert signal_message_boilerplate(msg) > 0.5


def test_boilerplate_none():
    assert signal_message_boilerplate("feat: add thing") == 0.0


# ---- file_diversity ----

def test_file_diversity_high():
    stats = [
        {"path": "a.py"}, {"path": "b.md"}, {"path": "c.yaml"}, {"path": "d.ts"},
    ]
    assert signal_file_diversity(stats) > 0.7


def test_file_diversity_single_type():
    stats = [{"path": "a.py"}, {"path": "b.py"}, {"path": "c.py"}]
    assert signal_file_diversity(stats) < 0.3


def test_file_diversity_empty():
    assert signal_file_diversity([]) == 0.0


# ---- perfect_punctuation ----

def test_punctuation_clean():
    assert signal_perfect_punctuation("Add the foo feature to the handler.") > 0.7


def test_punctuation_scruffy():
    assert signal_perfect_punctuation("add  the foo feature,,to   the  handler") < 0.4


def test_punctuation_empty():
    assert signal_perfect_punctuation("") == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/detection/test_scorer_signals.py -v`
Expected: FAIL — `codeassay.detection.scorer` does not exist.

- [ ] **Step 3: Implement the scorer module**

Create `src/codeassay/detection/scorer.py`:

```python
"""Probabilistic weak-signal scorer for commits lacking deterministic markers."""

from __future__ import annotations

import re

EMOJI_SET = {"🤖", "✨", "🚀", "♻️"}
BOILERPLATE_HEADERS = ("Summary:", "Changes:", "Test plan:", "## Summary", "## Test plan")


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def signal_diff_wholesale_rewrite(stats: list[dict]) -> float:
    """(added + removed) / max(file_size, 1), averaged across touched files."""
    if not stats:
        return 0.0
    ratios = []
    for s in stats:
        size = max(int(s.get("file_size", 0)), 1)
        churn = int(s.get("added", 0)) + int(s.get("removed", 0))
        ratios.append(min(churn / size, 1.0))
    return _clamp(sum(ratios) / len(ratios))


def signal_message_structured_body(message: str) -> float:
    """Body has multi-paragraph + bullet lists. 0.0 if only a one-line title."""
    if not message:
        return 0.0
    lines = message.splitlines()
    if len(lines) < 2:
        return 0.0
    body = "\n".join(lines[1:]).strip()
    if not body:
        return 0.0
    paragraphs = [p for p in body.split("\n\n") if p.strip()]
    bullet_lines = sum(1 for line in body.splitlines() if line.strip().startswith(("- ", "* ")))
    score = 0.0
    if len(paragraphs) >= 2:
        score += 0.4
    if bullet_lines >= 2:
        score += 0.4
    if len(body) > 120:
        score += 0.2
    return _clamp(score)


def signal_commit_velocity(seconds_since_prior: int | None) -> float:
    """<60s → 1.0, >1h → 0.0, linear in between."""
    if seconds_since_prior is None:
        return 0.0
    if seconds_since_prior <= 60:
        return 1.0
    if seconds_since_prior >= 3600:
        return 0.0
    return _clamp(1.0 - (seconds_since_prior - 60) / (3600 - 60))


def signal_emoji_indicator(message: str) -> float:
    return 1.0 if any(e in message for e in EMOJI_SET) else 0.0


def signal_message_boilerplate(message: str) -> float:
    hits = sum(1 for h in BOILERPLATE_HEADERS if h in message)
    if hits == 0:
        return 0.0
    return _clamp(min(hits / 2, 1.0))


def signal_file_diversity(stats: list[dict]) -> float:
    if not stats:
        return 0.0
    exts = set()
    for s in stats:
        path = s.get("path", "")
        if "." in path:
            exts.add(path.rsplit(".", 1)[-1].lower())
        else:
            exts.add("")
    return _clamp(min(len(exts) / 4, 1.0))


_DOUBLE_SPACE = re.compile(r"  +")
_MULTI_COMMA = re.compile(r",{2,}")


def signal_perfect_punctuation(message: str) -> float:
    if not message:
        return 0.0
    title = message.splitlines()[0]
    score = 1.0
    if _DOUBLE_SPACE.search(message):
        score -= 0.4
    if _MULTI_COMMA.search(message):
        score -= 0.3
    if title and title[0].islower() and not title.startswith(("fix:", "feat:", "chore:", "docs:", "refactor:", "test:")):
        score -= 0.2
    if title and not title.rstrip().endswith((".", ":")) and len(title) > 40:
        score -= 0.1
    return _clamp(score)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/detection/test_scorer_signals.py -v`
Expected: PASS — all 20 tests.

- [ ] **Step 5: Commit**

```bash
git add src/codeassay/detection/scorer.py tests/detection/test_scorer_signals.py
git commit -m "feat(detection): implement 7 weak signals for probabilistic scorer"
```

---

## Task 9: Scorer aggregator — weighted sum + threshold

Combine signals into a single score. Exposes a `score_commit(commit, diff_stats, prior_commit, config) -> float` function.

**Files:**
- Modify: `src/codeassay/detection/scorer.py`
- Create: `tests/detection/test_scorer_aggregate.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/detection/test_scorer_aggregate.py`:

```python
from codeassay.detection.config import ScoreConfig
from codeassay.detection.scorer import score_commit


def _commit(**overrides):
    base = {
        "hash": "abc",
        "author": "Jane Dev",
        "author_email": "jane@example.com",
        "date": "2026-02-15T12:00:00+00:00",
        "message": "feat: add foo",
    }
    base.update(overrides)
    return base


def test_score_zero_for_plain_commit():
    s = score_commit(
        commit=_commit(message="fix typo"),
        diff_stats=[{"path": "a.py", "added": 1, "removed": 1, "file_size": 100}],
        seconds_since_prior=7200,
        config=ScoreConfig(),
    )
    assert s < 0.3


def test_score_high_for_ai_shaped_commit():
    msg = (
        "feat: add structured feature 🤖\n\n"
        "Summary:\n- does X\n- does Y\n\n"
        "Test plan:\n- run pytest\n"
    )
    diff = [
        {"path": "a.py", "added": 80, "removed": 60, "file_size": 80},
        {"path": "b.md", "added": 20, "removed": 0, "file_size": 20},
        {"path": "c.yaml", "added": 10, "removed": 0, "file_size": 10},
    ]
    s = score_commit(
        commit=_commit(message=msg),
        diff_stats=diff,
        seconds_since_prior=45,
        config=ScoreConfig(),
    )
    assert s > 0.7


def test_score_respects_custom_weights():
    # Only punctuation weighted; clean commit should still score ~1.
    weights = {k: 0.0 for k in ScoreConfig().weights}
    weights["perfect_punctuation"] = 1.0
    cfg = ScoreConfig(weights=weights)
    s = score_commit(
        commit=_commit(message="feat: clean well-formed title"),
        diff_stats=[],
        seconds_since_prior=None,
        config=cfg,
    )
    assert s > 0.7


def test_score_returns_zero_when_all_signals_zero():
    msg = "x"
    weights = {k: 0.0 for k in ScoreConfig().weights}
    weights["emoji_indicator"] = 1.0
    cfg = ScoreConfig(weights=weights)
    s = score_commit(
        commit=_commit(message=msg),
        diff_stats=[],
        seconds_since_prior=None,
        config=cfg,
    )
    assert s == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/detection/test_scorer_aggregate.py -v`
Expected: FAIL — `score_commit` does not exist yet.

- [ ] **Step 3: Add `score_commit` to `scorer.py`**

Append to `src/codeassay/detection/scorer.py`:

```python
def score_commit(
    *,
    commit: dict,
    diff_stats: list[dict],
    seconds_since_prior: int | None,
    config,  # ScoreConfig (avoid circular import with TYPE_CHECKING if desired)
) -> float:
    """Return a 0-1 score combining all signals weighted per config."""
    msg = commit.get("message", "") or ""
    signals = {
        "diff_wholesale_rewrite": signal_diff_wholesale_rewrite(diff_stats),
        "message_structured_body": signal_message_structured_body(msg),
        "commit_velocity": signal_commit_velocity(seconds_since_prior),
        "emoji_indicator": signal_emoji_indicator(msg),
        "message_boilerplate": signal_message_boilerplate(msg),
        "file_diversity": signal_file_diversity(diff_stats),
        "perfect_punctuation": signal_perfect_punctuation(msg),
    }
    total = 0.0
    for name, value in signals.items():
        weight = config.weights.get(name, 0.0)
        total += value * weight
    return _clamp(total)


def per_signal_contributions(
    *,
    commit: dict,
    diff_stats: list[dict],
    seconds_since_prior: int | None,
    config,
) -> dict:
    """Return a dict of signal -> (raw_value, weighted_contribution) for auditing."""
    msg = commit.get("message", "") or ""
    raw = {
        "diff_wholesale_rewrite": signal_diff_wholesale_rewrite(diff_stats),
        "message_structured_body": signal_message_structured_body(msg),
        "commit_velocity": signal_commit_velocity(seconds_since_prior),
        "emoji_indicator": signal_emoji_indicator(msg),
        "message_boilerplate": signal_message_boilerplate(msg),
        "file_diversity": signal_file_diversity(diff_stats),
        "perfect_punctuation": signal_perfect_punctuation(msg),
    }
    return {
        name: {"raw": value, "weighted": value * config.weights.get(name, 0.0)}
        for name, value in raw.items()
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/detection/test_scorer_aggregate.py -v`
Expected: PASS — all 4 tests.

- [ ] **Step 5: Commit**

```bash
git add src/codeassay/detection/scorer.py tests/detection/test_scorer_aggregate.py
git commit -m "feat(detection): add score_commit aggregator and per-signal audit"
```

---

## Task 10: Classify orchestrator (`detection.classify`)

The public entry point. Runs user rules → profiles → scorer in the order defined by the spec, returns a `Detection` or `None`.

**Files:**
- Modify: `src/codeassay/detection/__init__.py`
- Create: `tests/detection/test_classify.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/detection/test_classify.py`:

```python
import re
from codeassay.detection import Detection, classify
from codeassay.detection.config import (
    DetectionConfig, RuleSpec, ScoreConfig, WindowSpec,
)
from codeassay.detection.profiles import Profile


def _commit(**overrides):
    base = {
        "hash": "abc",
        "author": "Jane Dev",
        "author_email": "jane@example.com",
        "date": "2026-02-15T12:00:00+00:00",
        "message": "feat: plain commit",
        "branches": set(),
    }
    base.update(overrides)
    return base


def _rule(pat, tool="x", conf="high"):
    return RuleSpec(pattern=re.compile(pat), tool=tool, confidence=conf)


def test_classify_user_author_rule_wins():
    cfg = DetectionConfig(author_rules=[_rule("jane@", tool="cursor", conf="high")])
    d = classify(_commit(), config=cfg, profiles=[])
    assert d == Detection(tool="cursor", confidence="high", method="rule",
                          source="user:detect.author[0]")


def test_classify_user_rules_before_profiles():
    cfg = DetectionConfig(message_rules=[_rule(r"^feat:", tool="user_tool", conf="medium")])
    profile = Profile(name="aider", message_rules=[_rule("feat", tool="aider", conf="high")])
    d = classify(_commit(message="feat: x"), config=cfg, profiles=[profile])
    assert d.tool == "user_tool"
    assert d.source == "user:detect.message[0]"


def test_classify_profile_when_no_user_rule():
    profile = Profile(name="aider", message_rules=[_rule("^aider:", tool="aider", conf="high")])
    cfg = DetectionConfig()
    d = classify(_commit(message="aider: refactor"), config=cfg, profiles=[profile])
    assert d == Detection(tool="aider", confidence="high", method="profile", source="profile:aider")


def test_classify_profile_alphabetic_order():
    p1 = Profile(name="aaa", message_rules=[_rule("x", tool="aaa")])
    p2 = Profile(name="bbb", message_rules=[_rule("x", tool="bbb")])
    cfg = DetectionConfig()
    # Both match; first (alphabetic) wins — caller is expected to pass them in order.
    d = classify(_commit(message="x"), config=cfg, profiles=[p1, p2])
    assert d.tool == "aaa"


def test_classify_no_match_returns_none_when_scorer_disabled():
    cfg = DetectionConfig()
    d = classify(_commit(), config=cfg, profiles=[])
    assert d is None


def test_classify_scorer_triggers_when_enabled_and_above_threshold():
    cfg = DetectionConfig(score=ScoreConfig(enabled=True, threshold=0.1))
    emoji_commit = _commit(message="feat: add thing 🤖")
    d = classify(
        emoji_commit, config=cfg, profiles=[],
        diff_stats=[], seconds_since_prior=None,
    )
    assert d is not None
    assert d.method == "score"
    assert d.tool == "unknown"
    assert d.confidence == "low"
    assert d.source.startswith("score:")


def test_classify_scorer_below_threshold_returns_none():
    cfg = DetectionConfig(score=ScoreConfig(enabled=True, threshold=0.99))
    d = classify(
        _commit(message="fix typo"), config=cfg, profiles=[],
        diff_stats=[], seconds_since_prior=None,
    )
    assert d is None


def test_classify_category_order_author_before_branch():
    cfg = DetectionConfig(
        author_rules=[_rule("jane@", tool="from_author")],
        branch_rules=[_rule("^main$", tool="from_branch")],
    )
    d = classify(_commit(branches={"main"}), config=cfg, profiles=[])
    assert d.tool == "from_author"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/detection/test_classify.py -v`
Expected: FAIL — `classify` does not exist.

- [ ] **Step 3: Implement `classify`**

Replace `src/codeassay/detection/__init__.py` with:

```python
"""Configurable AI commit detection pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from codeassay.detection.rules import (
    match_author, match_branch, match_message, match_window,
)
from codeassay.detection.scorer import score_commit

if TYPE_CHECKING:
    from codeassay.detection.config import DetectionConfig
    from codeassay.detection.profiles import Profile


@dataclass(frozen=True)
class Detection:
    tool: str
    confidence: str
    method: str  # "rule" | "profile" | "score"
    source: str


def _scan_rule_list(rules, *, category, kind, commit, branches=None) -> Detection | None:
    for i, rule in enumerate(rules):
        if kind == "author" and match_author(rule, commit):
            hit = True
        elif kind == "branch" and match_branch(rule, commit, branches=branches or set()):
            hit = True
        elif kind == "message" and match_message(rule, commit):
            hit = True
        elif kind == "window" and match_window(rule, commit):
            hit = True
        else:
            hit = False
        if hit:
            return Detection(
                tool=rule.tool,
                confidence=rule.confidence,
                method="__placeholder__",  # filled in by caller
                source=f"__placeholder__:detect.{category}[{i}]",
            )
    return None


def _check_rule_bundle(
    *, commit, branches, author_rules, branch_rules, message_rules, window_rules,
) -> tuple[str, int, object] | None:
    """Return (category, index, rule) for the first matching rule in the bundle, else None."""
    categories = [
        ("author", author_rules, "author"),
        ("branch", branch_rules, "branch"),
        ("message", message_rules, "message"),
        ("window", window_rules, "window"),
    ]
    for cat_label, rules, kind in categories:
        for i, rule in enumerate(rules):
            if kind == "author" and match_author(rule, commit):
                return (cat_label, i, rule)
            if kind == "branch" and match_branch(rule, commit, branches=branches):
                return (cat_label, i, rule)
            if kind == "message" and match_message(rule, commit):
                return (cat_label, i, rule)
            if kind == "window" and match_window(rule, commit):
                return (cat_label, i, rule)
    return None


def classify(
    commit: dict,
    *,
    config,
    profiles: list,
    diff_stats: list | None = None,
    seconds_since_prior: int | None = None,
) -> Detection | None:
    """Run detection pipeline. Returns Detection if AI, None if human."""
    branches = set(commit.get("branches", set()) or set())

    # 1. User rules
    hit = _check_rule_bundle(
        commit=commit, branches=branches,
        author_rules=config.author_rules,
        branch_rules=config.branch_rules,
        message_rules=config.message_rules,
        window_rules=config.window_rules,
    )
    if hit:
        cat, idx, rule = hit
        return Detection(
            tool=rule.tool,
            confidence=rule.confidence,
            method="rule",
            source=f"user:detect.{cat}[{idx}]",
        )

    # 2. Profiles (passed in alphabetic order by caller)
    for profile in profiles:
        hit = _check_rule_bundle(
            commit=commit, branches=branches,
            author_rules=profile.author_rules,
            branch_rules=profile.branch_rules,
            message_rules=profile.message_rules,
            window_rules=profile.window_rules,
        )
        if hit:
            _cat, _idx, rule = hit
            return Detection(
                tool=rule.tool,
                confidence=rule.confidence,
                method="profile",
                source=f"profile:{profile.name}",
            )

    # 3. Scorer
    if config.score.enabled:
        s = score_commit(
            commit=commit,
            diff_stats=diff_stats or [],
            seconds_since_prior=seconds_since_prior,
            config=config.score,
        )
        if s >= config.score.threshold:
            return Detection(
                tool="unknown",
                confidence="low",
                method="score",
                source=f"score:{s:.2f}",
            )

    return None


__all__ = ["Detection", "classify"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/detection/ -v`
Expected: PASS — all detection tests, including the new classify tests.

- [ ] **Step 5: Commit**

```bash
git add src/codeassay/detection/__init__.py tests/detection/test_classify.py
git commit -m "feat(detection): add classify() orchestrator for layered detection"
```

---

## Task 11: Refactor `scanner.py` to use `detection.classify`

Replace the hard-coded `detect_ai_tool` pipeline. Keep the public function signature (`scan_repo`) and the back-compat shim (`detect_ai_tool`, `get_detection_confidence`) so existing tests continue to pass until we update them.

**Files:**
- Modify: `src/codeassay/scanner.py` (most of the file)
- Modify: `tests/test_scanner.py` (update assertions for new `source` field)

- [ ] **Step 1: Read the existing scanner carefully**

Run: `cat src/codeassay/scanner.py | head -120`
(Make sure you understand `parse_commit_log`, `_get_changed_files`, `scan_repo`'s incremental behavior.)

- [ ] **Step 2: Write a new integration-style test**

Append to `tests/test_scanner.py`:

```python
def test_scan_repo_records_source(tmp_repo, db_conn):
    _make_commit(
        tmp_repo, "foo.py", "print('hi')\n",
        "feat: foo",
        co_author="Claude <x@anthropic.com>",
    )
    scan_repo(tmp_repo, db_conn)
    from codeassay.db import get_ai_commits
    rows = get_ai_commits(db_conn, repo_path=str(tmp_repo))
    assert len(rows) == 1
    assert rows[0]["source"] == "profile:claude_code"
    assert rows[0]["tool"] == "claude_code"


def test_scan_repo_respects_user_config_override(tmp_repo, db_conn):
    (tmp_repo / ".codeassay.toml").write_text(
        '[[detect.message]]\n'
        'pattern = "Co-Authored-By:.*Claude"\n'
        'tool = "custom_brand"\n'
        'confidence = "high"\n'
    )
    _make_commit(
        tmp_repo, "foo.py", "x\n",
        "feat: foo",
        co_author="Claude <x@anthropic.com>",
    )
    scan_repo(tmp_repo, db_conn)
    from codeassay.db import get_ai_commits
    rows = get_ai_commits(db_conn, repo_path=str(tmp_repo))
    assert rows[0]["tool"] == "custom_brand"
    assert rows[0]["source"] == "user:detect.message[0]"
```

- [ ] **Step 3: Run to confirm failure**

Run: `pytest tests/test_scanner.py -v -k "source or override"`
Expected: FAIL — old scanner doesn't populate source.

- [ ] **Step 4: Refactor scanner.py**

Replace `src/codeassay/scanner.py` entirely:

```python
"""Git history scanning. AI commit detection is delegated to codeassay.detection."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from codeassay.db import (
    get_last_scanned_commit,
    insert_ai_commit,
    set_last_scanned_commit,
)
from codeassay.detection import classify
from codeassay.detection.config import load_config
from codeassay.detection.profiles import load_profiles
from codeassay.ignore import filter_files_csv, load_ignore_patterns

DELIMITER = "---AIQUALITY---"
LOG_FORMAT = f"%H{DELIMITER}%an{DELIMITER}%ae{DELIMITER}%aI{DELIMITER}%B{DELIMITER}"


# ---- Back-compat shims (kept so old tests still pass) ----

_LEGACY_TOOL_PATTERNS = [
    (re.compile(r"Co-Authored-By:.*Claude", re.IGNORECASE), "claude_code"),
    (re.compile(r"Co-Authored-By:.*Copilot", re.IGNORECASE), "copilot"),
    (re.compile(r"Co-Authored-By:.*GPT", re.IGNORECASE), "gpt"),
    (re.compile(r"Co-Authored-By:.*Gemini", re.IGNORECASE), "gemini"),
]
_MANUAL_TAG_PATTERN = re.compile(r"AI-Assisted:\s*true", re.IGNORECASE)
_LEGACY_CONFIDENCE = {
    "co_author_trailer": "high",
    "branch_pattern": "medium",
    "manual_tag": "high",
}


def detect_ai_tool(message: str) -> str | None:
    """Back-compat shim; new code should use codeassay.detection.classify()."""
    for pattern, tool in _LEGACY_TOOL_PATTERNS:
        if pattern.search(message):
            return tool
    if _MANUAL_TAG_PATTERN.search(message):
        return "unknown"
    return None


def get_detection_confidence(method: str) -> str:
    return _LEGACY_CONFIDENCE.get(method, "low")


# ---- Log parsing ----

def parse_commit_log(repo_path: Path, since_commit: str | None = None) -> list[dict]:
    cmd = ["git", "log", f"--format={LOG_FORMAT}"]
    if since_commit:
        cmd.append(f"{since_commit}..HEAD")
    result = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True)
    if result.returncode != 0:
        return []
    raw = result.stdout.strip()
    if not raw:
        return []
    commits = []
    for entry in raw.split(f"{DELIMITER}\n"):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(DELIMITER)
        if len(parts) < 5:
            continue
        commit_hash, author, author_email, date, message = (p.strip() for p in parts[:5])
        if not commit_hash:
            continue
        commits.append({
            "hash": commit_hash,
            "author": author,
            "author_email": author_email,
            "date": date,
            "message": message,
        })
    return commits


def _get_changed_files(repo_path: Path, commit_hash: str) -> str:
    result = subprocess.run(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit_hash],
        cwd=repo_path, capture_output=True, text=True,
    )
    files = [f for f in result.stdout.strip().split("\n") if f]
    return ",".join(files)


def _branches_containing(repo_path: Path, commit_hash: str) -> set[str]:
    result = subprocess.run(
        ["git", "branch", "--contains", commit_hash, "--format=%(refname:short)"],
        cwd=repo_path, capture_output=True, text=True,
    )
    if result.returncode != 0:
        return set()
    return {b.strip() for b in result.stdout.splitlines() if b.strip()}


def _diff_stats(repo_path: Path, commit_hash: str) -> list[dict]:
    """Per-file numstat for a commit, plus file size after the commit."""
    numstat = subprocess.run(
        ["git", "show", "--numstat", "--format=", commit_hash],
        cwd=repo_path, capture_output=True, text=True,
    )
    stats = []
    if numstat.returncode != 0:
        return stats
    for line in numstat.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        added_s, removed_s, path = parts
        if added_s == "-" or removed_s == "-":
            continue  # binary file
        # File size = lines in the file at this commit
        cat = subprocess.run(
            ["git", "show", f"{commit_hash}:{path}"],
            cwd=repo_path, capture_output=True, text=True,
        )
        size = len(cat.stdout.splitlines()) if cat.returncode == 0 else 0
        stats.append({
            "path": path,
            "added": int(added_s),
            "removed": int(removed_s),
            "file_size": size,
        })
    return stats


def _seconds_between(commit_later: dict, commit_earlier: dict | None) -> int | None:
    if commit_earlier is None:
        return None
    from datetime import datetime
    try:
        a = datetime.fromisoformat(commit_later["date"])
        b = datetime.fromisoformat(commit_earlier["date"])
    except (ValueError, TypeError):
        return None
    return int((a - b).total_seconds())


# ---- Scan orchestration ----

def scan_repo(repo_path: Path, conn, branch: str | None = None) -> dict:
    repo_path = Path(repo_path).resolve()
    repo_str = str(repo_path)
    ignore_patterns = load_ignore_patterns(repo_path)
    config = load_config(repo_path)
    profiles = load_profiles(disabled=config.disabled_profiles)

    last_commit = get_last_scanned_commit(conn, repo_str)
    commits = parse_commit_log(repo_path, since_commit=last_commit)
    ai_count = 0

    needs_branches = bool(config.branch_rules) or any(p.branch_rules for p in profiles)
    scorer_on = config.score.enabled

    # parse_commit_log returns commits newest-first. For seconds_since_prior
    # we want chronological order.
    chronological = list(reversed(commits))
    prior = None
    for commit in chronological:
        commit["branches"] = (
            _branches_containing(repo_path, commit["hash"]) if needs_branches else set()
        )
        diff_stats = _diff_stats(repo_path, commit["hash"]) if scorer_on else []
        seconds_since_prior = _seconds_between(commit, prior) if scorer_on else None
        detection = classify(
            commit, config=config, profiles=profiles,
            diff_stats=diff_stats, seconds_since_prior=seconds_since_prior,
        )
        prior = commit
        if detection is None:
            continue

        files = _get_changed_files(repo_path, commit["hash"])
        files = filter_files_csv(files, ignore_patterns)
        if not files:
            continue

        insert_ai_commit(
            conn,
            commit_hash=commit["hash"],
            repo_path=repo_str,
            author=commit["author"],
            date=commit["date"],
            message=commit["message"],
            tool=detection.tool,
            detection_method=detection.method,
            confidence=detection.confidence,
            files_changed=files,
            source=detection.source,
        )
        ai_count += 1

    if commits:
        set_last_scanned_commit(conn, repo_str, commits[0]["hash"])
    return {"total_commits": len(commits), "ai_commits": ai_count}
```

- [ ] **Step 5: Run all tests to verify they pass**

Run: `pytest -v`
Expected: PASS — all existing tests pass, including the new `source` and `override` tests.

- [ ] **Step 6: Commit**

```bash
git add src/codeassay/scanner.py tests/test_scanner.py
git commit -m "refactor(scanner): delegate AI detection to detection.classify pipeline"
```

---

## Task 12: `codeassay tag` subcommand

Add a CLI command that appends an `AI-Assisted: <tool>` trailer to a commit message. Supports two modes: hook mode (reads/writes a message file path) and amend mode (amends `HEAD`).

**Files:**
- Create: `src/codeassay/tag.py`
- Modify: `src/codeassay/cli.py` (add subparser + handler)
- Create: `tests/test_tag.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tag.py`:

```python
import subprocess
from pathlib import Path
import pytest

from codeassay.tag import add_trailer_to_message_file, already_tagged


def test_add_trailer_plain_message(tmp_path):
    msg = tmp_path / "MSG"
    msg.write_text("feat: add thing\n")
    add_trailer_to_message_file(msg, tool="cursor")
    out = msg.read_text()
    assert "AI-Assisted: cursor" in out
    assert out.startswith("feat: add thing")


def test_add_trailer_strips_trailing_newline_before_appending(tmp_path):
    msg = tmp_path / "MSG"
    msg.write_text("feat: x\n\n")
    add_trailer_to_message_file(msg, tool="claude_code")
    assert msg.read_text().count("AI-Assisted:") == 1


def test_already_tagged_with_ai_assisted():
    assert already_tagged("feat: x\n\nAI-Assisted: cursor") is True


def test_already_tagged_with_co_author_claude():
    assert already_tagged("feat: x\n\nCo-Authored-By: Claude <x@a.com>") is True


def test_already_tagged_with_co_author_copilot():
    assert already_tagged("feat: x\n\nCo-Authored-By: GitHub Copilot <c@g.com>") is True


def test_already_tagged_none():
    assert already_tagged("feat: plain") is False


def test_add_trailer_idempotent(tmp_path):
    msg = tmp_path / "MSG"
    msg.write_text("feat: x\n\nAI-Assisted: cursor")
    add_trailer_to_message_file(msg, tool="cursor")
    assert msg.read_text().count("AI-Assisted:") == 1


def test_add_trailer_skips_when_co_author_present(tmp_path):
    msg = tmp_path / "MSG"
    msg.write_text("feat: x\n\nCo-Authored-By: Claude <x@a.com>")
    add_trailer_to_message_file(msg, tool="cursor")
    assert "AI-Assisted: cursor" not in msg.read_text()


def test_cli_tag_amend(tmp_repo):
    """End-to-end via CLI: tag amends the last commit."""
    subprocess.run(
        ["python", "-m", "codeassay", "tag", "--tool", "cursor"],
        cwd=tmp_repo, capture_output=True, text=True,
    )
    log = subprocess.run(
        ["git", "log", "-1", "--format=%B"],
        cwd=tmp_repo, capture_output=True, text=True,
    ).stdout
    assert "AI-Assisted: cursor" in log
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tag.py -v`
Expected: FAIL — `codeassay.tag` does not exist.

- [ ] **Step 3: Implement `tag.py`**

Create `src/codeassay/tag.py`:

```python
"""`codeassay tag` and related commit-time helpers."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_AI_TRAILER = re.compile(r"^AI-Assisted:", re.MULTILINE)
_CO_AUTHOR_AI = re.compile(
    r"Co-Authored-By:.*(Claude|Copilot|GPT|ChatGPT|Gemini|Cursor|Windsurf|Aider)",
    re.IGNORECASE,
)


def already_tagged(message: str) -> bool:
    """True if an AI-Assisted or Co-Authored-By AI-tool trailer is present."""
    return bool(_AI_TRAILER.search(message) or _CO_AUTHOR_AI.search(message))


def _append_trailer(message: str, tool: str) -> str:
    trimmed = message.rstrip("\n")
    if "\n\n" in trimmed or "\n" not in trimmed:
        # single-line or already-separated — ensure exactly one blank line before trailer
        return f"{trimmed}\n\nAI-Assisted: {tool}\n"
    return f"{trimmed}\n\nAI-Assisted: {tool}\n"


def add_trailer_to_message_file(path: Path, *, tool: str) -> None:
    """Hook mode: rewrite the message file at `path` to include the trailer.

    Idempotent: skips if any AI trailer is already present.
    """
    message = path.read_text()
    if already_tagged(message):
        return
    path.write_text(_append_trailer(message, tool))


def amend_head_with_trailer(*, tool: str, cwd: Path | None = None) -> None:
    """Standalone mode: amend HEAD commit to add the trailer."""
    log = subprocess.run(
        ["git", "log", "-1", "--format=%B"],
        cwd=cwd, capture_output=True, text=True,
    )
    if log.returncode != 0:
        raise RuntimeError(f"git log failed: {log.stderr}")
    message = log.stdout
    if already_tagged(message):
        return
    new_message = _append_trailer(message, tool)
    # Use --no-verify is NOT used — respect hooks. --no-edit keeps amend from opening editor.
    subprocess.run(
        ["git", "commit", "--amend", "-m", new_message.rstrip("\n")],
        cwd=cwd, check=True,
    )
```

- [ ] **Step 4: Add the CLI subparser and handler**

In `src/codeassay/cli.py`:

a. Add the import near the top:

```python
from codeassay.tag import add_trailer_to_message_file, amend_head_with_trailer
```

b. In `build_parser()`, after the existing `dash_p` subparser block (around line 91), add:

```python
    tag_p = sub.add_parser("tag", help="Add AI-Assisted trailer to a commit message")
    tag_p.add_argument("--tool", default="unknown", help="AI tool name (default: unknown)")
    tag_p.add_argument("message_file", nargs="?", help="Hook-mode: path to commit message file")
```

c. Add the handler function after `cmd_dashboard`:

```python
def cmd_tag(args) -> None:
    if args.message_file:
        add_trailer_to_message_file(Path(args.message_file), tool=args.tool)
    else:
        amend_head_with_trailer(tool=args.tool, cwd=Path.cwd())
```

d. Add to the `COMMANDS` dict:

```python
    "tag": cmd_tag,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_tag.py -v`
Expected: PASS — all 8 tests.

- [ ] **Step 6: Commit**

```bash
git add src/codeassay/tag.py src/codeassay/cli.py tests/test_tag.py
git commit -m "feat(cli): add codeassay tag command for AI-Assisted trailers"
```

---

## Task 13: `install-hook` / `uninstall-hook` subcommands

Install a `prepare-commit-msg` hook that invokes `codeassay tag`. Mark the hook with a shebang comment so uninstall can detect manual edits.

**Files:**
- Modify: `src/codeassay/tag.py` (add install/uninstall functions)
- Modify: `src/codeassay/cli.py`
- Modify: `tests/test_tag.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tag.py`:

```python
from codeassay.tag import install_hook, uninstall_hook, HOOK_MARKER


def _init_plain_repo(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True)
    return repo


def test_install_hook_writes_hook_with_marker(tmp_path):
    repo = _init_plain_repo(tmp_path)
    install_hook(repo, tool="cursor", mode="always")
    hook = repo / ".git" / "hooks" / "prepare-commit-msg"
    assert hook.exists()
    content = hook.read_text()
    assert HOOK_MARKER in content
    assert "cursor" in content
    # Should be executable.
    import os
    assert os.access(hook, os.X_OK)


def test_install_hook_fails_if_existing_unmanaged(tmp_path):
    repo = _init_plain_repo(tmp_path)
    hook = repo / ".git" / "hooks" / "prepare-commit-msg"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\n# handmade hook\n")
    with pytest.raises(RuntimeError, match="already exists"):
        install_hook(repo, tool="cursor", mode="always")


def test_install_hook_force_overwrites(tmp_path):
    repo = _init_plain_repo(tmp_path)
    hook = repo / ".git" / "hooks" / "prepare-commit-msg"
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\n# handmade\n")
    install_hook(repo, tool="cursor", mode="always", force=True)
    assert HOOK_MARKER in hook.read_text()


def test_uninstall_hook_removes_managed(tmp_path):
    repo = _init_plain_repo(tmp_path)
    install_hook(repo, tool="cursor", mode="always")
    uninstall_hook(repo)
    hook = repo / ".git" / "hooks" / "prepare-commit-msg"
    assert not hook.exists()


def test_uninstall_hook_refuses_modified(tmp_path):
    repo = _init_plain_repo(tmp_path)
    install_hook(repo, tool="cursor", mode="always")
    hook = repo / ".git" / "hooks" / "prepare-commit-msg"
    # Remove the marker to simulate hand editing
    hook.write_text("#!/bin/sh\necho hi\n")
    with pytest.raises(RuntimeError, match="modified"):
        uninstall_hook(repo)


def test_uninstall_hook_noop_when_absent(tmp_path):
    repo = _init_plain_repo(tmp_path)
    uninstall_hook(repo)  # should not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tag.py -v -k "hook"`
Expected: FAIL — `install_hook`/`uninstall_hook` don't exist.

- [ ] **Step 3: Add hook functions to `tag.py`**

Append to `src/codeassay/tag.py`:

```python
import os

HOOK_MARKER = "# managed-by-codeassay"

_HOOK_TEMPLATE_ALWAYS = """#!/bin/sh
{marker}
# prepare-commit-msg hook installed by codeassay.
# Mode: always. Adds AI-Assisted trailer unconditionally (idempotent).
# To uninstall: codeassay uninstall-hook
codeassay tag --tool {tool} "$1"
"""

_HOOK_TEMPLATE_PROMPT = """#!/bin/sh
{marker}
# prepare-commit-msg hook installed by codeassay.
# Mode: prompt. Asks whether to add AI-Assisted trailer.
# To uninstall: codeassay uninstall-hook
if [ -t 1 ]; then
    printf "Add AI-Assisted: {tool} trailer? [y/N] " >&2
    read answer < /dev/tty
    case "$answer" in
        y|Y|yes|YES) codeassay tag --tool {tool} "$1" ;;
    esac
fi
"""


def _hook_path(repo_path: Path) -> Path:
    return Path(repo_path) / ".git" / "hooks" / "prepare-commit-msg"


def install_hook(
    repo_path: Path, *, tool: str = "unknown", mode: str = "always", force: bool = False,
) -> None:
    hook = _hook_path(repo_path)
    if hook.exists() and not force:
        if HOOK_MARKER not in hook.read_text():
            raise RuntimeError(
                f"{hook} already exists and was not installed by codeassay. "
                "Use --force to overwrite."
            )
    template = _HOOK_TEMPLATE_ALWAYS if mode == "always" else _HOOK_TEMPLATE_PROMPT
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(template.format(marker=HOOK_MARKER, tool=tool))
    current_mode = os.stat(hook).st_mode
    os.chmod(hook, current_mode | 0o111)


def uninstall_hook(repo_path: Path) -> None:
    hook = _hook_path(repo_path)
    if not hook.exists():
        return
    if HOOK_MARKER not in hook.read_text():
        raise RuntimeError(
            f"{hook} was modified manually; refusing to delete. "
            "Remove it yourself if you're sure."
        )
    hook.unlink()
```

- [ ] **Step 4: Wire subcommands into the CLI**

In `src/codeassay/cli.py`:

a. Update the import:

```python
from codeassay.tag import (
    add_trailer_to_message_file, amend_head_with_trailer,
    install_hook, uninstall_hook,
)
```

b. Add to `build_parser()` after the `tag_p` block:

```python
    hook_p = sub.add_parser("install-hook", help="Install prepare-commit-msg hook")
    hook_p.add_argument("--tool", default="unknown")
    hook_p.add_argument("--mode", choices=["always", "prompt"], default="always")
    hook_p.add_argument("--force", action="store_true", help="Overwrite existing hook")

    uninst_p = sub.add_parser("uninstall-hook", help="Remove codeassay-managed hook")
```

c. Add the handlers after `cmd_tag`:

```python
def cmd_install_hook(args) -> None:
    install_hook(Path.cwd(), tool=args.tool, mode=args.mode, force=args.force)
    print(f"Installed prepare-commit-msg hook (tool={args.tool}, mode={args.mode})")


def cmd_uninstall_hook(args) -> None:
    uninstall_hook(Path.cwd())
    print("Uninstalled prepare-commit-msg hook (if present)")
```

d. Add to `COMMANDS`:

```python
    "install-hook": cmd_install_hook,
    "uninstall-hook": cmd_uninstall_hook,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_tag.py -v`
Expected: PASS — all hook tests.

- [ ] **Step 6: Commit**

```bash
git add src/codeassay/tag.py src/codeassay/cli.py tests/test_tag.py
git commit -m "feat(cli): add install-hook and uninstall-hook subcommands"
```

---

## Task 14: `config init` / `config show` subcommands

Scaffold a starter `.codeassay.toml`. Display merged effective config.

**Files:**
- Modify: `src/codeassay/cli.py`
- Create: `src/codeassay/detection/config_init.py` (holds the starter template)
- Create: `tests/test_cli_config.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_config.py`:

```python
import subprocess
from pathlib import Path
import pytest


def test_config_init_creates_file(tmp_path):
    result = subprocess.run(
        ["python", "-m", "codeassay", "config", "init"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0
    cfg = tmp_path / ".codeassay.toml"
    assert cfg.exists()
    content = cfg.read_text()
    assert "[profiles." in content
    assert "[score]" in content
    assert "enabled = false" in content


def test_config_init_fails_if_exists(tmp_path):
    (tmp_path / ".codeassay.toml").write_text("# existing\n")
    result = subprocess.run(
        ["python", "-m", "codeassay", "config", "init"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "exists" in result.stderr.lower()


def test_config_init_force_overwrites(tmp_path):
    (tmp_path / ".codeassay.toml").write_text("# old\n")
    result = subprocess.run(
        ["python", "-m", "codeassay", "config", "init", "--force"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "[profiles." in (tmp_path / ".codeassay.toml").read_text()


def test_config_show_lists_profiles(tmp_path):
    result = subprocess.run(
        ["python", "-m", "codeassay", "config", "show"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "claude_code" in result.stdout
    assert "cursor" in result.stdout
    assert "score" in result.stdout.lower()
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_cli_config.py -v`
Expected: FAIL — `config` subcommand doesn't exist.

- [ ] **Step 3: Create the starter template**

Create `src/codeassay/detection/config_init.py`:

```python
"""Starter .codeassay.toml content, emitted by `codeassay config init`."""

STARTER_TEMPLATE = '''\
# codeassay detection config
# Docs: https://github.com/jeffsinason/codeassay (replace when repo published)

# ---------- Built-in AI tool profiles ----------
# Enabled by default. Set enabled = false to disable any profile for this repo.

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

# ---------- User-defined rules (highest priority) ----------
# Examples — uncomment and edit to fit your team's conventions.

# [[detect.author]]
# pattern = "cursor-agent@.*"   # regex, matched against author email then name
# tool = "cursor"
# confidence = "high"

# [[detect.branch]]
# pattern = "^(ai|claude|copilot)/.*"
# tool = "claude_code"
# confidence = "medium"

# [[detect.message]]
# pattern = '^\\\\[AI\\\\]'     # team convention: AI commits prefixed with [AI]
# tool = "unknown"
# confidence = "high"

# [[detect.window]]
# author = "jeff@example.com"
# start = "2026-01-01"
# end = "2026-03-15"
# tool = "claude_code"
# confidence = "high"
# note = "AI-heavy sprint"

# ---------- Probabilistic scorer (opt-in, heuristic) ----------
# Runs only for commits no deterministic rule caught.
# Intended as a diagnostic; expect some false positives.

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
'''
```

- [ ] **Step 4: Add `config` subparser**

In `src/codeassay/cli.py`:

a. Add this in `build_parser()` after `uninst_p`:

```python
    config_p = sub.add_parser("config", help="Manage .codeassay.toml")
    config_sub = config_p.add_subparsers(dest="config_action")
    config_init_p = config_sub.add_parser("init", help="Write starter .codeassay.toml")
    config_init_p.add_argument("--force", action="store_true")
    config_show_p = config_sub.add_parser("show", help="Print merged effective config")
```

b. Add handlers:

```python
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
```

c. Add to `COMMANDS`:

```python
    "config": cmd_config,
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_cli_config.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/codeassay/cli.py src/codeassay/detection/config_init.py tests/test_cli_config.py
git commit -m "feat(cli): add config init and config show subcommands"
```

---

## Task 15: `detect-test` subcommand

Dry-run detection against a single commit, printing which rule/profile/signal matched (or didn't).

**Files:**
- Modify: `src/codeassay/cli.py`
- Create: `tests/test_cli_detect_test.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_detect_test.py`:

```python
import subprocess


def _make_commit(repo, filename, content, message):
    (repo / filename).write_text(content)
    subprocess.run(["git", "add", filename], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo, capture_output=True)


def test_detect_test_reports_profile_hit(tmp_repo):
    _make_commit(
        tmp_repo, "foo.py", "x\n",
        "feat: foo\n\nCo-Authored-By: Claude <x@a.com>",
    )
    hash_ = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_repo, capture_output=True, text=True,
    ).stdout.strip()
    result = subprocess.run(
        ["python", "-m", "codeassay", "detect-test", hash_],
        cwd=tmp_repo, capture_output=True, text=True,
    )
    assert result.returncode == 0
    out = result.stdout.lower()
    assert "claude_code" in out
    assert "profile" in out


def test_detect_test_reports_human(tmp_repo):
    _make_commit(tmp_repo, "foo.py", "x\n", "feat: foo by a human")
    hash_ = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_repo, capture_output=True, text=True,
    ).stdout.strip()
    result = subprocess.run(
        ["python", "-m", "codeassay", "detect-test", hash_],
        cwd=tmp_repo, capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "no match" in result.stdout.lower() or "human" in result.stdout.lower()
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_cli_detect_test.py -v`
Expected: FAIL — `detect-test` does not exist.

- [ ] **Step 3: Add subparser and handler**

In `src/codeassay/cli.py`:

a. Add imports at the top:

```python
from codeassay.detection import classify
from codeassay.detection.config import load_config
from codeassay.detection.profiles import load_profiles
from codeassay.detection.scorer import per_signal_contributions
from codeassay.scanner import parse_commit_log, _branches_containing
```

b. Add subparser in `build_parser()` after `config_p`:

```python
    dt_p = sub.add_parser("detect-test", help="Dry-run detection against one commit")
    dt_p.add_argument("commit", help="Commit hash")
```

c. Add handler:

```python
def cmd_detect_test(args) -> None:
    repo_path = Path.cwd().resolve()
    # Fetch the single commit's info via git log
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
        return
    print(f"Result: AI ({detection.tool}, confidence={detection.confidence})")
    print(f"  method: {detection.method}")
    print(f"  source: {detection.source}")
```

d. Add to `COMMANDS`:

```python
    "detect-test": cmd_detect_test,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli_detect_test.py -v`
Expected: PASS — both tests.

- [ ] **Step 5: Commit**

```bash
git add src/codeassay/cli.py tests/test_cli_detect_test.py
git commit -m "feat(cli): add detect-test dry-run subcommand"
```

---

## Task 16: New flags — `--with-scorer`, `--dry-run`, `--source`

Wire three new flags onto existing commands.

**Files:**
- Modify: `src/codeassay/cli.py`
- Modify: `src/codeassay/scanner.py`
- Create: `tests/test_cli_new_flags.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_new_flags.py`:

```python
import subprocess


def _make_commit(repo, filename, content, message, co_author=None):
    (repo / filename).write_text(content)
    subprocess.run(["git", "add", filename], cwd=repo, capture_output=True)
    msg = message + (f"\n\nCo-Authored-By: {co_author}" if co_author else "")
    subprocess.run(["git", "commit", "-m", msg], cwd=repo, capture_output=True)


def test_scan_dry_run_does_not_write_db(tmp_repo):
    _make_commit(
        tmp_repo, "foo.py", "x\n", "feat: foo",
        co_author="Claude <x@a.com>",
    )
    result = subprocess.run(
        ["python", "-m", "codeassay", "scan", str(tmp_repo), "--dry-run"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    db = tmp_repo / ".codeassay" / "quality.db"
    # DB may or may not exist after init, but the ai_commits table should be empty.
    if db.exists():
        import sqlite3
        conn = sqlite3.connect(db)
        rows = conn.execute("SELECT COUNT(*) FROM ai_commits").fetchone()[0]
        conn.close()
        assert rows == 0


def test_scan_with_scorer_flag_runs_scorer(tmp_repo):
    """--with-scorer should pick up commits that profiles miss."""
    _make_commit(
        tmp_repo, "foo.py", "a\nb\nc\nd\ne\nf\ng\nh\n",
        "feat: add structured feature 🤖\n\nSummary:\n- x\n- y\n\nTest plan:\n- run",
    )
    result = subprocess.run(
        ["python", "-m", "codeassay", "scan", str(tmp_repo), "--with-scorer"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    # Confirm at least one AI commit was detected via scorer.
    db = tmp_repo / ".codeassay" / "quality.db"
    import sqlite3
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT source FROM ai_commits WHERE source LIKE 'score:%'"
    ).fetchall()
    conn.close()
    assert len(rows) >= 1


def test_commits_source_filter(tmp_repo):
    _make_commit(
        tmp_repo, "a.py", "x\n", "feat: a",
        co_author="Claude <x@a.com>",
    )
    subprocess.run(
        ["python", "-m", "codeassay", "scan", str(tmp_repo)],
        capture_output=True, text=True, check=True,
    )
    result = subprocess.run(
        ["python", "-m", "codeassay", "commits", "--source", "profile:*"],
        cwd=tmp_repo, capture_output=True, text=True,
    )
    assert result.returncode == 0
    # Should list the one AI commit
    assert "feat: a" in result.stdout


def test_commits_source_filter_excludes(tmp_repo):
    _make_commit(
        tmp_repo, "a.py", "x\n", "feat: a",
        co_author="Claude <x@a.com>",
    )
    subprocess.run(
        ["python", "-m", "codeassay", "scan", str(tmp_repo)],
        capture_output=True, text=True, check=True,
    )
    result = subprocess.run(
        ["python", "-m", "codeassay", "commits", "--source", "score:*"],
        cwd=tmp_repo, capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "feat: a" not in result.stdout
```

- [ ] **Step 2: Run to confirm failure**

Run: `pytest tests/test_cli_new_flags.py -v`
Expected: FAIL — flags unknown.

- [ ] **Step 3: Extend `scan_repo` to support dry-run and override scorer**

In `src/codeassay/scanner.py`, replace the `scan_repo` function signature and body with:

```python
def scan_repo(
    repo_path: Path, conn, branch: str | None = None,
    *, dry_run: bool = False, force_scorer: bool = False,
) -> dict:
    repo_path = Path(repo_path).resolve()
    repo_str = str(repo_path)
    ignore_patterns = load_ignore_patterns(repo_path)
    config = load_config(repo_path)
    if force_scorer:
        config.score.enabled = True
    profiles = load_profiles(disabled=config.disabled_profiles)

    last_commit = get_last_scanned_commit(conn, repo_str) if not dry_run else None
    commits = parse_commit_log(repo_path, since_commit=last_commit)
    ai_count = 0

    needs_branches = bool(config.branch_rules) or any(p.branch_rules for p in profiles)
    scorer_on = config.score.enabled

    chronological = list(reversed(commits))
    prior = None
    for commit in chronological:
        commit["branches"] = (
            _branches_containing(repo_path, commit["hash"]) if needs_branches else set()
        )
        diff_stats = _diff_stats(repo_path, commit["hash"]) if scorer_on else []
        seconds_since_prior = _seconds_between(commit, prior) if scorer_on else None
        detection = classify(
            commit, config=config, profiles=profiles,
            diff_stats=diff_stats, seconds_since_prior=seconds_since_prior,
        )
        prior = commit
        if detection is None:
            continue

        files = _get_changed_files(repo_path, commit["hash"])
        files = filter_files_csv(files, ignore_patterns)
        if not files:
            continue
        ai_count += 1
        if dry_run:
            print(
                f"would store: {commit['hash'][:8]} tool={detection.tool} "
                f"source={detection.source}"
            )
            continue
        insert_ai_commit(
            conn,
            commit_hash=commit["hash"],
            repo_path=repo_str,
            author=commit["author"],
            date=commit["date"],
            message=commit["message"],
            tool=detection.tool,
            detection_method=detection.method,
            confidence=detection.confidence,
            files_changed=files,
            source=detection.source,
        )

    if commits and not dry_run:
        set_last_scanned_commit(conn, repo_str, commits[0]["hash"])
    return {"total_commits": len(commits), "ai_commits": ai_count}
```

- [ ] **Step 4: Add CLI flags**

In `src/codeassay/cli.py`:

a. Update the `scan` subparser definition:

```python
    scan_p = sub.add_parser("scan", help="Scan repos for AI commits and rework")
    scan_p.add_argument("repos", nargs="+", help="Paths to git repos to scan")
    scan_p.add_argument("--with-scorer", action="store_true",
                        help="Force-enable probabilistic scorer for this scan")
    scan_p.add_argument("--dry-run", action="store_true",
                        help="Report matches without writing to DB")
```

b. Update the `commits` and `rework` subparsers:

```python
    commits_p.add_argument("--source", help="Filter by detection source glob (e.g. 'profile:*')")
    # ... existing commits_p args stay as-is ...

    rework_p.add_argument("--source", help="Filter rework's original-commit source by glob")
```

c. Update `cmd_scan` to pass flags:

```python
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
```

d. Update `cmd_commits` to filter by `--source`:

```python
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
```

e. Update `cmd_rework` similarly:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_cli_new_flags.py -v`
Expected: PASS — all 4 tests.

- [ ] **Step 6: Run the full suite to catch regressions**

Run: `pytest -v`
Expected: PASS — all tests.

- [ ] **Step 7: Commit**

```bash
git add src/codeassay/scanner.py src/codeassay/cli.py tests/test_cli_new_flags.py
git commit -m "feat(cli): add --with-scorer, --dry-run, and --source flags"
```

---

## Task 17: Integration test — mixed-detection repo

End-to-end: build a repo with commits matching different tiers (profile, user rule, scorer) and verify the full `scan` → DB pipeline.

**Files:**
- Create: `tests/test_scan_integration.py`

- [ ] **Step 1: Write the test**

Create `tests/test_scan_integration.py`:

```python
import subprocess
from pathlib import Path

from codeassay.db import get_ai_commits, init_db, get_connection
from codeassay.scanner import scan_repo


def _commit(repo: Path, filename: str, content: str, message: str) -> None:
    (repo / filename).write_text(content)
    subprocess.run(["git", "add", filename], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo, capture_output=True)


def test_scan_with_mixed_signals(tmp_repo):
    # 1. Human commit (should not match).
    _commit(tmp_repo, "a.py", "print(1)\n", "feat: add a")

    # 2. Profile match (Claude co-author).
    _commit(
        tmp_repo, "b.py", "print(2)\n",
        "feat: add b\n\nCo-Authored-By: Claude <x@anthropic.com>",
    )

    # 3. User-rule match: we'll add a config so [AI] prefix is detected as custom tool.
    (tmp_repo / ".codeassay.toml").write_text(
        '[[detect.message]]\n'
        'pattern = "^\\\\[AI\\\\]"\n'
        'tool = "team_ai"\n'
        'confidence = "high"\n\n'
        '[score]\n'
        'enabled = true\n'
        'threshold = 0.4\n'
    )
    _commit(tmp_repo, "c.py", "print(3)\n", "[AI] feat: add c")

    # 4. Scorer-only match: structured message + emoji, no deterministic signal.
    structured_msg = (
        "feat: comprehensive refactor 🤖\n\n"
        "Summary:\n- replace module\n- update tests\n\n"
        "Test plan:\n- run pytest\n"
    )
    _commit(tmp_repo, "d.py", "x\n" * 20, structured_msg)

    # Run scan
    db_path = tmp_repo / ".codeassay" / "quality.db"
    init_db(db_path)
    conn = get_connection(db_path)
    result = scan_repo(tmp_repo, conn)
    rows = get_ai_commits(conn, repo_path=str(tmp_repo))
    conn.close()

    # Expect the 3 AI commits detected (profile, user-rule, scorer); skip the human one.
    sources = {r["source"] for r in rows}
    tools = {r["tool"] for r in rows}

    assert any(s == "profile:claude_code" for s in sources), sources
    assert any(s == "user:detect.message[0]" for s in sources), sources
    assert any(s and s.startswith("score:") for s in sources), sources
    assert "claude_code" in tools
    assert "team_ai" in tools
    assert "unknown" in tools  # scorer hit
    assert result["ai_commits"] == 3
```

- [ ] **Step 2: Run the test to confirm it passes**

Run: `pytest tests/test_scan_integration.py -v`
Expected: PASS — one test covering all three tiers.

- [ ] **Step 3: Run the full suite**

Run: `pytest -v`
Expected: PASS — all tests.

- [ ] **Step 4: Commit**

```bash
git add tests/test_scan_integration.py
git commit -m "test: add end-to-end scan integration with mixed detection tiers"
```

---

## Task 18: Update README

Document the new config and commands so end users can discover them.

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace the "How It Works" section**

Locate the `## How It Works` section and replace its contents:

```markdown
## How It Works

**AI Commit Detection** is layered — configurable in `.codeassay.toml`:

1. **User-defined rules** (highest priority) — match commits by author regex, branch pattern, commit-message regex, or author-plus-date-window.
2. **Built-in profiles** — shipped detectors for Claude Code, GitHub Copilot, Cursor, Aider, Windsurf, ChatGPT, and Gemini. Enabled by default, disable individually.
3. **Probabilistic scorer** (opt-in) — weights weak signals (diff shape, message structure, commit velocity, emoji, boilerplate headers, file diversity, punctuation) for commits no deterministic rule caught.

First match wins. Run `codeassay config init` to scaffold a starter config, `codeassay config show` to inspect the effective config, and `codeassay detect-test <hash>` to dry-run detection against a single commit.

To reliably tag AI commits going forward, install a git hook:

```bash
codeassay install-hook --tool cursor --mode always
```

This appends `AI-Assisted: cursor` to each commit message (idempotent — skips if a Co-Authored-By AI trailer is already present).

**Rework Detection** traces subsequent commits that modify AI-authored lines using `git blame` ancestry within a configurable time window (default: 14 days).

**Classification** categorizes rework into 7 types using commit message keywords and diff shape analysis:
- Bug fix, Misunderstanding, Test failure, Style/convention violation
- Security issue, Incomplete implementation, Over-engineering
```

- [ ] **Step 2: Replace the Commands table**

Locate the `## Commands` section and replace its table:

```markdown
| Command | Purpose |
|---------|---------|
| `codeassay scan <paths>` | Scan repos for AI commits and rework (supports `--with-scorer`, `--dry-run`) |
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
```

- [ ] **Step 3: Verify README still renders**

Run: `grep -c '^#' README.md`
Expected: Output ≥ 6 (at least that many section headings). A visual sanity-check is enough — if the heading count looks right, the structure is intact.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document configurable detection, new CLI, and hook installer"
```

---

## Task 19: Final full-suite check

- [ ] **Step 1: Run the full test suite**

Run: `pytest -v`
Expected: PASS — everything green.

- [ ] **Step 2: Smoke-test the CLI end-to-end**

Run:

```bash
python -m codeassay --help
python -m codeassay config show
```

Expected: `--help` lists `scan`, `report`, `commits`, `rework`, `reclassify`, `export`, `dashboard`, `config`, `detect-test`, `tag`, `install-hook`, `uninstall-hook`. `config show` prints profile names including `claude_code` and `cursor`.

- [ ] **Step 3: Confirm the feature is complete via the spec**

Open `docs/superpowers/specs/2026-04-18-configurable-ai-detection-design.md` and mentally walk each section; every requirement should map to at least one completed task above.

- [ ] **Step 4: No commit needed — this task is verification only.**

---

## Appendix: Spec → Task Map

| Spec section | Task(s) |
|---|---|
| Detection posture (layered) | 10 (classify), 11 (scanner) |
| Config file & schema | 4 (config loader), 14 (init/show) |
| Rule evaluation (author/branch/message/window) | 5 (rules), 10 (classify) |
| Built-in profiles | 6 (loader), 7 (TOMLs) |
| Probabilistic scorer | 8 (signals), 9 (aggregator), 10 (classify integration) |
| DB migration (`source` column) | 2 |
| `codeassay tag` + hook installer | 12, 13 |
| `codeassay config init` / `show` | 14 |
| `codeassay detect-test` | 15 |
| `--with-scorer`, `--dry-run`, `--source` flags | 16 |
| Code structure (`detection/` module) | 3, 11 |
| Testing strategy | 4, 5, 6, 7, 8, 9, 10, 11 (tests), 12, 13, 14, 15, 16, 17 |
| README update | 18 |
