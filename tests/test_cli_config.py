import subprocess
import sys
from pathlib import Path
import pytest


def test_config_init_creates_file(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "codeassay", "config", "init"],
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
        [sys.executable, "-m", "codeassay", "config", "init"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "exists" in result.stderr.lower()


def test_config_init_force_overwrites(tmp_path):
    (tmp_path / ".codeassay.toml").write_text("# old\n")
    result = subprocess.run(
        [sys.executable, "-m", "codeassay", "config", "init", "--force"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "[profiles." in (tmp_path / ".codeassay.toml").read_text()


def test_config_show_lists_profiles(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "codeassay", "config", "show"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "claude_code" in result.stdout
    assert "cursor" in result.stdout
    assert "score" in result.stdout.lower()


def test_generated_config_is_valid_toml(tmp_path):
    """The starter template must load cleanly via load_config with no warnings."""
    import tomllib
    from codeassay.detection.config import load_config
    result = subprocess.run(
        [sys.executable, "-m", "codeassay", "config", "init"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0
    # Raises on invalid TOML
    with (tmp_path / ".codeassay.toml").open("rb") as f:
        tomllib.load(f)
    # Should also load via our DetectionConfig loader without raising.
    cfg = load_config(tmp_path)
    assert cfg.score.enabled is False


def test_starter_template_has_toml_guidance_comment(tmp_path):
    """The template must warn users against re-declaring [profiles.X] blocks."""
    result = subprocess.run(
        [sys.executable, "-m", "codeassay", "config", "init"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0
    content = (tmp_path / ".codeassay.toml").read_text()
    # Guidance comment must appear before the first [profiles.X] header
    profiles_idx = content.index("[profiles.")
    guidance_idx = content.index("Do NOT add a second")
    assert guidance_idx < profiles_idx, (
        "Guidance comment must precede the profiles block"
    )
    # Must explicitly mention changing enabled = true -> false
    assert "enabled = false" in content[:profiles_idx]
    assert "TOML forbids duplicate" in content
