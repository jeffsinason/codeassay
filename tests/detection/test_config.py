import re
from datetime import date
from pathlib import Path
import pytest

from codeassay.detection.config import (
    DetectionConfig, FingerprintConfig, RuleSpec, ScoreConfig, TurnoverConfig,
    WindowSpec, load_config,
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
    assert w.start == date(2026, 1, 1)
    assert w.end == date(2026, 3, 15)
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


def test_score_weights_zero_sum_falls_back_to_defaults(tmp_path, capsys):
    _write(tmp_path, """
[score]
enabled = true

[score.weights]
diff_wholesale_rewrite = 0.0
message_structured_body = 0.0
""")
    cfg = load_config(tmp_path)
    captured = capsys.readouterr()
    assert "fall" in captured.err.lower() or "default" in captured.err.lower()
    # Should have the full default weights restored
    assert len(cfg.score.weights) == 7
    assert abs(sum(cfg.score.weights.values()) - 1.0) < 0.01


def test_invalid_window_date_raises(tmp_path):
    _write(tmp_path, """
[[detect.window]]
author = "jeff@example.com"
start = "not-a-date"
end = "2026-03-15"
tool = "claude_code"
""")
    with pytest.raises(ValueError) as exc:
        load_config(tmp_path)
    assert "detect.window[0]" in str(exc.value)


def test_turnover_config_defaults(tmp_path):
    cfg = load_config(tmp_path)
    assert isinstance(cfg.turnover, TurnoverConfig)
    assert cfg.turnover.lookback_days == 90
    assert cfg.turnover.rewrite_window_days == 30
    assert cfg.turnover.yellow_threshold == 0.04
    assert cfg.turnover.red_threshold == 0.06


def test_turnover_config_overrides(tmp_path):
    _write(tmp_path, """
[turnover]
lookback_days = 60
rewrite_window_days = 14
yellow_threshold = 0.05
red_threshold = 0.08
""")
    cfg = load_config(tmp_path)
    assert cfg.turnover.lookback_days == 60
    assert cfg.turnover.rewrite_window_days == 14
    assert cfg.turnover.yellow_threshold == 0.05
    assert cfg.turnover.red_threshold == 0.08


def test_fingerprint_config_defaults(tmp_path):
    cfg = load_config(tmp_path)
    assert isinstance(cfg.fingerprint, FingerprintConfig)
    assert cfg.fingerprint.enabled is False
    assert cfg.fingerprint.min_prior_commits == 20
    assert cfg.fingerprint.sigma_threshold == 2.0
    assert cfg.fingerprint.min_divergent_metrics == 3


def test_fingerprint_config_enabled(tmp_path):
    _write(tmp_path, """
[fingerprint]
enabled = true
min_prior_commits = 30
sigma_threshold = 2.5
min_divergent_metrics = 4
""")
    cfg = load_config(tmp_path)
    assert cfg.fingerprint.enabled is True
    assert cfg.fingerprint.min_prior_commits == 30
    assert cfg.fingerprint.sigma_threshold == 2.5
    assert cfg.fingerprint.min_divergent_metrics == 4


def test_turnover_and_fingerprint_not_in_unknown_warning(tmp_path, capsys):
    _write(tmp_path, """
[turnover]
lookback_days = 60

[fingerprint]
enabled = true
""")
    load_config(tmp_path)
    captured = capsys.readouterr()
    # Neither section name should appear in an "unknown top-level key" warning
    assert "turnover" not in captured.err.lower() or "unknown" not in captured.err.lower()
    assert "fingerprint" not in captured.err.lower() or "unknown" not in captured.err.lower()
