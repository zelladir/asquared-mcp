"""Auth middleware tests."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from asquared_mcp.auth import (
    AGENT_ID_STATE_KEY,
    BearerTokenMiddleware,
    OriginAllowlistMiddleware,
    OAUTH_PUBLIC_PATHS,
)
from asquared_mcp.store import init_db, store_oauth_token


def _build_app(token_map: dict[str, str], allowed_origins: list[str] | None = None):
    """Tiny app that echoes the resolved agent_id from request.state."""

    async def echo(request: Request) -> JSONResponse:
        agent_id = getattr(request.state, AGENT_ID_STATE_KEY, None)
        return JSONResponse({"agent_id": agent_id})

    middleware = []
    if allowed_origins is not None:
        middleware.append(Middleware(OriginAllowlistMiddleware, allowed_origins=allowed_origins))
    middleware.append(Middleware(BearerTokenMiddleware, token_map=token_map))

    return Starlette(
        routes=[Route("/echo", echo, methods=["GET", "POST"])],
        middleware=middleware,
    )


def test_missing_authorization_returns_401():
    client = TestClient(_build_app({"abc": "claude-web"}))
    r = client.get("/echo")
    assert r.status_code == 401
    assert r.json()["error"] == "unauthorized"
    assert r.json()["message"] == "Unauthorized"


def test_malformed_authorization_returns_401():
    client = TestClient(_build_app({"abc": "claude-web"}))
    r = client.get("/echo", headers={"Authorization": "Token abc"})
    assert r.status_code == 401


def test_unknown_token_returns_401():
    client = TestClient(_build_app({"abc": "claude-web"}))
    r = client.get("/echo", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401
    assert r.json() == {"error": "unauthorized", "message": "Unauthorized"}


def test_valid_token_attaches_agent_id():
    client = TestClient(_build_app({"abc": "claude-web"}))
    r = client.get("/echo", headers={"Authorization": "Bearer abc"})
    assert r.status_code == 200
    assert r.json() == {"agent_id": "claude-web"}


def test_token_comparison_uses_compare_digest(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_compare_digest(a: str, b: str) -> bool:
        calls.append((a, b))
        return a == b

    monkeypatch.setattr("asquared_mcp.auth.secrets.compare_digest", fake_compare_digest)
    client = TestClient(_build_app({"abc": "claude-web"}))
    r = client.get("/echo", headers={"Authorization": "Bearer abc"})
    assert r.status_code == 200
    assert calls == [("abc", "abc")]


def test_query_string_token_is_not_accepted():
    client = TestClient(_build_app({"abc": "claude-web"}))
    r = client.get("/echo?access_token=abc")
    assert r.status_code == 401


def test_authorization_with_extra_spaces_rejected():
    client = TestClient(_build_app({"abc": "claude-web"}))
    assert client.get("/echo", headers={"Authorization": "Bearer  abc"}).status_code == 401
    assert client.get("/echo", headers={"Authorization": "Bearer abc "}).status_code == 401


def test_health_endpoint_bypasses_auth():
    """Requests to /health pass through both middlewares unauthenticated."""
    from asquared_mcp.auth import HEALTH_PATH

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    app = Starlette(
        routes=[Route(HEALTH_PATH, health)],
        middleware=[Middleware(BearerTokenMiddleware, token_map={"abc": "claude-web"})],
    )
    client = TestClient(app)
    assert client.get(HEALTH_PATH).status_code == 200


def test_origin_allowed_passes():
    client = TestClient(
        _build_app(
            {"abc": "claude-web"},
            allowed_origins=["https://mcp.asquaredhome.com"],
        )
    )
    r = client.get(
        "/echo",
        headers={
            "Authorization": "Bearer abc",
            "Origin": "https://mcp.asquaredhome.com",
        },
    )
    assert r.status_code == 200


def test_origin_disallowed_rejected():
    client = TestClient(
        _build_app(
            {"abc": "claude-web"},
            allowed_origins=["https://mcp.asquaredhome.com"],
        )
    )
    r = client.get(
        "/echo",
        headers={
            "Authorization": "Bearer abc",
            "Origin": "https://attacker.example.com",
        },
    )
    assert r.status_code == 403
    assert r.json() == {"error": "forbidden_origin", "message": "Origin not allowed"}


def test_origin_from_hosted_client_allowed_for_public_tunnel_host():
    client = TestClient(
        _build_app(
            {"abc": "claude-web"},
            allowed_origins=["https://mcp.asquaredhome.com", "http://localhost:8765"],
        )
    )
    r = client.get(
        "/echo",
        headers={
            "Authorization": "Bearer abc",
            "Host": "mcp.asquaredhome.com",
            "Origin": "https://claude.ai",
        },
    )
    assert r.status_code == 200


def test_unmatched_origin_still_rejected_for_localhost():
    client = TestClient(
        _build_app(
            {"abc": "claude-web"},
            allowed_origins=["https://mcp.asquaredhome.com", "http://localhost:8765"],
        )
    )
    r = client.get(
        "/echo",
        headers={
            "Authorization": "Bearer abc",
            "Host": "localhost:8765",
            "Origin": "https://attacker.example.com",
        },
    )
    assert r.status_code == 403


def test_no_origin_header_passes_through():
    """CLI / curl / non-browser clients have no Origin and must pass."""
    client = TestClient(
        _build_app(
            {"abc": "claude-web"},
            allowed_origins=["https://mcp.asquaredhome.com"],
        )
    )
    r = client.get("/echo", headers={"Authorization": "Bearer abc"})
    assert r.status_code == 200


def test_agent_id_propagates_to_scope_top_level():
    """BearerTokenMiddleware must write agent_id to scope['agent_id'] so pure-ASGI
    middlewares see it."""
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    seen: dict = {}

    async def grab(request: Request):
        seen["scope_agent"] = request.scope.get(AGENT_ID_STATE_KEY)
        return PlainTextResponse("ok")

    app = Starlette(
        routes=[Route("/grab", grab)],
        middleware=[Middleware(BearerTokenMiddleware, token_map={"abc": "claude-web"})],
    )
    client = TestClient(app)
    client.get("/grab", headers={"Authorization": "Bearer abc"})
    assert seen["scope_agent"] == "claude-web"


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
