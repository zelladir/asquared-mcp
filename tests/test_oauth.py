"""OAuth 2.0 client credentials route tests."""

from __future__ import annotations

import base64
import hashlib
import secrets

import pytest
from starlette.testclient import TestClient

from asquared_mcp.config import Config, OAuthClientConfig, OAuthConfig, PushoverConfig, ServerConfig
from asquared_mcp.server import build_app
from asquared_mcp.store import init_db


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
    assert data["authorization_endpoint"] == "https://mcp.asquaredhome.com/authorize"
    assert "client_credentials" in data["grant_types_supported"]


def test_discovery_requires_no_auth(oauth_config):
    client = TestClient(build_app(oauth_config))
    assert client.get("/.well-known/oauth-protected-resource").status_code == 200
    assert client.get("/.well-known/oauth-authorization-server").status_code == 200


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
        "grant_type": "password",
        "client_id": "ccw_testclient",
        "client_secret": "ccs_testsecret",
    })
    assert r.status_code == 400
    assert r.json()["error"] == "unsupported_grant_type"


def test_token_endpoint_requires_no_auth(oauth_config):
    client = TestClient(build_app(oauth_config))
    r = client.post("/token", data={
        "grant_type": "client_credentials",
        "client_id": "ccw_testclient",
        "client_secret": "ccs_testsecret",
    })
    assert r.status_code != 401


def test_register_returns_400(oauth_config):
    client = TestClient(build_app(oauth_config))
    r = client.post("/register", json={"client_name": "some-connector"})
    assert r.status_code == 400
    assert r.json()["error"] == "registration_not_supported"


def test_oauth_token_authenticates_on_mcp(oauth_config):
    # raise_server_exceptions=False: the MCP session manager raises RuntimeError
    # when the lifespan task group is not running (TestClient without lifespan).
    # That becomes a 500, not a 401 — auth passed.
    client = TestClient(build_app(oauth_config), raise_server_exceptions=False)
    r = client.post("/token", data={
        "grant_type": "client_credentials",
        "client_id": "ccw_testclient",
        "client_secret": "ccs_testsecret",
    })
    assert r.status_code == 200
    token = r.json()["access_token"]
    r2 = client.post("/mcp", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code != 401, f"Expected auth to pass, got 401. Token: {token}"


def test_static_bearer_token_still_works(oauth_config):
    client = TestClient(build_app(oauth_config), raise_server_exceptions=False)
    assert client.get("/health").status_code == 200
    r2 = client.post("/mcp", headers={"Authorization": "Bearer static-tok-cc"})
    assert r2.status_code != 401


def _pkce_pair() -> tuple[str, str]:
    """Generate a (code_verifier, code_challenge) PKCE pair."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def test_authorize_redirects_to_callback(oauth_config):
    client = TestClient(build_app(oauth_config), follow_redirects=False)
    verifier, challenge = _pkce_pair()
    r = client.get("/authorize", params={
        "response_type": "code",
        "client_id": "ccw_testclient",
        "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "test_state_xyz",
    })
    assert r.status_code == 302
    location = r.headers["location"]
    assert location.startswith("https://claude.ai/api/mcp/auth_callback")
    assert "code=" in location
    assert "state=test_state_xyz" in location


def test_authorize_unknown_client(oauth_config):
    client = TestClient(build_app(oauth_config), follow_redirects=False)
    _, challenge = _pkce_pair()
    r = client.get("/authorize", params={
        "response_type": "code", "client_id": "ccw_unknown",
        "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "s",
    })
    assert r.status_code == 400


def test_authorize_missing_pkce(oauth_config):
    client = TestClient(build_app(oauth_config), follow_redirects=False)
    r = client.get("/authorize", params={
        "response_type": "code", "client_id": "ccw_testclient",
        "redirect_uri": "https://claude.ai/api/mcp/auth_callback", "state": "s",
    })
    assert r.status_code == 400


def test_full_authcode_flow(oauth_config):
    """Complete authorization code + PKCE exchange produces a working access token."""
    from urllib.parse import parse_qs, urlparse
    client = TestClient(build_app(oauth_config), follow_redirects=False, raise_server_exceptions=False)
    verifier, challenge = _pkce_pair()

    r = client.get("/authorize", params={
        "response_type": "code", "client_id": "ccw_testclient",
        "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "mystate",
    })
    assert r.status_code == 302
    parsed = urlparse(r.headers["location"])
    params = parse_qs(parsed.query)
    code = params["code"][0]
    assert params["state"][0] == "mystate"

    r2 = client.post("/token", data={
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
        "client_id": "ccw_testclient", "code_verifier": verifier,
    })
    assert r2.status_code == 200
    data = r2.json()
    assert data["access_token"].startswith("oat_")
    assert data["token_type"] == "Bearer"

    r3 = client.post("/mcp", headers={"Authorization": f"Bearer {data['access_token']}"})
    assert r3.status_code != 401


def test_authcode_is_single_use(oauth_config):
    from urllib.parse import parse_qs, urlparse
    client = TestClient(build_app(oauth_config), follow_redirects=False)
    verifier, challenge = _pkce_pair()
    r = client.get("/authorize", params={
        "response_type": "code", "client_id": "ccw_testclient",
        "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "s",
    })
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]

    r2 = client.post("/token", data={
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
        "client_id": "ccw_testclient", "code_verifier": verifier,
    })
    assert r2.status_code == 200

    r3 = client.post("/token", data={
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
        "client_id": "ccw_testclient", "code_verifier": verifier,
    })
    assert r3.status_code == 400
    assert r3.json()["error"] == "invalid_grant"


def test_token_wrong_code_verifier(oauth_config):
    from urllib.parse import parse_qs, urlparse
    client = TestClient(build_app(oauth_config), follow_redirects=False)
    _, challenge = _pkce_pair()
    r = client.get("/authorize", params={
        "response_type": "code", "client_id": "ccw_testclient",
        "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "s",
    })
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]

    r2 = client.post("/token", data={
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
        "client_id": "ccw_testclient", "code_verifier": "wrong_verifier_value",
    })
    assert r2.status_code == 400
    assert r2.json()["error"] == "invalid_grant"


def test_discovery_includes_authorize_endpoint(oauth_config):
    client = TestClient(build_app(oauth_config))
    r = client.get("/.well-known/oauth-authorization-server")
    data = r.json()
    assert "authorization_endpoint" in data
    assert data["authorization_endpoint"].endswith("/authorize")
    assert "S256" in data.get("code_challenge_methods_supported", [])
    assert "authorization_code" in data["grant_types_supported"]
