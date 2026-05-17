"""CLI tests."""

from __future__ import annotations

import json

from click.testing import CliRunner

from asquared_mcp.cli import main as cli
from asquared_mcp.store import post_message


def test_read_default_outputs_recent(temp_db, monkeypatch):
    monkeypatch.setenv("COORD_DB_PATH", temp_db)
    post_message(temp_db, "codex", "alex", "note", json.dumps({"text": "hi"}), None)
    runner = CliRunner()
    r = runner.invoke(cli, ["read", "--as-agent", "alex"])
    assert r.exit_code == 0
    assert "codex" in r.output
    assert "note" in r.output


def test_read_filters_by_thread(temp_db, monkeypatch):
    monkeypatch.setenv("COORD_DB_PATH", temp_db)
    post_message(temp_db, "codex", "alex", "note", "{}", "thr-A")
    post_message(temp_db, "codex", "alex", "note", "{}", "thr-B")
    runner = CliRunner()
    r = runner.invoke(cli, ["read", "--as-agent", "alex", "--thread", "thr-A"])
    assert r.exit_code == 0
    assert "thr-A" in r.output
    assert "thr-B" not in r.output


def test_post_inserts_row(temp_db, monkeypatch):
    monkeypatch.setenv("COORD_DB_PATH", temp_db)
    runner = CliRunner()
    r = runner.invoke(
        cli,
        [
            "post",
            "--from-agent",
            "alex",
            "--to",
            "claude-code",
            "--kind",
            "answer",
            "--text",
            "go ahead",
        ],
    )
    assert r.exit_code == 0
    # Verify via direct DB read
    from asquared_mcp.store import read_messages

    rows = read_messages(temp_db, to_agent="claude-code")
    assert any(r_["from_agent"] == "alex" for r_ in rows)
