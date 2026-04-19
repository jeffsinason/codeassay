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
