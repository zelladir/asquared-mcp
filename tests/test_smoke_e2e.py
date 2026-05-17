"""End-to-end round-trip: post stop_and_ask -> notify fires -> read as another agent -> ack
-> reply."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from asquared_mcp.config import Config, PushoverConfig, ServerConfig
from asquared_mcp.models import (
    CoordAckInput,
    CoordPostInput,
    CoordReadInput,
)
from asquared_mcp.notify import PUSHOVER_URL
from asquared_mcp.server import _current_agent, build_app, build_mcp
from asquared_mcp.store import init_db


@pytest.fixture
def live_config(tmp_path):
    db = tmp_path / "smoke.db"
    init_db(str(db))
    return Config(
        server=ServerConfig(port=8765, db_path=str(db)),
        tokens={
            "tok-cw": "claude-web",
            "tok-cc": "claude-code",
            "tok-cx": "codex",
        },
        pushover=PushoverConfig(dry_run=False, user_key="u-test", app_token="a-test"),
        allowed_origins=["http://testserver", "https://mcp.asquaredhome.com"],
    )


def test_health_open(live_config):
    client = TestClient(build_app(live_config))
    assert client.get("/health").status_code == 200


def test_mcp_endpoint_401_unauth(live_config):
    client = TestClient(build_app(live_config))
    assert client.post("/mcp").status_code == 401


def test_mcp_endpoint_401_bad_token(live_config):
    client = TestClient(build_app(live_config))
    r = client.post("/mcp", headers={"Authorization": "Bearer not-a-token"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_full_round_trip_with_real_notify(live_config, httpx_mock):
    """codex posts stop_and_ask to alex -> Pushover fires -> claude-web reads -> acks -> answers."""
    httpx_mock.add_response(
        method="POST",
        url=PUSHOVER_URL,
        json={"status": 1, "request": "ok"},
        status_code=200,
    )
    mcp = build_mcp(live_config)
    posted_id: int | None = None

    # 1) codex posts a stop_and_ask to alex
    token = _current_agent.set("codex")
    try:
        post_fn = mcp._tool_manager._tools["coord_post"].fn
        result = await post_fn(
            CoordPostInput(
                to_agent="alex",
                kind="stop_and_ask",
                payload={"question": "approve registry change?"},
            ),
            ctx=None,
        )
        posted_id = result["message_id"]
        assert result["notified"] is True, f"expected real notify; got {result}"
    finally:
        _current_agent.reset(token)

    # Verify Pushover was called once with priority=1
    pushover_request = httpx_mock.get_request()
    assert pushover_request is not None
    body = dict(kv.split("=", 1) for kv in pushover_request.content.decode().split("&"))
    assert body["priority"] == "1"

    # 2) claude-web reads the shared queue and sees the message addressed to alex.
    token = _current_agent.set("claude-web")
    try:
        read_fn = mcp._tool_manager._tools["coord_read"].fn
        result = await read_fn(CoordReadInput(), ctx=None)
        assert any(m["id"] == posted_id for m in result["messages"]), (
            f"expected posted message in alex's queue; got {result}"
        )
    finally:
        _current_agent.reset(token)

    # 3) ack as claude-web
    token = _current_agent.set("claude-web")
    try:
        ack_fn = mcp._tool_manager._tools["coord_ack"].fn
        ack_result = await ack_fn(CoordAckInput(message_ids=[posted_id]), ctx=None)
        assert ack_result["acked"] == 1
    finally:
        _current_agent.reset(token)

    # 4) claude-web posts an answer back to codex (acting on alex's behalf in chat)
    token = _current_agent.set("claude-web")
    try:
        post_fn = mcp._tool_manager._tools["coord_post"].fn
        reply = await post_fn(
            CoordPostInput(
                to_agent="codex",
                kind="answer",
                payload={"text": "approved"},
            ),
            ctx=None,
        )
        # answer kind doesn't trigger a notify
        assert reply["notified"] is False
        assert reply["notification_reason"] == "rule_not_matched"
    finally:
        _current_agent.reset(token)

    # 5) verify codex would see the reply
    token = _current_agent.set("codex")
    try:
        result = await read_fn(CoordReadInput(kinds=["answer"]), ctx=None)
        assert any(m["payload"]["text"] == "approved" for m in result["messages"])
    finally:
        _current_agent.reset(token)
