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
pattern = '^\\[AI\\]'
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
