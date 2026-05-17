"""Direct unit tests on the tool functions (contextvars set manually)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from asquared_mcp.models import (
    MAX_PAYLOAD_BYTES,
    CoordAckInput,
    CoordPostInput,
    CoordReadInput,
    CoordStatusInput,
    CoordThreadsInput,
)
from asquared_mcp.server import _current_agent, build_app, build_mcp
from asquared_mcp.store import get_message


@pytest.fixture
def mcp_with_config(temp_config):
    return build_mcp(temp_config), temp_config


def _set_agent(agent_id: str):
    return _current_agent.set(agent_id)


def _get_tool(mcp, name):
    """Resolve a tool by name from the FastMCP instance.

    FastMCP stores tools internally; this peeks at its registry. If the
    SDK's internal API changes, swap to `mcp._tool_manager.get_tool(name)`
    or whatever the current accessor is — verify with introspection.
    """
    return mcp._tool_manager._tools[name].fn  # internal; acceptable for unit tests


@pytest.mark.asyncio
async def test_coord_post_inserts_and_returns_id(mcp_with_config):
    mcp, _ = mcp_with_config
    token = _set_agent("claude-code")
    try:
        result = await _get_tool(mcp, "coord_post")(
            CoordPostInput(to_agent="alex", kind="note", payload={"text": "hi"}),
            ctx=None,  # not used by handler
        )
        assert result["message_id"] > 0
        assert result["from_agent"] == "claude-code"
    finally:
        _current_agent.reset(token)


@pytest.mark.asyncio
async def test_coord_post_stop_and_ask_triggers_dry_run_notify(mcp_with_config):
    mcp, cfg = mcp_with_config
    token = _set_agent("codex")
    try:
        result = await _get_tool(mcp, "coord_post")(
            CoordPostInput(to_agent="alex", kind="stop_and_ask", payload={"question": "go?"}),
            ctx=None,
        )
        # Dry-run config: notified=False but reason indicates the rule fired
        assert result["notified"] is False
        assert result["notification_reason"] == "dry_run"
        row = get_message(cfg.server.db_path, result["message_id"])
        assert row["notified_at"] is not None
        assert row["notification_error"] == "dry_run"
    finally:
        _current_agent.reset(token)


@pytest.mark.asyncio
async def test_coord_read_returns_shared_queue(mcp_with_config):
    mcp, _ = mcp_with_config
    # codex posts: one to alex, one to broadcast, one to claude-web
    poster = _set_agent("codex")
    try:
        for to in ("alex", "broadcast", "claude-web"):
            await _get_tool(mcp, "coord_post")(
                CoordPostInput(to_agent=to, kind="note", payload={}),
                ctx=None,
            )
    finally:
        _current_agent.reset(poster)
    # alex reads
    reader = _set_agent("alex")
    try:
        result = await _get_tool(mcp, "coord_read")(CoordReadInput(), ctx=None)
        targets = [m["to_agent"] for m in result["messages"]]
        assert "alex" in targets
        assert "broadcast" in targets
        assert "claude-web" in targets
    finally:
        _current_agent.reset(reader)


@pytest.mark.asyncio
async def test_coord_threads_create_then_list_then_close(mcp_with_config):
    mcp, _ = mcp_with_config
    token = _set_agent("codex")
    try:
        created = await _get_tool(mcp, "coord_threads")(
            CoordThreadsInput(action="create", title="wave A"),
            ctx=None,
        )
        tid = created["thread_id"]
        listed = await _get_tool(mcp, "coord_threads")(
            CoordThreadsInput(action="list"),
            ctx=None,
        )
        assert any(t["id"] == tid for t in listed["threads"])
        await _get_tool(mcp, "coord_threads")(
            CoordThreadsInput(action="close", thread_id=tid),
            ctx=None,
        )
        listed_after = await _get_tool(mcp, "coord_threads")(
            CoordThreadsInput(action="list", include_closed=False),
            ctx=None,
        )
        assert all(t["id"] != tid for t in listed_after["threads"])
    finally:
        _current_agent.reset(token)


@pytest.mark.asyncio
async def test_coord_ack_idempotent(mcp_with_config):
    mcp, cfg = mcp_with_config
    poster = _set_agent("codex")
    try:
        posted = await _get_tool(mcp, "coord_post")(
            CoordPostInput(to_agent="alex", kind="note", payload={}),
            ctx=None,
        )
    finally:
        _current_agent.reset(poster)
    reader = _set_agent("alex")
    try:
        ack_input = CoordAckInput(message_ids=[posted["message_id"]])
        await _get_tool(mcp, "coord_ack")(ack_input, ctx=None)
        await _get_tool(mcp, "coord_ack")(ack_input, ctx=None)
        row = get_message(cfg.server.db_path, posted["message_id"])
        assert json.loads(row["read_by"]).count("alex") == 1
    finally:
        _current_agent.reset(reader)


@pytest.mark.asyncio
async def test_coord_status_posts_to_broadcast_no_notify(mcp_with_config):
    mcp, cfg = mcp_with_config
    token = _set_agent("claude-code")
    try:
        result = await _get_tool(mcp, "coord_status")(
            CoordStatusInput(summary="working on auth packet"),
            ctx=None,
        )
        row = get_message(cfg.server.db_path, result["message_id"])
        assert row["to_agent"] == "broadcast"
        assert row["kind"] == "status"
        assert row["notified_at"] is None  # status never notifies
    finally:
        _current_agent.reset(token)


def test_health_endpoint_returns_ok(temp_config):
    app = build_app(temp_config)
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_mcp_endpoint_requires_auth(temp_config):
    app = build_app(temp_config)
    client = TestClient(app)
    r = client.post("/mcp", json={})
    assert r.status_code == 401


def test_mcp_endpoint_accepts_initialize_at_documented_path(temp_config):
    app = build_app(temp_config)
    with TestClient(app, base_url="http://localhost:8765") as client:
        r = client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer test-token-codex",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "0"},
                },
            },
        )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith(("application/json", "text/event-stream"))


def test_mcp_endpoint_allows_hosted_origin_through_public_host(temp_config):
    app = build_app(temp_config)
    with TestClient(app, base_url="https://mcp.asquaredhome.com") as client:
        r = client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer test-token-codex",
                "Accept": "application/json, text/event-stream",
                "Origin": "https://claude.ai",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "0"},
                },
            },
        )
    assert r.status_code == 200


def test_tool_annotations_are_security_accurate(temp_config):
    mcp = build_mcp(temp_config)
    assert mcp._tool_manager._tools["coord_read"].annotations.readOnlyHint is True
    assert mcp._tool_manager._tools["coord_post"].annotations.readOnlyHint is False
    assert mcp._tool_manager._tools["coord_ack"].annotations.readOnlyHint is False
    assert mcp._tool_manager._tools["coord_status"].annotations.readOnlyHint is False
    assert mcp._tool_manager._tools["coord_threads"].annotations.destructiveHint is True


def test_coord_post_payload_rejects_over_64kb():
    payload = {"text": "x" * MAX_PAYLOAD_BYTES}
    with pytest.raises(ValidationError, match="payload serialized JSON"):
        CoordPostInput(to_agent="alex", kind="note", payload=payload)


def test_thread_id_rejects_long_or_unsafe_values():
    with pytest.raises(ValidationError):
        CoordPostInput(to_agent="alex", kind="note", payload={}, thread_id="bad/thread")
    with pytest.raises(ValidationError):
        CoordStatusInput(summary="ok", thread_id="t" * 201)


def test_coord_read_limit_is_schema_capped():
    with pytest.raises(ValidationError):
        CoordReadInput(limit=201)


def test_coord_threads_title_is_capped():
    with pytest.raises(ValidationError):
        CoordThreadsInput(action="create", title="x" * 201)
