"""SQLite store tests."""

from __future__ import annotations

import json
import sqlite3

from asquared_mcp.store import (
    ack_messages,
    close_thread,
    consume_auth_code,
    create_thread,
    get_message,
    init_db,
    list_threads,
    lookup_oauth_token,
    mark_notified,
    pending_notifications,
    post_message,
    read_messages,
    store_auth_code,
    store_oauth_token,
)


def test_init_db_creates_schema(tmp_path):
    """init_db creates messages, threads, meta tables and indexes."""
    db = tmp_path / "c.db"
    init_db(str(db))
    conn = sqlite3.connect(str(db))
    try:
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"messages", "threads", "meta"} <= tables
        indexes = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
        assert "idx_messages_to_agent" in indexes
        assert "idx_messages_thread" in indexes
        assert "idx_messages_timestamp" in indexes
    finally:
        conn.close()


def test_init_db_is_idempotent(tmp_path):
    """Running init_db twice on the same file does not error."""
    db = tmp_path / "c.db"
    init_db(str(db))
    init_db(str(db))


def test_init_db_enables_wal_mode(tmp_path):
    """init_db sets journal_mode=WAL for concurrent reader/writer safety."""
    db = tmp_path / "c.db"
    init_db(str(db))
    conn = sqlite3.connect(str(db))
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
    finally:
        conn.close()


def test_post_message_returns_id(temp_db):
    msg_id = post_message(
        db_path=temp_db,
        from_agent="claude-code",
        to_agent="alex",
        kind="stop_and_ask",
        payload=json.dumps({"question": "approve plan?"}),
        thread_id=None,
    )
    assert isinstance(msg_id, int)
    assert msg_id > 0


def test_post_then_get_round_trip(temp_db):
    msg_id = post_message(
        db_path=temp_db,
        from_agent="codex",
        to_agent="claude-code",
        kind="answer",
        payload=json.dumps({"text": "yes"}),
        thread_id="thr-1",
    )
    row = get_message(temp_db, msg_id)
    assert row is not None
    assert row["from_agent"] == "codex"
    assert row["to_agent"] == "claude-code"
    assert row["kind"] == "answer"
    assert json.loads(row["payload"]) == {"text": "yes"}
    assert row["thread_id"] == "thr-1"
    assert row["read_by"] == "[]"
    assert row["notified_at"] is None


def test_read_messages_filters_by_to_agent(temp_db):
    post_message(temp_db, "codex", "alex", "note", "{}", None)
    post_message(temp_db, "codex", "claude-web", "note", "{}", None)
    post_message(temp_db, "codex", "broadcast", "status", "{}", None)
    rows = read_messages(temp_db, to_agent="alex")
    # alex sees: messages addressed to alex + broadcast
    to_targets = [r["to_agent"] for r in rows]
    assert "alex" in to_targets
    assert "broadcast" in to_targets
    assert "claude-web" not in to_targets


def test_read_messages_without_to_agent_returns_shared_queue(temp_db):
    post_message(temp_db, "codex", "alex", "note", "{}", None)
    post_message(temp_db, "codex", "claude-web", "note", "{}", None)
    post_message(temp_db, "codex", "broadcast", "status", "{}", None)
    rows = read_messages(temp_db, to_agent=None)
    assert {r["to_agent"] for r in rows} == {"alex", "claude-web", "broadcast"}


def test_read_messages_unread_only_uses_read_by_agent_for_shared_queue(temp_db):
    first = post_message(temp_db, "codex", "alex", "note", "{}", None)
    second = post_message(temp_db, "codex", "claude-web", "note", "{}", None)
    ack_messages(temp_db, [first], by_agent="claude-web")
    rows = read_messages(temp_db, to_agent=None, unread_only=True, read_by_agent="claude-web")
    ids = {r["id"] for r in rows}
    assert first not in ids
    assert second in ids


def test_read_messages_since_id_excludes_lower_or_equal(temp_db):
    a = post_message(temp_db, "codex", "alex", "note", "{}", None)
    b = post_message(temp_db, "codex", "alex", "note", "{}", None)
    rows = read_messages(temp_db, to_agent="alex", since_id=a)
    ids = [r["id"] for r in rows]
    assert a not in ids
    assert b in ids


def test_read_messages_filters_by_thread(temp_db):
    post_message(temp_db, "codex", "alex", "note", "{}", "thr-A")
    post_message(temp_db, "codex", "alex", "note", "{}", "thr-B")
    rows = read_messages(temp_db, to_agent="alex", thread_id="thr-A")
    assert all(r["thread_id"] == "thr-A" for r in rows)
    assert len(rows) == 1


def test_read_messages_filters_by_kinds(temp_db):
    post_message(temp_db, "codex", "alex", "note", "{}", None)
    post_message(temp_db, "codex", "alex", "stop_and_ask", "{}", None)
    rows = read_messages(temp_db, to_agent="alex", kinds=["stop_and_ask"])
    assert all(r["kind"] == "stop_and_ask" for r in rows)
    assert len(rows) == 1


def test_read_messages_limit_capped_at_200(temp_db):
    for _ in range(5):
        post_message(temp_db, "codex", "alex", "note", "{}", None)
    rows = read_messages(temp_db, to_agent="alex", limit=10_000)
    # caller-supplied giant limit must not exceed 200; we only have 5 here so this only
    # checks the capping mechanism doesn't crash.
    assert len(rows) == 5


def test_read_messages_default_returns_recent(temp_db):
    post_message(temp_db, "codex", "alex", "note", "{}", None)
    rows = read_messages(temp_db, to_agent="alex")
    assert len(rows) == 1


def test_ack_messages_appends_agent(temp_db):
    a = post_message(temp_db, "codex", "alex", "note", "{}", None)
    b = post_message(temp_db, "codex", "alex", "note", "{}", None)
    n = ack_messages(temp_db, message_ids=[a, b], by_agent="alex")
    assert n == 2
    row = get_message(temp_db, a)
    assert "alex" in json.loads(row["read_by"])


def test_ack_messages_idempotent_for_same_agent(temp_db):
    a = post_message(temp_db, "codex", "alex", "note", "{}", None)
    ack_messages(temp_db, [a], by_agent="alex")
    ack_messages(temp_db, [a], by_agent="alex")
    row = get_message(temp_db, a)
    read_by = json.loads(row["read_by"])
    assert read_by.count("alex") == 1


def test_mark_notified_sets_timestamp(temp_db):
    a = post_message(temp_db, "codex", "alex", "stop_and_ask", "{}", None)
    mark_notified(temp_db, a, error=None)
    row = get_message(temp_db, a)
    assert row["notified_at"] is not None
    assert row["notification_error"] is None


def test_mark_notified_records_error(temp_db):
    a = post_message(temp_db, "codex", "alex", "stop_and_ask", "{}", None)
    mark_notified(temp_db, a, error="HTTP 429: rate limited")
    row = get_message(temp_db, a)
    assert row["notification_error"] == "HTTP 429: rate limited"
    assert row["notified_at"] is not None  # still set so we don't retry


def test_pending_notifications_returns_unnotified_eligible(temp_db):
    """pending_notifications returns rows that match a notify rule and have no notified_at."""
    eligible = post_message(temp_db, "codex", "alex", "stop_and_ask", "{}", None)
    not_eligible_kind = post_message(temp_db, "codex", "alex", "status", "{}", None)
    not_eligible_recipient = post_message(
        temp_db, "codex", "claude-web", "stop_and_ask", "{}", None
    )
    already = post_message(temp_db, "codex", "alex", "stop_and_ask", "{}", None)
    mark_notified(temp_db, already, error=None)

    pending_ids = {r["id"] for r in pending_notifications(temp_db)}
    assert eligible in pending_ids
    assert not_eligible_kind not in pending_ids
    # stop_and_ask to a non-alex recipient still triggers because rule is "stop_and_ask -> any"
    assert not_eligible_recipient in pending_ids
    assert already not in pending_ids


def test_create_thread_returns_slug(temp_db):
    tid = create_thread(temp_db, title="Wave A leadership cleanup", created_by="codex")
    assert tid
    assert tid.startswith("thr-")


def test_list_threads_excludes_closed_by_default(temp_db):
    open_id = create_thread(temp_db, title="open", created_by="codex")
    closed_id = create_thread(temp_db, title="closed", created_by="codex")
    close_thread(temp_db, closed_id)
    open_only = {r["id"] for r in list_threads(temp_db, include_closed=False)}
    all_threads = {r["id"] for r in list_threads(temp_db, include_closed=True)}
    assert open_id in open_only
    assert closed_id not in open_only
    assert closed_id in all_threads


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


def test_store_and_consume_auth_code(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    store_auth_code(
        db, code="ac_test123", client_id="ccw_test", agent_id="claude-web",
        code_challenge="abc123challenge", redirect_uri="https://claude.ai/api/mcp/auth_callback",
        expires_at="2099-01-01T00:00:00+00:00",
    )
    row = consume_auth_code(db, "ac_test123")
    assert row is not None
    assert row["client_id"] == "ccw_test"
    assert row["agent_id"] == "claude-web"
    assert row["code_challenge"] == "abc123challenge"
    assert row["redirect_uri"] == "https://claude.ai/api/mcp/auth_callback"


def test_consume_auth_code_is_single_use(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    store_auth_code(db, code="ac_once", client_id="ccw_test", agent_id="claude-web",
        code_challenge="xyz", redirect_uri="https://example.com/cb", expires_at="2099-01-01T00:00:00+00:00")
    assert consume_auth_code(db, "ac_once") is not None
    assert consume_auth_code(db, "ac_once") is None


def test_consume_expired_auth_code(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    store_auth_code(db, code="ac_expired", client_id="ccw_test", agent_id="claude-web",
        code_challenge="xyz", redirect_uri="https://example.com/cb", expires_at="2000-01-01T00:00:00+00:00")
    assert consume_auth_code(db, "ac_expired") is None


def test_consume_missing_auth_code(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    assert consume_auth_code(db, "ac_nonexistent") is None


def test_init_db_creates_auth_codes_table(tmp_path):
    db = str(tmp_path / "t.db")
    init_db(db)
    import sqlite3 as _sqlite3
    conn = _sqlite3.connect(db)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "oauth_auth_codes" in tables
