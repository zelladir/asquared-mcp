"""Notification module tests."""

from __future__ import annotations

import json

import pytest

from asquared_mcp.config import Config, PushoverConfig, ServerConfig
from asquared_mcp.notify import PUSHOVER_URL, maybe_notify, rule_matches
from asquared_mcp.store import get_message, post_message


@pytest.fixture
def dry_run_config(temp_db):
    return Config(
        server=ServerConfig(port=8765, db_path=temp_db),
        tokens={},
        pushover=PushoverConfig(dry_run=True, user_key="", app_token=""),
        allowed_origins=[],
    )


def test_rule_matches_stop_and_ask_to_anyone():
    assert rule_matches(kind="stop_and_ask", to_agent="claude-web") is True
    assert rule_matches(kind="stop_and_ask", to_agent="alex") is True


def test_rule_matches_handoff_only_to_alex():
    assert rule_matches(kind="handoff", to_agent="alex") is True
    assert rule_matches(kind="handoff", to_agent="claude-web") is False


def test_rule_matches_status_never():
    assert rule_matches(kind="status", to_agent="alex") is False


@pytest.mark.asyncio
async def test_maybe_notify_dry_run_marks_notified_without_http(temp_db, dry_run_config):
    msg_id = post_message(
        temp_db, "codex", "alex", "stop_and_ask", json.dumps({"text": "ping"}), None
    )
    result = await maybe_notify(dry_run_config, msg_id)
    assert result.notified is False
    assert result.reason == "dry_run"
    row = get_message(temp_db, msg_id)
    assert row["notified_at"] is not None
    assert row["notification_error"] == "dry_run"


@pytest.mark.asyncio
async def test_maybe_notify_skips_already_notified(temp_db, dry_run_config):
    msg_id = post_message(temp_db, "codex", "alex", "stop_and_ask", "{}", None)
    await maybe_notify(dry_run_config, msg_id)  # first call sets notified_at
    result = await maybe_notify(dry_run_config, msg_id)
    assert result.reason == "already_notified"


@pytest.mark.asyncio
async def test_maybe_notify_skips_rule_mismatch(temp_db, dry_run_config):
    msg_id = post_message(temp_db, "codex", "claude-web", "status", "{}", None)
    result = await maybe_notify(dry_run_config, msg_id)
    assert result.reason == "rule_not_matched"
    row = get_message(temp_db, msg_id)
    assert row["notified_at"] is None  # left untouched


@pytest.fixture
def live_config(temp_db):
    return Config(
        server=ServerConfig(port=8765, db_path=temp_db),
        tokens={},
        pushover=PushoverConfig(dry_run=False, user_key="u-test", app_token="a-test"),
        allowed_origins=[],
    )


@pytest.mark.asyncio
async def test_maybe_notify_posts_to_pushover_with_priority_1_for_stop_and_ask(
    temp_db,
    live_config,
    httpx_mock,
):
    httpx_mock.add_response(
        method="POST",
        url=PUSHOVER_URL,
        json={"status": 1, "request": "abc"},
        status_code=200,
    )
    msg_id = post_message(
        temp_db,
        "codex",
        "alex",
        "stop_and_ask",
        json.dumps({"question": "approve plan?"}),
        None,
    )
    result = await maybe_notify(live_config, msg_id)
    assert result.notified is True
    assert result.error is None

    sent = httpx_mock.get_request()
    assert sent is not None
    body = dict(kv.split("=", 1) for kv in sent.content.decode().split("&"))
    # urlencoded — pytest-httpx exposes raw bytes; we decode and split.
    assert body["token"] == "a-test"
    assert body["user"] == "u-test"
    assert body["priority"] == "1"


@pytest.mark.asyncio
async def test_maybe_notify_uses_priority_0_for_handoff_to_alex(
    temp_db,
    live_config,
    httpx_mock,
):
    httpx_mock.add_response(
        method="POST", url=PUSHOVER_URL, json={"status": 1, "request": "x"}, status_code=200
    )
    msg_id = post_message(temp_db, "codex", "alex", "handoff", "{}", None)
    result = await maybe_notify(live_config, msg_id)
    assert result.notified is True
    sent = httpx_mock.get_request()
    body = dict(kv.split("=", 1) for kv in sent.content.decode().split("&"))
    assert body["priority"] == "0"


@pytest.mark.asyncio
async def test_maybe_notify_marks_notified_on_4xx_to_prevent_retry_loop(
    temp_db,
    live_config,
    httpx_mock,
):
    httpx_mock.add_response(
        method="POST",
        url=PUSHOVER_URL,
        status_code=400,
        json={"status": 0, "errors": ["bad request"]},
    )
    msg_id = post_message(temp_db, "codex", "alex", "stop_and_ask", "{}", None)
    result = await maybe_notify(live_config, msg_id)
    assert result.notified is False
    assert result.error == "pushover_http_400"
    row = get_message(temp_db, msg_id)
    assert row["notified_at"] is not None  # set so we don't retry
    assert row["notification_error"] == "pushover_http_400"


@pytest.mark.asyncio
async def test_maybe_notify_does_not_store_pushover_error_body(
    temp_db,
    live_config,
    httpx_mock,
):
    httpx_mock.add_response(
        method="POST",
        url=PUSHOVER_URL,
        status_code=400,
        json={"status": 0, "errors": ["user u-test is invalid"]},
    )
    msg_id = post_message(temp_db, "codex", "alex", "stop_and_ask", "{}", None)
    result = await maybe_notify(live_config, msg_id)
    row = get_message(temp_db, msg_id)
    assert result.error == "pushover_http_400"
    assert "u-test" not in (row["notification_error"] or "")


@pytest.mark.asyncio
async def test_maybe_notify_treats_status_zero_as_failure(
    temp_db,
    live_config,
    httpx_mock,
):
    httpx_mock.add_response(
        method="POST",
        url=PUSHOVER_URL,
        status_code=200,
        json={"status": 0, "errors": ["bad user"]},
    )
    msg_id = post_message(temp_db, "codex", "alex", "stop_and_ask", "{}", None)
    result = await maybe_notify(live_config, msg_id)
    assert result.notified is False
    assert result.error == "pushover_status_not_1"


@pytest.mark.asyncio
async def test_format_body_truncates_at_1024_chars():
    from asquared_mcp.notify import _format_body

    long = json.dumps({"text": "x" * 2000})
    out = _format_body(long)
    assert len(out) == 1024
    assert out.endswith("[truncated]")


@pytest.mark.asyncio
async def test_format_body_prefers_text_field():
    from asquared_mcp.notify import _format_body

    out = _format_body(json.dumps({"text": "hello", "extra": "ignored"}))
    assert out == "hello"


def test_format_body_handles_non_dict_payload():
    from asquared_mcp.notify import _format_body

    out = _format_body(json.dumps(["a", "b", "c"]))
    # falls through to json.dumps with indent
    assert "[" in out
    assert "]" in out


def test_format_body_handles_invalid_json_payload():
    from asquared_mcp.notify import _format_body

    out = _format_body("not-json-at-all")
    assert out == "not-json-at-all"
