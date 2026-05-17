"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from asquared_mcp.config import Config, PushoverConfig, ServerConfig
from asquared_mcp.store import init_db


@pytest.fixture
def temp_db(tmp_path):
    """Create a fresh SQLite DB in a temp dir; return its path."""
    db_path = tmp_path / "test_coord.db"
    init_db(str(db_path))
    return str(db_path)


@pytest.fixture
def temp_config(tmp_path, temp_db):
    """Build a Config object pointing at the temp DB with dry-run notifications."""
    return Config(
        server=ServerConfig(port=8765, db_path=temp_db),
        tokens={
            "test-token-claude-web": "claude-web",
            "test-token-claude-code": "claude-code",
            "test-token-codex": "codex",
        },
        pushover=PushoverConfig(
            dry_run=True,
            user_key="",
            app_token="",
        ),
        allowed_origins=[
            "http://localhost",
            "http://localhost:8765",
            "https://mcp.asquaredhome.com",
        ],
    )
