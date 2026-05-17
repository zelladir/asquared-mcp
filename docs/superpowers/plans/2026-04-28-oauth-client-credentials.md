# OAuth Client Credentials Implementation Plan

**Historical note:** path references inside this plan use the pre-rename form
`src/pfit_coord_mcp/`. The active code lives at `src/asquared_mcp/` after the
2026-05-17 rename. The plan was executed as written and is preserved here as
a project record.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add OAuth 2.0 client credentials support so hosted AI connectors (Claude Web, ChatGPT, Gemini) can authenticate against the MCP server without breaking existing static Bearer token auth for Claude Code and Codex.

**Architecture:** Pre-configured OAuth clients live in `config.toml`. The server exposes RFC 9728/8414 discovery endpoints plus a `/token` endpoint that validates client credentials and issues short-lived access tokens stored in SQLite. `BearerTokenMiddleware` gains a second lookup path against the token table.

**Tech Stack:** Python 3.12, Starlette, SQLite (via stdlib sqlite3), Pydantic v2, pytest

---

## File Map

| File | Action | Responsibility |
| ---- | ------ | -------------- |
| `src/pfit_coord_mcp/config.py` | Modify | Add `OAuthClientConfig`, `OAuthConfig`; extend `Config` and `load_config` |
| `src/pfit_coord_mcp/store.py` | Modify | Add `oauth_access_tokens` table; add `store_oauth_token`, `lookup_oauth_token` |
| `src/pfit_coord_mcp/auth.py` | Modify | Add `OAUTH_PUBLIC_PATHS` bypass; extend `BearerTokenMiddleware` with `db_path` + second lookup |
| `src/pfit_coord_mcp/oauth.py` | Create | OAuth route handlers: discovery, `/token`, `/register` |
| `src/pfit_coord_mcp/server.py` | Modify | Mount OAuth routes; pass `db_path` to `BearerTokenMiddleware` |
| `config.toml.example` | Modify | Add commented `[oauth]` block |
| `tests/test_config.py` | Modify | Add OAuth config loading tests |
| `tests/test_store.py` | Modify | Add `store_oauth_token` / `lookup_oauth_token` tests |
| `tests/test_auth.py` | Modify | Add OAuth bypass tests; update `_build_app` helper for new `db_path` param |
| `tests/test_oauth.py` | Create | Route-level tests for discovery, `/token`, `/register`, end-to-end token use |

---

## Task 1: Config models

**Files:**
- Modify: `src/pfit_coord_mcp/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1.1: Write failing config tests**

Add to `tests/test_config.py`:

```python
from pfit_coord_mcp.config import (
    Config, OAuthClientConfig, OAuthConfig, PushoverConfig, ServerConfig, load_config
)
import tempfile, textwrap, pathlib


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
```

- [ ] **Step 1.2: Run tests to confirm they fail**

```bash
cd C:/PFIT/Coding/pfit-coord-mcp
.venv/Scripts/python.exe -m pytest tests/test_config.py::test_oauth_config_defaults tests/test_config.py::test_oauth_config_loads_clients tests/test_config.py::test_load_config_with_oauth_section tests/test_config.py::test_load_config_without_oauth_section -v
```

Expected: `ImportError` or `TypeError` — `OAuthClientConfig` and `OAuthConfig` don't exist yet.

- [ ] **Step 1.3: Implement config models**

In `src/pfit_coord_mcp/config.py`, add after `PushoverConfig`:

```python
class OAuthClientConfig(BaseModel):
    secret: str
    agent_id: str


class OAuthConfig(BaseModel):
    token_ttl_seconds: int = 86400
    clients: dict[str, OAuthClientConfig] = Field(default_factory=dict)
```

Add `oauth` field to `Config`:

```python
class Config(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    tokens: dict[str, str] = Field(default_factory=dict)
    pushover: PushoverConfig = Field(default_factory=PushoverConfig)
    allowed_origins: list[str] = Field(default_factory=list)
    oauth: OAuthConfig = Field(default_factory=OAuthConfig)
    # ... validators unchanged ...
```

Update `load_config` to parse the new section. Replace the `return Config(...)` block:

```python
    oauth_raw = raw.get("oauth", {})
    oauth_clients = {
        k: OAuthClientConfig(**v)
        for k, v in oauth_raw.get("clients", {}).items()
    }
    return Config(
        server=ServerConfig(**raw.get("server", {})),
        tokens=raw.get("tokens", {}),
        pushover=PushoverConfig(**raw.get("pushover", {})),
        allowed_origins=raw.get("security", {}).get("allowed_origins", []),
        oauth=OAuthConfig(
            token_ttl_seconds=oauth_raw.get("token_ttl_seconds", 86400),
            clients=oauth_clients,
        ),
    )
```

- [ ] **Step 1.4: Run tests to confirm they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_config.py -v
```

Expected: all config tests pass.

- [ ] **Step 1.5: Run full suite to check for regressions**

```bash
.venv/Scripts/python.exe -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 1.6: Commit**

```bash
git add src/pfit_coord_mcp/config.py tests/test_config.py
git commit -m "feat(config): add OAuthClientConfig and OAuthConfig models"
```

---

## Task 2: SQLite oauth_access_tokens table

**Files:**
- Modify: `src/pfit_coord_mcp/store.py`
- Modify: `tests/test_store.py`

- [ ] **Step 2.1: Write failing store tests**

Add to `tests/test_store.py`:

```python
from pfit_coord_mcp.store import lookup_oauth_token, store_oauth_token


def test_store_and_lookup_valid_oauth_token(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    store_oauth_token(db, "oat_valid", "ccw_test", "claude-web", "2099-01-01T00:00:00+00:00")
    row = lookup_oauth_token(db, "oat_valid")
    assert row is not None
    assert row["agent_id"] == "claude-web"
    assert row["client_id"] == "ccw_test"


def test_lookup_expired_oauth_token(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    store_oauth_token(db, "oat_expired", "ccw_test", "claude-web", "2000-01-01T00:00:00+00:00")
    assert lookup_oauth_token(db, "oat_expired") is None


def test_lookup_missing_oauth_token(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    assert lookup_oauth_token(db, "oat_nonexistent") is None


def test_init_db_creates_oauth_table(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    import sqlite3
    conn = sqlite3.connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "oauth_access_tokens" in tables
```

- [ ] **Step 2.2: Run tests to confirm they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_store.py::test_store_and_lookup_valid_oauth_token tests/test_store.py::test_lookup_expired_oauth_token tests/test_store.py::test_lookup_missing_oauth_token tests/test_store.py::test_init_db_creates_oauth_table -v
```

Expected: `ImportError` — `store_oauth_token` and `lookup_oauth_token` don't exist yet.

- [ ] **Step 2.3: Add schema and functions to store.py**

In `src/pfit_coord_mcp/store.py`, append to `SCHEMA` (inside the triple-quoted string, after the `meta` table):

```sql

CREATE TABLE IF NOT EXISTS oauth_access_tokens (
    token      TEXT PRIMARY KEY,
    client_id  TEXT NOT NULL,
    agent_id   TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
```

Add two functions at the end of the file:

```python
def store_oauth_token(
    db_path: str,
    token: str,
    client_id: str,
    agent_id: str,
    expires_at: str,
) -> None:
    """Store an issued OAuth access token."""
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO oauth_access_tokens (token, client_id, agent_id, created_at, expires_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (token, client_id, agent_id, _now_iso(), expires_at),
        )


def lookup_oauth_token(db_path: str, token: str) -> sqlite3.Row | None:
    """Return the token row if it exists and has not expired; None otherwise.

    Both missing and expired tokens return None — callers cannot distinguish them.
    """
    with _connect(db_path) as conn:
        return conn.execute(
            "SELECT * FROM oauth_access_tokens WHERE token = ? AND expires_at > ?",
            (token, _now_iso()),
        ).fetchone()
```

- [ ] **Step 2.4: Run tests to confirm they pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_store.py -v
```

Expected: all store tests pass.

- [ ] **Step 2.5: Commit**

```bash
git add src/pfit_coord_mcp/store.py tests/test_store.py
git commit -m "feat(store): add oauth_access_tokens table and lookup functions"
```

---

## Task 3: Auth layer — bypass list and extended token lookup

**Files:**
- Modify: `src/pfit_coord_mcp/auth.py`
- Modify: `tests/test_auth.py`

- [ ] **Step 3.1: Write failing auth tests**

Add to `tests/test_auth.py`. First update the `_build_app` helper to accept `db_path` (add it after the existing helper — do not change the existing helper signature yet, add a new one):

```python
def _build_app_with_db(
    token_map: dict[str, str],
    db_path: str,
    allowed_origins: list[str] | None = None,
):
    """Like _build_app but passes db_path to BearerTokenMiddleware."""

    async def echo(request: Request) -> JSONResponse:
        agent_id = getattr(request.state, AGENT_ID_STATE_KEY, None)
        return JSONResponse({"agent_id": agent_id})

    middleware = []
    if allowed_origins is not None:
        middleware.append(Middleware(OriginAllowlistMiddleware, allowed_origins=allowed_origins))
    middleware.append(Middleware(BearerTokenMiddleware, token_map=token_map, db_path=db_path))
    return Starlette(routes=[Route("/", echo), Route("/health", echo)], middleware=middleware)
```

Then add the new tests:

```python
from pfit_coord_mcp.auth import OAUTH_PUBLIC_PATHS
from pfit_coord_mcp.store import init_db, store_oauth_token


def test_oauth_public_paths_are_defined():
    assert "/.well-known/oauth-protected-resource" in OAUTH_PUBLIC_PATHS
    assert "/.well-known/oauth-authorization-server" in OAUTH_PUBLIC_PATHS
    assert "/token" in OAUTH_PUBLIC_PATHS
    assert "/register" in OAUTH_PUBLIC_PATHS


def test_bearer_bypasses_oauth_paths(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    app = _build_app_with_db({"tok": "claude-code"}, db_path=db)
    client = TestClient(app, raise_server_exceptions=False)
    # These paths should pass through without auth
    for path in ["/.well-known/oauth-protected-resource", "/token", "/register"]:
        r = client.get(path)
        assert r.status_code != 401, f"{path} returned 401 — should bypass auth"


def test_origin_middleware_bypasses_oauth_paths():
    app = Starlette(
        routes=[Route("/.well-known/oauth-authorization-server", lambda r: JSONResponse({}))],
        middleware=[Middleware(OriginAllowlistMiddleware, allowed_origins=["https://example.com"])],
    )
    client = TestClient(app)
    r = client.get(
        "/.well-known/oauth-authorization-server",
        headers={"Origin": "https://untrusted.example"},
    )
    assert r.status_code != 403


def test_bearer_accepts_oauth_token(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    store_oauth_token(db, "oat_test123", "ccw_test", "claude-web", "2099-01-01T00:00:00+00:00")
    app = _build_app_with_db({}, db_path=db)
    client = TestClient(app)
    r = client.get("/", headers={"Authorization": "Bearer oat_test123"})
    assert r.status_code == 200
    assert r.json()["agent_id"] == "claude-web"


def test_bearer_rejects_expired_oauth_token(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    store_oauth_token(db, "oat_expired", "ccw_test", "claude-web", "2000-01-01T00:00:00+00:00")
    app = _build_app_with_db({}, db_path=db)
    client = TestClient(app)
    r = client.get("/", headers={"Authorization": "Bearer oat_expired"})
    assert r.status_code == 401
```

- [ ] **Step 3.2: Run tests to confirm they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_auth.py::test_oauth_public_paths_are_defined tests/test_auth.py::test_bearer_bypasses_oauth_paths tests/test_auth.py::test_origin_middleware_bypasses_oauth_paths tests/test_auth.py::test_bearer_accepts_oauth_token tests/test_auth.py::test_bearer_rejects_expired_oauth_token -v
```

Expected: `ImportError` or `TypeError` — `OAUTH_PUBLIC_PATHS` doesn't exist yet and `BearerTokenMiddleware` doesn't accept `db_path`.

- [ ] **Step 3.3: Update auth.py**

Replace `src/pfit_coord_mcp/auth.py` with:

```python
"""Starlette middleware: Bearer-token auth + Origin allowlist."""

from __future__ import annotations

import secrets
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from .store import lookup_oauth_token

AGENT_ID_STATE_KEY = "agent_id"
HEALTH_PATH = "/health"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
UNAUTHORIZED_RESPONSE = {"error": "unauthorized", "message": "Unauthorized"}

OAUTH_PUBLIC_PATHS = frozenset({
    "/.well-known/oauth-protected-resource",
    "/.well-known/oauth-authorization-server",
    "/token",
    "/register",
})

_BYPASS_PATHS = frozenset({HEALTH_PATH}) | OAUTH_PUBLIC_PATHS


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Validate `Authorization: Bearer <token>`; attach agent_id to request.state.

    /health and OAuth public paths are unauthenticated (bypass).
    Token resolution checks static config tokens first, then SQLite OAuth tokens.
    """

    def __init__(self, app: ASGIApp, token_map: dict[str, str], db_path: str = "") -> None:
        super().__init__(app)
        self.token_map = token_map
        self.db_path = db_path

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in _BYPASS_PATHS:
            return await call_next(request)

        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token or token.strip() != token or " " in token:
            return JSONResponse(UNAUTHORIZED_RESPONSE, status_code=401)
        agent_id = self._resolve_agent_id(token)
        if agent_id is None:
            return JSONResponse(UNAUTHORIZED_RESPONSE, status_code=401)
        setattr(request.state, AGENT_ID_STATE_KEY, agent_id)
        request.scope[AGENT_ID_STATE_KEY] = agent_id
        return await call_next(request)

    def _resolve_agent_id(self, presented_token: str) -> str | None:
        # 1. Static config tokens (constant-time comparison)
        matched_agent: str | None = None
        for configured_token, agent_id in self.token_map.items():
            if secrets.compare_digest(presented_token, configured_token):
                matched_agent = agent_id
        if matched_agent is not None:
            return matched_agent
        # 2. OAuth access tokens from SQLite
        if self.db_path:
            row = lookup_oauth_token(self.db_path, presented_token)
            if row is not None:
                return str(row["agent_id"])
        return None


class OriginAllowlistMiddleware(BaseHTTPMiddleware):
    """DNS-rebinding defense per MCP streamable HTTP spec.

    Rules:
    - /health and OAuth public paths are exempt.
    - Requests with no Origin header pass through (CLI / curl / non-browser).
    - Requests with an Origin header must match one of `allowed_origins`.
    - Requests that arrive for a configured public HTTPS host pass through even
      when the client Origin is a rotating hosted-client origin.
    """

    def __init__(self, app: ASGIApp, allowed_origins: list[str]) -> None:
        super().__init__(app)
        self.allowed_origins = set(allowed_origins)
        self.trusted_public_hosts = {
            parsed.hostname
            for origin in allowed_origins
            if (parsed := urlsplit(origin)).scheme == "https"
            and parsed.hostname is not None
            and parsed.hostname not in LOCAL_HOSTS
        }

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in _BYPASS_PATHS:
            return await call_next(request)
        origin = request.headers.get("origin")
        if origin is not None and origin not in self.allowed_origins:
            if request.url.hostname not in self.trusted_public_hosts:
                return JSONResponse(
                    {"error": "forbidden_origin", "message": "Origin not allowed"},
                    status_code=403,
                )
        return await call_next(request)
```

- [ ] **Step 3.4: Run auth tests**

```bash
.venv/Scripts/python.exe -m pytest tests/test_auth.py -v
```

Expected: all auth tests pass.

- [ ] **Step 3.5: Run full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 3.6: Commit**

```bash
git add src/pfit_coord_mcp/auth.py tests/test_auth.py
git commit -m "feat(auth): add OAuth public path bypass and SQLite token lookup"
```

---

## Task 4: OAuth route handlers + server wiring

**Files:**
- Create: `src/pfit_coord_mcp/oauth.py`
- Modify: `src/pfit_coord_mcp/server.py`
- Create: `tests/test_oauth.py`

- [ ] **Step 4.1: Write failing OAuth route tests**

Create `tests/test_oauth.py`:

```python
"""OAuth 2.0 client credentials route tests."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from pfit_coord_mcp.config import Config, OAuthClientConfig, OAuthConfig, PushoverConfig, ServerConfig
from pfit_coord_mcp.server import build_app
from pfit_coord_mcp.store import init_db


@pytest.fixture
def oauth_config(tmp_path):
    db = str(tmp_path / "test.db")
    init_db(db)
    return Config(
        server=ServerConfig(port=8765, db_path=db),
        tokens={"static-tok-cc": "claude-code"},
        pushover=PushoverConfig(dry_run=True),
        allowed_origins=[
            "https://mcp.asquaredhome.com",
            "http://localhost:8765",
            "http://127.0.0.1:8765",
        ],
        oauth=OAuthConfig(
            token_ttl_seconds=3600,
            clients={
                "ccw_testclient": OAuthClientConfig(secret="ccs_testsecret", agent_id="claude-web")
            },
        ),
    )


# --- Discovery endpoints ---

def test_oauth_protected_resource(oauth_config):
    client = TestClient(build_app(oauth_config))
    r = client.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 200
    data = r.json()
    assert data["resource"] == "https://mcp.asquaredhome.com"
    assert "https://mcp.asquaredhome.com" in data["authorization_servers"]


def test_oauth_authorization_server(oauth_config):
    client = TestClient(build_app(oauth_config))
    r = client.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200
    data = r.json()
    assert data["issuer"] == "https://mcp.asquaredhome.com"
    assert data["token_endpoint"] == "https://mcp.asquaredhome.com/token"
    assert "authorization_endpoint" not in data
    assert "client_credentials" in data["grant_types_supported"]


def test_discovery_requires_no_auth(oauth_config):
    client = TestClient(build_app(oauth_config))
    # No Authorization header — should not get 401
    assert client.get("/.well-known/oauth-protected-resource").status_code == 200
    assert client.get("/.well-known/oauth-authorization-server").status_code == 200


# --- /token endpoint ---

def test_token_valid_credentials(oauth_config):
    client = TestClient(build_app(oauth_config))
    r = client.post("/token", data={
        "grant_type": "client_credentials",
        "client_id": "ccw_testclient",
        "client_secret": "ccs_testsecret",
    })
    assert r.status_code == 200
    data = r.json()
    assert "access_token" in data
    assert data["token_type"] == "Bearer"
    assert data["expires_in"] == 3600
    assert data["access_token"].startswith("oat_")


def test_token_wrong_secret(oauth_config):
    client = TestClient(build_app(oauth_config))
    r = client.post("/token", data={
        "grant_type": "client_credentials",
        "client_id": "ccw_testclient",
        "client_secret": "wrong_secret",
    })
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_client"


def test_token_unknown_client_id(oauth_config):
    client = TestClient(build_app(oauth_config))
    r = client.post("/token", data={
        "grant_type": "client_credentials",
        "client_id": "ccw_unknown",
        "client_secret": "anything",
    })
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_client"


def test_token_wrong_grant_type(oauth_config):
    client = TestClient(build_app(oauth_config))
    r = client.post("/token", data={
        "grant_type": "authorization_code",
        "client_id": "ccw_testclient",
        "client_secret": "ccs_testsecret",
    })
    assert r.status_code == 400
    assert r.json()["error"] == "unsupported_grant_type"


def test_token_endpoint_requires_no_auth(oauth_config):
    client = TestClient(build_app(oauth_config))
    # POST without Authorization header should not get 401 on /token itself
    r = client.post("/token", data={
        "grant_type": "client_credentials",
        "client_id": "ccw_testclient",
        "client_secret": "ccs_testsecret",
    })
    assert r.status_code != 401


# --- /register endpoint ---

def test_register_returns_400(oauth_config):
    client = TestClient(build_app(oauth_config))
    r = client.post("/register", json={"client_name": "some-connector"})
    assert r.status_code == 400
    assert r.json()["error"] == "registration_not_supported"


# --- End-to-end: token issued by /token works on /mcp ---

def test_oauth_token_authenticates_on_mcp(oauth_config):
    client = TestClient(build_app(oauth_config))
    # Step 1: get a token
    r = client.post("/token", data={
        "grant_type": "client_credentials",
        "client_id": "ccw_testclient",
        "client_secret": "ccs_testsecret",
    })
    assert r.status_code == 200
    token = r.json()["access_token"]

    # Step 2: use it on /mcp — should not get 401 (may get 200, 405, or MCP-layer response)
    r2 = client.post("/mcp", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code != 401, f"Expected auth to pass, got 401. Token: {token}"


# --- Regression: static Bearer tokens still work ---

def test_static_bearer_token_still_works(oauth_config):
    client = TestClient(build_app(oauth_config))
    r = client.get("/health")
    assert r.status_code == 200

    # Static token should authenticate on /mcp
    r2 = client.post("/mcp", headers={"Authorization": "Bearer static-tok-cc"})
    assert r2.status_code != 401
```

- [ ] **Step 4.2: Run tests to confirm they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_oauth.py -v
```

Expected: `ModuleNotFoundError` — `oauth.py` doesn't exist yet.

- [ ] **Step 4.3: Create oauth.py**

Create `src/pfit_coord_mcp/oauth.py`:

```python
"""OAuth 2.0 client credentials routes."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .config import Config
from .store import store_oauth_token

_LOCAL_HOSTNAMES = {"localhost", "127.0.0.1", "::1"}


def _base_url(allowed_origins: list[str]) -> str:
    """Return the first HTTPS non-local origin as the OAuth issuer base URL."""
    for origin in allowed_origins:
        if not origin.startswith("https://"):
            continue
        host = origin.removeprefix("https://").split(":")[0]
        if host not in _LOCAL_HOSTNAMES:
            return origin
    return allowed_origins[0] if allowed_origins else "http://localhost:8765"


def build_oauth_routes(config: Config) -> list[Route]:
    """Return Starlette Route objects for all OAuth endpoints."""
    base = _base_url(config.allowed_origins)

    async def oauth_protected_resource(_request: Request) -> Response:
        return JSONResponse({
            "resource": base,
            "authorization_servers": [base],
        })

    async def oauth_authorization_server(_request: Request) -> Response:
        return JSONResponse({
            "issuer": base,
            "token_endpoint": f"{base}/token",
            "grant_types_supported": ["client_credentials"],
            "token_endpoint_auth_methods_supported": [
                "client_secret_post",
                "client_secret_basic",
            ],
        })

    async def oauth_token(request: Request) -> Response:
        form = await request.form()
        grant_type = form.get("grant_type") or ""
        if grant_type != "client_credentials":
            return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

        client_id = str(form.get("client_id") or "")
        client_secret = str(form.get("client_secret") or "")

        client = config.oauth.clients.get(client_id)
        # Always compare to prevent timing-based enumeration of client IDs.
        expected = client.secret if client is not None else secrets.token_urlsafe(32)
        match = secrets.compare_digest(client_secret, expected)
        if client is None or not match:
            return JSONResponse({"error": "invalid_client"}, status_code=400)

        token = "oat_" + secrets.token_urlsafe(32)
        expires_at = (
            datetime.now(UTC) + timedelta(seconds=config.oauth.token_ttl_seconds)
        ).isoformat(timespec="seconds")
        store_oauth_token(
            config.server.db_path,
            token,
            client_id,
            client.agent_id,
            expires_at,
        )
        return JSONResponse({
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": config.oauth.token_ttl_seconds,
        })

    async def oauth_register(_request: Request) -> Response:
        return JSONResponse(
            {
                "error": "registration_not_supported",
                "message": (
                    "Dynamic registration is disabled. "
                    "Request credentials from the administrator."
                ),
            },
            status_code=400,
        )

    return [
        Route("/.well-known/oauth-protected-resource", oauth_protected_resource),
        Route("/.well-known/oauth-authorization-server", oauth_authorization_server),
        Route("/token", oauth_token, methods=["POST"]),
        Route("/register", oauth_register, methods=["POST"]),
    ]
```

- [ ] **Step 4.4: Wire OAuth routes into server.py**

In `src/pfit_coord_mcp/server.py`:

Add import near the top with other local imports:
```python
from .oauth import build_oauth_routes
```

Replace `build_app`'s `return Starlette(...)` block:

```python
    return Starlette(
        routes=[
            Route(HEALTH_PATH, health),
            *build_oauth_routes(config),
            Mount("/", app=mcp_asgi),
        ],
        middleware=[
            Middleware(OriginAllowlistMiddleware, allowed_origins=config.allowed_origins),
            Middleware(BearerTokenMiddleware, token_map=config.tokens, db_path=config.server.db_path),
            Middleware(AgentContextMiddleware),
        ],
        lifespan=lambda app: mcp.session_manager.run(),
    )
```

- [ ] **Step 4.5: Run OAuth tests**

```bash
.venv/Scripts/python.exe -m pytest tests/test_oauth.py -v
```

Expected: all OAuth tests pass.

- [ ] **Step 4.6: Run full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```

Expected: all 75+ tests pass.

- [ ] **Step 4.7: Commit**

```bash
git add src/pfit_coord_mcp/oauth.py src/pfit_coord_mcp/server.py tests/test_oauth.py
git commit -m "feat(oauth): add client credentials flow — discovery, /token, /register"
```

---

## Task 5: Update config.toml.example

**Files:**
- Modify: `config.toml.example`

- [ ] **Step 5.1: Add OAuth block**

In `config.toml.example`, add after the `[security]` block:

```toml
[oauth]
# Access token lifetime in seconds (default: 86400 = 24 hours).
token_ttl_seconds = 86400

# Pre-configured OAuth clients for hosted AI connectors (Claude Web, ChatGPT, Gemini, etc.).
# Generate credentials with:
#   python -c "import secrets; print('ccw_' + secrets.token_urlsafe(16)); print('ccs_' + secrets.token_urlsafe(32))"
# Then paste the client_id and secret into the connector's OAuth settings in its UI.
# [oauth.clients]
# "REPLACE_WITH_CLIENT_ID" = { secret = "REPLACE_WITH_CLIENT_SECRET", agent_id = "claude-web" }
```

- [ ] **Step 5.2: Commit**

```bash
git add config.toml.example
git commit -m "docs(config): add commented oauth block to config.toml.example"
```

---

## Task 6: Generate credentials, deploy, and verify

**Files:**
- Modify: `config.toml` on codeserver (via scp/ssh)

- [ ] **Step 6.1: Generate claude-web OAuth credentials**

```bash
python -c "
import secrets
client_id = 'ccw_' + secrets.token_urlsafe(16)
client_secret = 'ccs_' + secrets.token_urlsafe(32)
print(f'client_id:     {client_id}')
print(f'client_secret: {client_secret}')
"
```

Save both values to 1Password as `coord-mcp/claude-web-oauth-client-id` and `coord-mcp/claude-web-oauth-client-secret`.

- [ ] **Step 6.2: Add [oauth] block to codeserver config.toml**

SSH to codeserver and edit `~/pfit-coord-mcp/config.toml`. Add after the `[security]` block:

```toml
[oauth]
token_ttl_seconds = 86400

[oauth.clients]
"<client_id_from_step_6.1>" = { secret = "<client_secret_from_step_6.1>", agent_id = "claude-web" }
```

- [ ] **Step 6.3: Push code to repo and redeploy**

```bash
cd C:/PFIT/Coding/pfit-coord-mcp
git push origin <branch>
```

Then open a PR, merge to main, and on the codeserver:

```bash
ssh codeserver "cd ~/pfit-coord-mcp && git pull origin main && docker compose up -d --build 2>&1 | tail -8"
```

- [ ] **Step 6.4: Verify OAuth discovery is live**

```bash
curl -s --resolve mcp.asquaredhome.com:443:104.21.95.55 \
  https://mcp.asquaredhome.com/.well-known/oauth-authorization-server | python -m json.tool
```

Expected: JSON with `issuer`, `token_endpoint`, `grant_types_supported: ["client_credentials"]`.

- [ ] **Step 6.5: Verify /token endpoint issues a token**

```bash
CLIENT_ID="<client_id_from_step_6.1>"
CLIENT_SECRET="<client_secret_from_step_6.1>"

curl -s --resolve mcp.asquaredhome.com:443:104.21.95.55 \
  -X POST https://mcp.asquaredhome.com/token \
  -d "grant_type=client_credentials&client_id=${CLIENT_ID}&client_secret=${CLIENT_SECRET}"
```

Expected: `{"access_token": "oat_...", "token_type": "Bearer", "expires_in": 86400}`.

- [ ] **Step 6.6: Verify the issued token works on /mcp**

```bash
TOKEN="<access_token_from_step_6.5>"

curl -sI --resolve mcp.asquaredhome.com:443:104.21.95.55 \
  -H "Authorization: Bearer $TOKEN" \
  https://mcp.asquaredhome.com/mcp
```

Expected: not 401 (200, 307, or MCP-layer response).

- [ ] **Step 6.7: Configure Claude Web connector**

In Claude Web → Settings → Connectors → Add Custom Connector:
- Name: `pfit-coord`
- URL: `https://mcp.asquaredhome.com/mcp`
- OAuth Client ID: `<client_id_from_step_6.1>`
- OAuth Client Secret: `<client_secret_from_step_6.1>`

Save. Start a chat and ask: "What tools do you have available from pfit-coord?"

Expected: `coord_post`, `coord_read`, `coord_threads`, `coord_ack`, `coord_status`.
