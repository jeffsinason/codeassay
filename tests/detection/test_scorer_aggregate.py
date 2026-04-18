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
