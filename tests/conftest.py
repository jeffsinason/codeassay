"""Shared test fixtures for codeassay."""

import os
import sqlite3
import subprocess
import tempfile
from pathlib import Path

import pytest

from codeassay.db import init_db


@pytest.fixture
def tmp_repo(tmp_path):
    """Create a temporary git repo with some commits for testing."""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"], cwd=repo, capture_output=True
    )
    # Initial commit
    (repo / "README.md").write_text("# Test Repo\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"], cwd=repo, capture_output=True
    )
    return repo


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary database."""
    path = tmp_path / ".codeassay" / "quality.db"
    path.parent.mkdir(parents=True)
    init_db(path)
    return path


@pytest.fixture
def db_conn(db_path):
    """Return an open connection to a temp database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()
