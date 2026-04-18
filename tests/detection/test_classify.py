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
                          source="user:detect.author[0]", detection_confidence=90)


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
    assert d == Detection(tool="aider", confidence="high", method="profile", source="profile:aider",
                          detection_confidence=90)


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


def test_classify_scorer_produces_numeric_confidence():
    cfg = DetectionConfig(score=ScoreConfig(enabled=True, threshold=0.1))
    d = classify(_commit(message="feat: add thing 🤖"), config=cfg, profiles=[],
                 diff_stats=[], seconds_since_prior=None)
    assert d is not None
    assert 0 <= d.detection_confidence <= 100
    # Scorer's numeric confidence should roughly match the score value ×100
    # (source is "score:0.XX"); extract and compare within a small tolerance.
    raw = float(d.source.split(":")[1])
    assert abs(d.detection_confidence - int(round(raw * 100))) <= 1
