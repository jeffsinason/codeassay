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
    signature works without raising. Content-level assertions come in Task 7."""
    profiles = load_profiles()
    assert isinstance(profiles, list)


def test_load_profile_invalid_regex_raises(tmp_path):
    _write_profile(tmp_path, "bad", "[[detect.message]]\npattern='[unclosed'\ntool='x'\n")
    with pytest.raises(ValueError) as exc:
        load_profiles(profiles_dir=tmp_path)
    assert "bad" in str(exc.value)
