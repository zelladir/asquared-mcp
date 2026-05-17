"""Config loading tests."""

from __future__ import annotations

import textwrap

import pytest

from asquared_mcp.config import (
    Config, OAuthClientConfig, OAuthConfig, PushoverConfig, ServerConfig, load_config
)


def test_load_config_from_toml(tmp_path):
    """A valid config.toml loads into a Config object with all sections populated."""
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        """
[server]
port = 9000
db_path = "./data/test.db"

[tokens]
"abc123" = "claude-web"
"def456" = "claude-code"
"ghi789" = "codex"

[pushover]
dry_run = false
user_key = "u-test"
app_token = "a-test"

[security]
allowed_origins = ["https://mcp.asquaredhome.com", "http://localhost:8765"]
""",
        encoding="utf-8",
    )
    cfg = load_config(str(cfg_path))
    assert cfg.server.port == 9000
    assert cfg.server.db_path == "./data/test.db"
    assert cfg.tokens == {
        "abc123": "claude-web",
        "def456": "claude-code",
        "ghi789": "codex",
    }
    assert cfg.pushover.dry_run is False
    assert cfg.pushover.user_key == "u-test"
    assert cfg.pushover.app_token == "a-test"
    assert "https://mcp.asquaredhome.com" in cfg.allowed_origins


def test_load_config_missing_file_raises(tmp_path):
    """Missing config file is a hard error (no silent fallback)."""
    with pytest.raises(FileNotFoundError):
        load_config(str(tmp_path / "nope.toml"))


def test_pushover_dry_run_when_creds_empty(tmp_path):
    """If user_key is empty, dry_run is forced to True regardless of the toml setting."""
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        """
[server]
port = 8765
db_path = "./data/c.db"

[tokens]
"t1" = "claude-web"

[pushover]
dry_run = false
user_key = ""
app_token = ""
""",
        encoding="utf-8",
    )
    cfg = load_config(str(cfg_path))
    assert cfg.pushover.dry_run is True, "dry_run must be forced True when creds are empty"


def test_invalid_agent_id_in_tokens_rejected(tmp_path):
    """Token map values must be one of the known agent identities."""
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        """
[server]
port = 8765
db_path = "./data/c.db"

[tokens]
"t1" = "rogue-agent"

[pushover]
dry_run = true
user_key = ""
app_token = ""
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="rogue-agent"):
        load_config(str(cfg_path))


def test_oauth_config_defaults():
    config = Config(
        server=ServerConfig(port=8765, db_path="./data/coord.db"),
        tokens={"tok": "claude-code"},
        pushover=PushoverConfig(dry_run=True),
        allowed_origins=[],
    )
    assert config.oauth.token_ttl_seconds == 86400
    assert config.oauth.clients == {}


def test_oauth_config_loads_clients():
    config = Config(
        server=ServerConfig(port=8765, db_path="./data/coord.db"),
        tokens={"tok": "claude-code"},
        pushover=PushoverConfig(dry_run=True),
        allowed_origins=[],
        oauth=OAuthConfig(
            token_ttl_seconds=3600,
            clients={"ccw_abc": OAuthClientConfig(secret="ccs_xyz", agent_id="claude-web")},
        ),
    )
    assert config.oauth.token_ttl_seconds == 3600
    assert config.oauth.clients["ccw_abc"].agent_id == "claude-web"
    assert config.oauth.clients["ccw_abc"].secret == "ccs_xyz"


def test_load_config_with_oauth_section(tmp_path):
    toml = textwrap.dedent("""
        [server]
        port = 8765
        db_path = "./data/coord.db"

        [tokens]
        "static-token" = "claude-code"

        [pushover]
        dry_run = true

        [security]
        allowed_origins = ["https://mcp.asquaredhome.com"]

        [oauth]
        token_ttl_seconds = 7200

        [oauth.clients]
        "ccw_test" = { secret = "ccs_test", agent_id = "claude-web" }
    """)
    p = tmp_path / "config.toml"
    p.write_text(toml)
    config = load_config(str(p))
    assert config.oauth.token_ttl_seconds == 7200
    assert config.oauth.clients["ccw_test"].agent_id == "claude-web"


def test_load_config_without_oauth_section(tmp_path):
    toml = textwrap.dedent("""
        [server]
        port = 8765
        db_path = "./data/coord.db"

        [tokens]
        "tok" = "claude-code"

        [pushover]
        dry_run = true

        [security]
        allowed_origins = []
    """)
    p = tmp_path / "config.toml"
    p.write_text(toml)
    config = load_config(str(p))
    assert config.oauth.clients == {}
