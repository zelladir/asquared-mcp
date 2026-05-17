"""coord-cli: admin tool that reads and posts directly to the SQLite store."""

from __future__ import annotations

import json
import os
import time
from typing import Any

import click
from rich.console import Console
from rich.table import Table

from .store import (
    create_thread,
    list_threads,
    post_message,
    read_messages,
)

DEFAULT_DB = "./data/coord.db"


def _db_path() -> str:
    return os.environ.get("COORD_DB_PATH", DEFAULT_DB)


def _render_messages(rows: list[Any]) -> None:
    console = Console()
    table = Table(show_header=True, header_style="bold")
    table.add_column("id", justify="right", width=6)
    table.add_column("ts")
    table.add_column("from", width=12)
    table.add_column("to", width=12)
    table.add_column("thread", width=14)
    table.add_column("kind", width=14)
    table.add_column("payload", overflow="fold")
    for r in rows:
        try:
            payload = json.loads(r["payload"])
            payload_str = (
                payload.get("text")
                or payload.get("summary")
                or payload.get("question")
                or json.dumps(payload)
            )
        except Exception:  # any malformed payload falls through to raw
            payload_str = r["payload"]
        table.add_row(
            str(r["id"]),
            r["timestamp"],
            r["from_agent"],
            r["to_agent"],
            r["thread_id"] or "-",
            r["kind"],
            str(payload_str)[:120],
        )
    console.print(table)


@click.group()
def main() -> None:
    """coord-cli: read/post coordination messages from the terminal."""


@main.command()
@click.option("--as-agent", default="alex", help="Read as which agent identity (default: alex).")
@click.option("--since-id", type=int, help="Only messages with id > N.")
@click.option("--thread", "thread_id", help="Filter to one thread.")
@click.option("--kind", "kinds", multiple=True, help="Filter by kind (repeatable).")
@click.option("--unread", is_flag=True, help="Only unread (by --as-agent).")
@click.option("--limit", type=int, default=50)
def read(
    as_agent: str,
    since_id: int | None,
    thread_id: str | None,
    kinds: tuple[str, ...],
    unread: bool,
    limit: int,
) -> None:
    """Read messages from the queue."""
    rows = read_messages(
        db_path=_db_path(),
        to_agent=as_agent,
        since_id=since_id,
        thread_id=thread_id,
        kinds=list(kinds) or None,
        unread_only=unread,
        limit=limit,
    )
    _render_messages(rows)


@main.command()
@click.option("--as-agent", default="alex")
@click.option("--interval", type=float, default=2.0, help="Poll interval (seconds).")
def tail(as_agent: str, interval: float) -> None:
    """Tail the queue, polling for new messages."""
    last_id = 0
    while True:
        rows = read_messages(_db_path(), to_agent=as_agent, since_id=last_id, limit=200)
        if rows:
            _render_messages(rows)
            last_id = max(r["id"] for r in rows)
        time.sleep(interval)


@main.command()
@click.option("--from-agent", required=True, help="Identity to post as.")
@click.option("--to", "to_agent", required=True)
@click.option("--kind", required=True)
@click.option("--text", required=True, help="Free text; stored under payload.text.")
@click.option("--thread", "thread_id", default=None)
def post(from_agent: str, to_agent: str, kind: str, text: str, thread_id: str | None) -> None:
    """Post a message (admin/debug use; bypasses MCP auth)."""
    msg_id = post_message(
        db_path=_db_path(),
        from_agent=from_agent,
        to_agent=to_agent,
        kind=kind,
        payload=json.dumps({"text": text}),
        thread_id=thread_id,
    )
    click.echo(f"posted message_id={msg_id}")


@main.command()
@click.option("--include-closed", is_flag=True)
def threads(include_closed: bool) -> None:
    """List threads."""
    rows = list_threads(_db_path(), include_closed=include_closed)
    console = Console()
    t = Table(show_header=True, header_style="bold")
    t.add_column("id")
    t.add_column("title")
    t.add_column("created_by")
    t.add_column("created_at")
    t.add_column("closed")
    for r in rows:
        t.add_row(
            r["id"],
            r["title"],
            r["created_by"],
            r["created_at"],
            "yes" if r["closed"] else "no",
        )
    console.print(t)


@main.command(name="thread-create")
@click.option("--title", required=True)
@click.option("--created-by", default="alex")
def thread_create(title: str, created_by: str) -> None:
    """Create a thread."""
    tid = create_thread(_db_path(), title=title, created_by=created_by)
    click.echo(tid)
