"""TOML config loader for the coordination MCP server."""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator

VALID_AGENT_IDS: frozenset[str] = frozenset({"claude-web", "claude-code", "codex"})


class ServerConfig(BaseModel):
    port: int = 8765
    db_path: str = "./data/coord.db"


class PushoverConfig(BaseModel):
    dry_run: bool = True
    user_key: str = ""
    app_token: str = ""


class OAuthClientConfig(BaseModel):
    secret: str
    agent_id: str


class OAuthConfig(BaseModel):
    token_ttl_seconds: int = 86400
    clients: dict[str, OAuthClientConfig] = Field(default_factory=dict)


class HomeInventoryConfig(BaseModel):
    """Config block for the home-inventory tool family.

    Leaving ``base_url`` blank (the default) disables the inventory
    tools entirely — ``build_mcp`` only registers ``inventory_*`` when
    a base_url + token are both set. That keeps the server runnable for
    coord-only deployments without faking inventory connectivity.
    """

    base_url: str = ""
    token: str = ""
    timeout_seconds: float = 20.0


class Config(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    tokens: dict[str, str] = Field(default_factory=dict)
    pushover: PushoverConfig = Field(default_factory=PushoverConfig)
    allowed_origins: list[str] = Field(default_factory=list)
    oauth: OAuthConfig = Field(default_factory=OAuthConfig)
    home_inventory: HomeInventoryConfig = Field(default_factory=HomeInventoryConfig)

    @field_validator("tokens")
    @classmethod
    def _validate_token_agent_ids(cls, v: dict[str, str]) -> dict[str, str]:
        for _token, agent_id in v.items():
            if agent_id not in VALID_AGENT_IDS:
                raise ValueError(
                    f"Token maps to unknown agent_id {agent_id!r}; "
                    f"valid options: {sorted(VALID_AGENT_IDS)}"
                )
        return v

    @model_validator(mode="after")
    def _force_dry_run_when_empty_creds(self) -> Config:
        if not self.pushover.user_key or not self.pushover.app_token:
            self.pushover.dry_run = True
        return self


def load_config(path: str | Path) -> Config:
    """Read a TOML file from `path` and return a validated Config.

    Raises FileNotFoundError if the file is missing — no silent fallback.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {p}")
    with p.open("rb") as f:
        raw = tomllib.load(f)

    oauth_raw = raw.get("oauth", {})
    oauth_clients = {
        k: OAuthClientConfig(**v)
        for k, v in oauth_raw.get("clients", {}).items()
    }
    oauth_raw_clean = {k: v for k, v in oauth_raw.items() if k != "clients"}
    return Config(
        server=ServerConfig(**raw.get("server", {})),
        tokens=raw.get("tokens", {}),
        pushover=PushoverConfig(**raw.get("pushover", {})),
        allowed_origins=raw.get("security", {}).get("allowed_origins", []),
        oauth=OAuthConfig(clients=oauth_clients, **oauth_raw_clean),
        home_inventory=HomeInventoryConfig(**raw.get("home_inventory", {})),
    )
