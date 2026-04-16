"""Tests for codeassay.ignore."""

from pathlib import Path

from codeassay.ignore import (
    filter_files,
    filter_files_csv,
    is_ignored,
    load_ignore_patterns,
)


def test_load_ignore_patterns(tmp_path):
    ignore_file = tmp_path / ".codeassayignore"
    ignore_file.write_text("*.md\n# comment\n\n.organization\ndocs/*\n")
    patterns = load_ignore_patterns(tmp_path)
    assert patterns == ["*.md", ".organization", "docs/*"]


def test_load_ignore_patterns_missing(tmp_path):
    patterns = load_ignore_patterns(tmp_path)
    assert patterns == []


def test_is_ignored_extension():
    assert is_ignored("README.md", ["*.md"]) is True
    assert is_ignored("docs/guide.md", ["*.md"]) is True
    assert is_ignored("src/main.py", ["*.md"]) is False


def test_is_ignored_exact_filename():
    assert is_ignored(".organization", [".organization"]) is True
    assert is_ignored(".DS_Store", [".DS_Store"]) is True
    assert is_ignored("src/.organization", [".organization"]) is True


def test_is_ignored_directory_pattern():
    assert is_ignored("docs/guide.md", ["docs/*"]) is True
    assert is_ignored("docs/sub/file.txt", ["docs/*"]) is False
    assert is_ignored("docs/sub/file.txt", ["docs/**"]) is True


def test_is_ignored_no_patterns():
    assert is_ignored("anything.py", []) is False


def test_filter_files():
    files = ["src/main.py", "README.md", ".organization", "docs/guide.md"]
    patterns = ["*.md", ".organization"]
    result = filter_files(files, patterns)
    assert result == ["src/main.py"]


def test_filter_files_empty_patterns():
    files = ["src/main.py", "README.md"]
    assert filter_files(files, []) == files


def test_filter_files_csv():
    csv = "src/main.py,README.md,.organization,docs/guide.md"
    patterns = ["*.md", ".organization"]
    result = filter_files_csv(csv, patterns)
    assert result == "src/main.py"


def test_filter_files_csv_empty():
    assert filter_files_csv("", ["*.md"]) == ""
    assert filter_files_csv("src/main.py", []) == "src/main.py"
