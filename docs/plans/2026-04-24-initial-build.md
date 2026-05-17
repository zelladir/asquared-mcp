<!-- markdownlint-disable MD032 MD031 MD010 -->
<!--
  HISTORICAL: this plan was written when the project was named pfit-coord-mcp.
  Path references inside still use the old `src/pfit_coord_mcp/` form; the
  active code lives at `src/asquared_mcp/` after the 2026-05-17 rename.
  Preserved verbatim as a project record.

  MD032 (blanks-around-lists) and MD031 (blanks-around-fences): suppressed
  for this plan. The plan uses a checklist-of-checklists structure where
  every "- [ ] **Step N:**" item is immediately followed by a fenced code
  block — adding blank lines between every list item and its code block
  would balloon the file ~30% with whitespace and visually disconnect each
  step from the code it's about. Standard rendering on GitHub handles the
  current layout cleanly.

  MD010 (no-hard-tabs): suppressed because the Makefile section in Task 26
  contains literal Makefile syntax, which REQUIRES tab indentation for
  recipe lines. Replacing tabs with spaces would produce a broken Makefile.
-->

# PFIT Coordination MCP Server — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a personal-team coordination MCP server hosting a shared message queue between Claude Web, Claude Code, and Codex; expose publicly via Cloudflare Tunnel at `mcp.asquaredhome.com`; route STOP-AND-ASK + handoff-to-alex messages to Pushover.

**Architecture:** Python + FastMCP serving streamable HTTP through a Starlette wrapper that adds Bearer token middleware + Origin-header validation. SQLite (WAL mode) at `./data/coord.db` for the message store. `httpx` async client to Pushover. `coord-cli` reads SQLite directly (admin tool). Cloudflare Tunnel routes the public hostname to `localhost:8765`.

**Tech Stack:** Python 3.12+, `mcp[cli]`, `pydantic` v2, `httpx`, `click`, `rich`, `tomllib`, `uvicorn`, `starlette`. Build: `hatchling`. Lint/type: `ruff`, `mypy --strict`. Test: `pytest` + `pytest-asyncio` + `pytest-httpx`. Containerized via Docker; orchestrated by `docker-compose`.

**Pre-build context (locked in from packet pre-read):**
- MCP SDK API verified: `FastMCP("name").streamable_http_app()` returns ASGI app for mounting; tools accept `ctx: Context[ServerSession, None]`.
- MCP transport spec: single endpoint accepts both POST + GET; `Mcp-Session-Id` header for session correlation; **MUST validate `Origin` header (DNS rebinding defense)**; SHOULD bind to localhost when running locally (Docker port-binds to 127.0.0.1 to satisfy this).
- Pushover: `POST https://api.pushover.net/1/messages.json`, form-encoded, `priority=1` for high (bypasses quiet hours), 1024-char message cap, 250-char title cap, free 10k/month, ≤2 concurrent requests. **Note for PR description:** Pushover banner "API usage limit changes coming May 1st" — monitor post-merge.
- v2 repo conventions to mirror: ruff `select=E,F,W,I,B,UP,C4,RUF`, line-length 100, mypy `strict=true` py312, single-job CI named `validate`.
- Pre-conditions confirmed with Alex: clone to `c:/PFIT/Coding/pfit-coord-mcp/`; `asquaredhome.com` DNS on Cloudflare; Pushover creds available, will be pasted into local `config.toml` after clone. Server still ships with `dry_run=false` only when `pushover.user_key` is non-empty (defensive default in code).

---

## Task index

- **Phase 1 — Repo bootstrap & project layout** (Tasks 1–4)
- **Phase 2 — SQLite store** (Tasks 5–8)
- **Phase 3 — Auth + Origin middleware** (Tasks 9–11)
- **Phase 4 — Notifications module** (Tasks 12–14)
- **Phase 5 — MCP tools + server core** (Tasks 15–20)
- **Phase 6 — CLI** (Tasks 21–23)
- **Phase 7 — Local dev tooling (Docker, compose, Make)** (Tasks 24–26)
- **Phase 8 — End-to-end smoke test** (Task 27)
- **Phase 9 — Docs (Cloudflare, agent setup, Azure migration, README)** (Tasks 28–32)
- **Phase 10 — CI + PR** (Tasks 33–34)

---

## Phase 1 — Repo bootstrap & project layout

### Task 1: Create the repo, branch, and move plan into it

**Files:**
- Create: GitHub repo `zelladir/pfit-coord-mcp`
- Create: local clone at `c:/PFIT/Coding/pfit-coord-mcp/`
- Create: branch `claude/coord-mcp-initial-build`
- Create: `pfit-coord-mcp/docs/plans/2026-04-24-initial-build.md` (move of this plan)

- [ ] **Step 1: Create the GitHub repo**

```bash
gh repo create zelladir/pfit-coord-mcp \
  --public \
  --license MIT \
  --description "Three-way coordination MCP server for Claude Web + Claude Code + Codex"
```

Expected: prints `https://github.com/zelladir/pfit-coord-mcp`.

If this fails with "name already exists" or auth error: HALT and report. Do not pick a different name.

- [ ] **Step 2: Clone locally**

```bash
cd c:/PFIT/Coding
git clone https://github.com/zelladir/pfit-coord-mcp
cd pfit-coord-mcp
```

- [ ] **Step 3: Create the work branch**

```bash
git checkout -b claude/coord-mcp-initial-build
```

- [ ] **Step 4: Move the plan into the repo**

```bash
mkdir -p docs/plans
mv ../pfit-coord-mcp-plan.md docs/plans/2026-04-24-initial-build.md
git add docs/plans/2026-04-24-initial-build.md
git commit -m "docs: add initial implementation plan"
```

---

### Task 2: Write `.gitignore`, `LICENSE` is already there from `gh repo create --license MIT`

**Files:**
- Create: `.gitignore`

- [ ] **Step 1: Write `.gitignore`**

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
dist/
build/
.eggs/

# Virtual environments
.venv/
venv/
env/

# Test / lint caches
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/

# Local config + secrets (NEVER commit)
.env
.env.*
!.env.example
config.toml
!config.toml.example

# SQLite database files
data/*.db
data/*.db-wal
data/*.db-shm

# IDE
.vscode/
.idea/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db
```

- [ ] **Step 2: Commit**

```bash
git add .gitignore
git commit -m "chore: add .gitignore"
```

---

### Task 3: Create directory layout and `pyproject.toml`

**Files:**
- Create: `src/pfit_coord_mcp/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `data/.gitkeep`
- Create: `docs/.gitkeep` (other docs come later)
- Create: `pyproject.toml`

- [ ] **Step 1: Create directories and stub files**

```bash
mkdir -p src/pfit_coord_mcp tests data docs
touch src/pfit_coord_mcp/__init__.py
touch tests/__init__.py
touch data/.gitkeep
```

- [ ] **Step 2: Write `src/pfit_coord_mcp/__init__.py`**

```python
"""PFIT Coordination MCP Server."""

__version__ = "0.1.0"
```

- [ ] **Step 3: Write `tests/conftest.py`**

```python
"""Shared pytest fixtures."""
from __future__ import annotations

import pytest

from pfit_coord_mcp.config import Config, PushoverConfig, ServerConfig
from pfit_coord_mcp.store import init_db


@pytest.fixture
def temp_db(tmp_path):
    """Create a fresh SQLite DB in a temp dir; return its path."""
    db_path = tmp_path / "test_coord.db"
    init_db(str(db_path))
    return str(db_path)


@pytest.fixture
def temp_config(tmp_path, temp_db):
    """Build a Config object pointing at the temp DB with dry-run notifications."""
    return Config(
        server=ServerConfig(port=8765, db_path=temp_db),
        tokens={
            "test-token-claude-web": "claude-web",
            "test-token-claude-code": "claude-code",
            "test-token-codex": "codex",
        },
        pushover=PushoverConfig(
            dry_run=True,
            user_key="",
            app_token="",
        ),
        allowed_origins=["http://localhost", "http://localhost:8765", "https://mcp.asquaredhome.com"],
    )
```

(This fixture imports modules that don't exist yet — that's intentional. Tasks 4–13 build them, and the fixture is consumed starting Task 5. The smoke test pulls it all together in Task 27.)

- [ ] **Step 4: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "pfit-coord-mcp"
version = "0.1.0"
description = "Three-way coordination MCP server for Claude Web + Claude Code + Codex"
readme = "README.md"
requires-python = ">=3.12"
license = { text = "MIT" }
authors = [
    { name = "Path Forward IT", email = "engineering@pathforwardit.com" }
]
dependencies = [
    "mcp>=1.0.0",
    "pydantic>=2.10.0,<3.0.0",
    "httpx>=0.27.0,<1.0.0",
    "click>=8.1.0,<9.0.0",
    "rich>=13.7.0,<14.0.0",
    "uvicorn[standard]>=0.34.0,<1.0.0",
    "starlette>=0.40.0,<1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-httpx>=0.30.0",
    "ruff>=0.7.0",
    "mypy>=1.12.0",
]

[project.scripts]
coord-cli = "pfit_coord_mcp.cli:main"
pfit-coord-mcp = "pfit_coord_mcp.server:main"

[tool.hatch.build.targets.wheel]
packages = ["src/pfit_coord_mcp"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "C4", "RUF"]
ignore = []

[tool.mypy]
python_version = "3.12"
strict = true
disallow_untyped_defs = true
warn_unused_ignores = true
warn_return_any = true
packages = ["pfit_coord_mcp"]
mypy_path = "src"

[[tool.mypy.overrides]]
module = ["mcp.*"]
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
asyncio_mode = "auto"
```

- [ ] **Step 5: Install in editable mode (verify pyproject parses)**

```bash
python -m venv .venv
source .venv/Scripts/activate    # Windows: .venv/Scripts/activate; macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
```

Expected: clean install. If `mcp[cli]` fails to resolve (older PyPI cache), surface and STOP.

- [ ] **Step 6: Commit**

```bash
git add src/ tests/ data/ docs/ pyproject.toml
git commit -m "feat: project scaffold (src layout, pyproject, dev deps)"
```

---

### Task 4: Write `config.py` (TOML loader + Pydantic models)

**Files:**
- Create: `src/pfit_coord_mcp/config.py`
- Create: `tests/test_config.py`
- Create: `config.toml.example`
- Create: `.env.example`

- [ ] **Step 1: Write the failing test (`tests/test_config.py`)**

```python
"""Config loading tests."""
from __future__ import annotations

import pytest

from pfit_coord_mcp.config import Config, load_config


def test_load_config_from_toml(tmp_path):
    """A valid config.toml loads into a Config object with all sections populated."""
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        """
[server]
port = 9000
db_path = "./data/test.db"

[tokens]
"abc123" = "claude-web"
"def456" = "claude-code"
"ghi789" = "codex"

[pushover]
dry_run = false
user_key = "u-test"
app_token = "a-test"

[security]
allowed_origins = ["https://mcp.asquaredhome.com", "http://localhost:8765"]
""",
        encoding="utf-8",
    )
    cfg = load_config(str(cfg_path))
    assert cfg.server.port == 9000
    assert cfg.server.db_path == "./data/test.db"
    assert cfg.tokens == {
        "abc123": "claude-web",
        "def456": "claude-code",
        "ghi789": "codex",
    }
    assert cfg.pushover.dry_run is False
    assert cfg.pushover.user_key == "u-test"
    assert cfg.pushover.app_token == "a-test"
    assert "https://mcp.asquaredhome.com" in cfg.allowed_origins


def test_load_config_missing_file_raises(tmp_path):
    """Missing config file is a hard error (no silent fallback)."""
    with pytest.raises(FileNotFoundError):
        load_config(str(tmp_path / "nope.toml"))


def test_pushover_dry_run_when_creds_empty(tmp_path):
    """If user_key is empty, dry_run is forced to True regardless of the toml setting."""
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        """
[server]
port = 8765
db_path = "./data/c.db"

[tokens]
"t1" = "claude-web"

[pushover]
dry_run = false
user_key = ""
app_token = ""
""",
        encoding="utf-8",
    )
    cfg = load_config(str(cfg_path))
    assert cfg.pushover.dry_run is True, "dry_run must be forced True when creds are empty"


def test_invalid_agent_id_in_tokens_rejected(tmp_path):
    """Token map values must be one of the known agent identities."""
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        """
[server]
port = 8765
db_path = "./data/c.db"

[tokens]
"t1" = "rogue-agent"

[pushover]
dry_run = true
user_key = ""
app_token = ""
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="rogue-agent"):
        load_config(str(cfg_path))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_config.py -v
```

Expected: ImportError on `load_config` / `Config`.

- [ ] **Step 3: Write `src/pfit_coord_mcp/config.py`**

```python
"""TOML config loader for the coordination MCP server."""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

VALID_AGENT_IDS: frozenset[str] = frozenset({"claude-web", "claude-code", "codex"})


class ServerConfig(BaseModel):
    port: int = 8765
    db_path: str = "./data/coord.db"


class PushoverConfig(BaseModel):
    dry_run: bool = True
    user_key: str = ""
    app_token: str = ""


class Config(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    tokens: dict[str, str] = Field(default_factory=dict)
    pushover: PushoverConfig = Field(default_factory=PushoverConfig)
    allowed_origins: list[str] = Field(default_factory=list)

    @field_validator("tokens")
    @classmethod
    def _validate_token_agent_ids(cls, v: dict[str, str]) -> dict[str, str]:
        for token, agent_id in v.items():
            if agent_id not in VALID_AGENT_IDS:
                raise ValueError(
                    f"Token maps to unknown agent_id {agent_id!r}; "
                    f"valid options: {sorted(VALID_AGENT_IDS)}"
                )
        return v

    @model_validator(mode="after")
    def _force_dry_run_when_empty_creds(self) -> "Config":
        if not self.pushover.user_key or not self.pushover.app_token:
            # Pydantic v2 model is frozen-by-default? No — we mutate in place.
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

    return Config(
        server=ServerConfig(**raw.get("server", {})),
        tokens=raw.get("tokens", {}),
        pushover=PushoverConfig(**raw.get("pushover", {})),
        allowed_origins=raw.get("security", {}).get("allowed_origins", []),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_config.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Write `config.toml.example`**

```toml
# Coordination MCP server config.
# Copy this file to `config.toml` (gitignored) and fill in real values.

[server]
port = 8765
db_path = "./data/coord.db"

[tokens]
# Generate fresh tokens with:
#   python -c "import secrets; print(secrets.token_urlsafe(32))"
# Map each token string to one of: claude-web, claude-code, codex
"REPLACE_WITH_GENERATED_TOKEN_1" = "claude-web"
"REPLACE_WITH_GENERATED_TOKEN_2" = "claude-code"
"REPLACE_WITH_GENERATED_TOKEN_3" = "codex"

[pushover]
# Dry-run logs notifications without calling the API. Setting dry_run = false
# only takes effect when both user_key and app_token are non-empty (defensive
# default in config.py).
dry_run = false
user_key = "REPLACE_WITH_PUSHOVER_USER_KEY"
app_token = "REPLACE_WITH_PUSHOVER_APP_TOKEN"

[security]
# Origin allowlist for DNS-rebinding protection (per MCP streamable HTTP spec).
# The middleware allows requests with no Origin header (CLI / curl) and rejects
# unmatched browser-origin requests.
allowed_origins = [
    "https://mcp.asquaredhome.com",
    "http://localhost:8765",
    "http://127.0.0.1:8765",
]
```

- [ ] **Step 6: Write `.env.example`**

```text
# Optional: override config file location. Defaults to ./config.toml.
# COORD_CONFIG=/app/config.toml
```

- [ ] **Step 7: Commit**

```bash
git add src/pfit_coord_mcp/config.py tests/test_config.py config.toml.example .env.example
git commit -m "feat(config): toml loader with agent-id validation and dry-run safeguard"
```

---

## Phase 2 — SQLite store

### Task 5: `store.py` schema initialization

**Files:**
- Create: `src/pfit_coord_mcp/store.py`
- Create: `tests/test_store.py`

- [ ] **Step 1: Write the failing test**

```python
"""SQLite store tests."""
from __future__ import annotations

import sqlite3

from pfit_coord_mcp.store import init_db


def test_init_db_creates_schema(tmp_path):
    """init_db creates messages, threads, meta tables and indexes."""
    db = tmp_path / "c.db"
    init_db(str(db))
    conn = sqlite3.connect(str(db))
    try:
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        assert {"messages", "threads", "meta"} <= tables
        indexes = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )}
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_store.py -v
```

Expected: ImportError on `init_db`.

- [ ] **Step 3: Write `src/pfit_coord_mcp/store.py` (init_db only)**

```python
"""SQLite-backed message store."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp          TEXT NOT NULL,
    from_agent         TEXT NOT NULL,
    to_agent           TEXT NOT NULL,
    thread_id          TEXT,
    kind               TEXT NOT NULL,
    payload            TEXT NOT NULL,
    read_by            TEXT NOT NULL DEFAULT '[]',
    notified_at        TEXT,
    notification_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_to_agent  ON messages(to_agent);
CREATE INDEX IF NOT EXISTS idx_messages_thread    ON messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);

CREATE TABLE IF NOT EXISTS threads (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    created_by  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    closed      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def init_db(path: str) -> None:
    """Create the SQLite database (if needed) and apply schema. Idempotent."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def _connect(path: str) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_store.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/pfit_coord_mcp/store.py tests/test_store.py
git commit -m "feat(store): schema init with WAL mode"
```

---

### Task 6: `store.py` — post + read messages

**Files:**
- Modify: `src/pfit_coord_mcp/store.py`
- Modify: `tests/test_store.py`

- [ ] **Step 1: Append failing tests to `tests/test_store.py`**

```python
import json

from pfit_coord_mcp.store import (
    post_message,
    read_messages,
    get_message,
)


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
    # caller-supplied giant limit must not exceed 200; we only have 5 here so this only checks the mechanism doesn't crash
    assert len(rows) == 5


def test_read_messages_default_returns_recent(temp_db):
    post_message(temp_db, "codex", "alex", "note", "{}", None)
    rows = read_messages(temp_db, to_agent="alex")
    assert len(rows) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_store.py -v
```

Expected: ImportError on `post_message`, `read_messages`, `get_message`.

- [ ] **Step 3: Append to `src/pfit_coord_mcp/store.py`**

```python
RECIPIENT_BROADCAST = "broadcast"


def post_message(
    db_path: str,
    from_agent: str,
    to_agent: str,
    kind: str,
    payload: str,
    thread_id: str | None,
) -> int:
    """Insert a message and return its new id."""
    with _connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO messages (timestamp, from_agent, to_agent, thread_id, kind, payload)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (_now_iso(), from_agent, to_agent, thread_id, kind, payload),
        )
        new_id = cur.lastrowid
        if new_id is None:  # pragma: no cover  # SQLite always returns an id for AUTOINCREMENT
            raise RuntimeError("SQLite did not return a lastrowid")
        return int(new_id)


def get_message(db_path: str, message_id: int) -> sqlite3.Row | None:
    with _connect(db_path) as conn:
        cur = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
        return cur.fetchone()


def read_messages(
    db_path: str,
    to_agent: str,
    since_id: int | None = None,
    thread_id: str | None = None,
    kinds: Sequence[str] | None = None,
    unread_only: bool = False,
    limit: int = 50,
) -> list[sqlite3.Row]:
    """Return messages addressed to `to_agent` (or to broadcast).

    Filters compose with AND. `unread_only` excludes rows whose `read_by` JSON
    array already contains `to_agent`.
    """
    capped_limit = min(max(limit, 1), 200)
    clauses = ["(to_agent = ? OR to_agent = ?)"]
    params: list[Any] = [to_agent, RECIPIENT_BROADCAST]
    if since_id is not None:
        clauses.append("id > ?")
        params.append(since_id)
    if thread_id is not None:
        clauses.append("thread_id = ?")
        params.append(thread_id)
    if kinds:
        placeholders = ",".join("?" for _ in kinds)
        clauses.append(f"kind IN ({placeholders})")
        params.extend(kinds)
    if unread_only:
        # SQLite JSON1 — `json_each(read_by)` exposes the array elements;
        # the NOT EXISTS keeps rows where to_agent is not yet in the array.
        clauses.append(
            "NOT EXISTS (SELECT 1 FROM json_each(read_by) WHERE value = ?)"
        )
        params.append(to_agent)

    sql = (
        "SELECT * FROM messages WHERE " + " AND ".join(clauses)
        + " ORDER BY id ASC LIMIT ?"
    )
    params.append(capped_limit)
    with _connect(db_path) as conn:
        return list(conn.execute(sql, params).fetchall())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_store.py -v
```

Expected: 3 (from Task 5) + 8 (new) = 11 passed.

- [ ] **Step 5: Commit**

```bash
git add src/pfit_coord_mcp/store.py tests/test_store.py
git commit -m "feat(store): post_message + read_messages with broadcast and filters"
```

---

### Task 7: `store.py` — ack + notification tracking

**Files:**
- Modify: `src/pfit_coord_mcp/store.py`
- Modify: `tests/test_store.py`

- [ ] **Step 1: Append failing tests**

```python
from pfit_coord_mcp.store import ack_messages, mark_notified, pending_notifications


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
    not_eligible_recipient = post_message(temp_db, "codex", "claude-web", "stop_and_ask", "{}", None)
    already = post_message(temp_db, "codex", "alex", "stop_and_ask", "{}", None)
    mark_notified(temp_db, already, error=None)

    pending_ids = {r["id"] for r in pending_notifications(temp_db)}
    assert eligible in pending_ids
    assert not_eligible_kind not in pending_ids
    # stop_and_ask to a non-alex recipient still triggers because rule is "stop_and_ask -> any"
    assert not_eligible_recipient in pending_ids
    assert already not in pending_ids
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_store.py -v
```

Expected: ImportError on `ack_messages`, `mark_notified`, `pending_notifications`.

- [ ] **Step 3: Append to `src/pfit_coord_mcp/store.py`**

```python
def ack_messages(db_path: str, message_ids: Sequence[int], by_agent: str) -> int:
    """Append `by_agent` to each message's `read_by` JSON array. Idempotent."""
    if not message_ids:
        return 0
    with _connect(db_path) as conn:
        n = 0
        for mid in message_ids:
            row = conn.execute("SELECT read_by FROM messages WHERE id = ?", (mid,)).fetchone()
            if row is None:
                continue
            existing = json.loads(row["read_by"])
            if by_agent not in existing:
                existing.append(by_agent)
                conn.execute(
                    "UPDATE messages SET read_by = ? WHERE id = ?",
                    (json.dumps(existing), mid),
                )
            n += 1
        return n


def mark_notified(db_path: str, message_id: int, error: str | None) -> None:
    """Set notified_at = now and record any error string."""
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE messages SET notified_at = ?, notification_error = ? WHERE id = ?",
            (_now_iso(), error, message_id),
        )


# Server-enforced notification rules. (kind, recipient_predicate) -> priority
NOTIFY_KIND_RULES = {
    "stop_and_ask": "*",      # any recipient
    "handoff":      "alex",   # only when addressed to alex
    "task_complete":"alex",
    "question":     "alex",
}


def pending_notifications(db_path: str) -> list[sqlite3.Row]:
    """Return messages eligible for notification (not yet notified)."""
    parts: list[str] = []
    params: list[Any] = []
    for kind, recipient in NOTIFY_KIND_RULES.items():
        if recipient == "*":
            parts.append("kind = ?")
            params.append(kind)
        else:
            parts.append("(kind = ? AND to_agent = ?)")
            params.extend([kind, recipient])
    where = "(" + " OR ".join(parts) + ") AND notified_at IS NULL"
    with _connect(db_path) as conn:
        return list(conn.execute(
            f"SELECT * FROM messages WHERE {where} ORDER BY id ASC", params
        ).fetchall())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_store.py -v
```

Expected: 11 + 5 = 16 passed.

- [ ] **Step 5: Commit**

```bash
git add src/pfit_coord_mcp/store.py tests/test_store.py
git commit -m "feat(store): ack tracking + pending_notifications"
```

---

### Task 8: `store.py` — threads

**Files:**
- Modify: `src/pfit_coord_mcp/store.py`
- Modify: `tests/test_store.py`

- [ ] **Step 1: Append failing tests**

```python
from pfit_coord_mcp.store import close_thread, create_thread, list_threads


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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_store.py -v
```

Expected: ImportError on `create_thread`, `list_threads`, `close_thread`.

- [ ] **Step 3: Append to `src/pfit_coord_mcp/store.py`**

```python
import secrets


def create_thread(db_path: str, title: str, created_by: str) -> str:
    """Create a thread with a short URL-safe slug ID."""
    tid = "thr-" + secrets.token_urlsafe(6)
    with _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO threads (id, title, created_by, created_at, closed) VALUES (?, ?, ?, ?, 0)",
            (tid, title, created_by, _now_iso()),
        )
    return tid


def list_threads(db_path: str, include_closed: bool = False) -> list[sqlite3.Row]:
    sql = "SELECT * FROM threads"
    if not include_closed:
        sql += " WHERE closed = 0"
    sql += " ORDER BY created_at DESC"
    with _connect(db_path) as conn:
        return list(conn.execute(sql).fetchall())


def close_thread(db_path: str, thread_id: str) -> None:
    with _connect(db_path) as conn:
        conn.execute("UPDATE threads SET closed = 1 WHERE id = ?", (thread_id,))
```

- [ ] **Step 4: Run tests pass**

```bash
pytest tests/test_store.py -v
```

Expected: 16 + 2 = 18 passed.

- [ ] **Step 5: Commit**

```bash
git add src/pfit_coord_mcp/store.py tests/test_store.py
git commit -m "feat(store): thread create/list/close"
```

---

## Phase 3 — Auth + Origin middleware

### Task 9: Bearer token middleware

**Files:**
- Create: `src/pfit_coord_mcp/auth.py`
- Create: `tests/test_auth.py`

- [ ] **Step 1: Write the failing test**

```python
"""Auth middleware tests."""
from __future__ import annotations

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from pfit_coord_mcp.auth import (
    AGENT_ID_STATE_KEY,
    BearerTokenMiddleware,
    OriginAllowlistMiddleware,
)


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


def test_malformed_authorization_returns_401():
    client = TestClient(_build_app({"abc": "claude-web"}))
    r = client.get("/echo", headers={"Authorization": "Token abc"})
    assert r.status_code == 401


def test_unknown_token_returns_401():
    client = TestClient(_build_app({"abc": "claude-web"}))
    r = client.get("/echo", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_valid_token_attaches_agent_id():
    client = TestClient(_build_app({"abc": "claude-web"}))
    r = client.get("/echo", headers={"Authorization": "Bearer abc"})
    assert r.status_code == 200
    assert r.json() == {"agent_id": "claude-web"}


def test_health_endpoint_bypasses_auth():
    """Requests to /health pass through both middlewares unauthenticated."""
    from pfit_coord_mcp.auth import HEALTH_PATH

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    app = Starlette(
        routes=[Route(HEALTH_PATH, health)],
        middleware=[Middleware(BearerTokenMiddleware, token_map={"abc": "claude-web"})],
    )
    client = TestClient(app)
    assert client.get(HEALTH_PATH).status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_auth.py -v
```

Expected: ImportError on `auth` module.

- [ ] **Step 3: Write `src/pfit_coord_mcp/auth.py`**

```python
"""Starlette middleware: Bearer-token auth + Origin allowlist."""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

AGENT_ID_STATE_KEY = "agent_id"
HEALTH_PATH = "/health"


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Validate `Authorization: Bearer <token>`; attach agent_id to request.state.

    The /health endpoint is unauthenticated (bypass).
    """

    def __init__(self, app: ASGIApp, token_map: dict[str, str]) -> None:
        super().__init__(app)
        self.token_map = token_map

    async def dispatch(self, request: Request, call_next):
        if request.url.path == HEALTH_PATH:
            return await call_next(request)

        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return JSONResponse(
                {"error": "unauthorized", "message": "Bearer token required"},
                status_code=401,
            )
        agent_id = self.token_map.get(token)
        if agent_id is None:
            return JSONResponse(
                {"error": "unauthorized", "message": "Unknown bearer token"},
                status_code=401,
            )
        setattr(request.state, AGENT_ID_STATE_KEY, agent_id)
        return await call_next(request)


class OriginAllowlistMiddleware(BaseHTTPMiddleware):
    """DNS-rebinding defense per MCP streamable HTTP spec.

    Rules:
    - Requests with no Origin header pass through (CLI / curl / non-browser).
    - Requests with an Origin header must match one of `allowed_origins`.
    - /health is exempt.
    """

    def __init__(self, app: ASGIApp, allowed_origins: list[str]) -> None:
        super().__init__(app)
        self.allowed_origins = set(allowed_origins)

    async def dispatch(self, request: Request, call_next):
        if request.url.path == HEALTH_PATH:
            return await call_next(request)
        origin = request.headers.get("origin")
        if origin is not None and origin not in self.allowed_origins:
            return JSONResponse(
                {"error": "forbidden_origin", "message": f"Origin not allowed: {origin}"},
                status_code=403,
            )
        return await call_next(request)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_auth.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/pfit_coord_mcp/auth.py tests/test_auth.py
git commit -m "feat(auth): bearer token + origin allowlist middleware"
```

---

### Task 10: Origin allowlist edge cases

**Files:**
- Modify: `tests/test_auth.py`

- [ ] **Step 1: Append failing tests**

```python
def test_origin_allowed_passes():
    client = TestClient(_build_app(
        {"abc": "claude-web"},
        allowed_origins=["https://mcp.asquaredhome.com"],
    ))
    r = client.get(
        "/echo",
        headers={
            "Authorization": "Bearer abc",
            "Origin": "https://mcp.asquaredhome.com",
        },
    )
    assert r.status_code == 200


def test_origin_disallowed_rejected():
    client = TestClient(_build_app(
        {"abc": "claude-web"},
        allowed_origins=["https://mcp.asquaredhome.com"],
    ))
    r = client.get(
        "/echo",
        headers={
            "Authorization": "Bearer abc",
            "Origin": "https://attacker.example.com",
        },
    )
    assert r.status_code == 403
    assert r.json()["error"] == "forbidden_origin"


def test_no_origin_header_passes_through():
    """CLI / curl / non-browser clients have no Origin and must pass."""
    client = TestClient(_build_app(
        {"abc": "claude-web"},
        allowed_origins=["https://mcp.asquaredhome.com"],
    ))
    r = client.get("/echo", headers={"Authorization": "Bearer abc"})
    assert r.status_code == 200
```

- [ ] **Step 2: Run tests to verify they pass (no implementation change needed)**

```bash
pytest tests/test_auth.py -v
```

Expected: 5 + 3 = 8 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_auth.py
git commit -m "test(auth): origin allowlist edge cases"
```

---

### Task 11: `models.py` for shared Pydantic input/output types

**Files:**
- Create: `src/pfit_coord_mcp/models.py`

(No tests — these are pure data classes consumed by tools, indirectly tested via the server tests in Task 17 and the smoke test in Task 27.)

- [ ] **Step 1: Write `src/pfit_coord_mcp/models.py`**

```python
"""Pydantic input/output models for MCP tool calls."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ValidRecipient = Literal["claude-web", "claude-code", "codex", "alex", "broadcast"]
ValidKind = Literal[
    "status",
    "question",
    "answer",
    "handoff",
    "note",
    "stop_and_ask",
    "task_complete",
]


class CoordPostInput(BaseModel):
    to_agent: ValidRecipient
    kind: ValidKind
    payload: dict[str, Any]
    thread_id: str | None = None


class CoordReadInput(BaseModel):
    since_id: int | None = None
    thread_id: str | None = None
    kinds: list[ValidKind] | None = None
    unread_only: bool = False
    limit: int = 50


class CoordThreadsInput(BaseModel):
    action: Literal["create", "list", "close"]
    thread_id: str | None = None
    title: str | None = None
    include_closed: bool = False


class CoordAckInput(BaseModel):
    message_ids: list[int]


class CoordStatusInput(BaseModel):
    summary: str = Field(..., max_length=500)
    thread_id: str | None = None


class NotifyResult(BaseModel):
    notified: bool
    error: str | None = None
    reason: str | None = None
```

- [ ] **Step 2: Verify it imports**

```bash
python -c "from pfit_coord_mcp.models import CoordPostInput; print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/pfit_coord_mcp/models.py
git commit -m "feat(models): pydantic input/output models for tools"
```

---

## Phase 4 — Notifications module

### Task 12: `notify.py` — rule matcher + dry-run path

**Files:**
- Create: `src/pfit_coord_mcp/notify.py`
- Create: `tests/test_notify.py`

- [ ] **Step 1: Write the failing test**

```python
"""Notification module tests."""
from __future__ import annotations

import json

import pytest

from pfit_coord_mcp.config import Config, PushoverConfig, ServerConfig
from pfit_coord_mcp.notify import maybe_notify, rule_matches
from pfit_coord_mcp.store import get_message, post_message


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
    msg_id = post_message(temp_db, "codex", "alex", "stop_and_ask", json.dumps({"text": "ping"}), None)
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_notify.py -v
```

Expected: ImportError on `notify` module.

- [ ] **Step 3: Write `src/pfit_coord_mcp/notify.py`**

```python
"""Pushover notification dispatcher."""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from .config import Config
from .models import NotifyResult
from .store import get_message, mark_notified

logger = logging.getLogger(__name__)

PUSHOVER_URL = "https://api.pushover.net/1/messages.json"
PUSHOVER_TIMEOUT_SECONDS = 10
MAX_BODY_CHARS = 1024
TRUNCATION_SUFFIX = "[truncated]"

# (kind, recipient_pattern) -> Pushover priority
_RULES: dict[tuple[str, str], int] = {
    ("stop_and_ask", "*"):    1,   # high priority, bypasses quiet hours
    ("handoff",       "alex"): 0,
    ("task_complete", "alex"): 0,
    ("question",      "alex"): 0,
}


def rule_matches(kind: str, to_agent: str) -> bool:
    return _priority_for(kind, to_agent) is not None


def _priority_for(kind: str, to_agent: str) -> int | None:
    for (rule_kind, rule_recipient), priority in _RULES.items():
        if kind != rule_kind:
            continue
        if rule_recipient == "*" or rule_recipient == to_agent:
            return priority
    return None


def _format_body(payload_json: str) -> str:
    try:
        payload: Any = json.loads(payload_json)
    except json.JSONDecodeError:
        text = payload_json
    else:
        if isinstance(payload, dict):
            text = (
                payload.get("text")
                or payload.get("message")
                or payload.get("question")
                or json.dumps(payload, indent=2)
            )
        else:
            text = json.dumps(payload, indent=2)
    if len(text) > MAX_BODY_CHARS:
        text = text[: MAX_BODY_CHARS - len(TRUNCATION_SUFFIX)] + TRUNCATION_SUFFIX
    return text


async def maybe_notify(config: Config, message_id: int) -> NotifyResult:
    """Apply rules and fire (or skip) a Pushover push for one message."""
    msg = get_message(config.server.db_path, message_id)
    if msg is None:
        return NotifyResult(notified=False, reason="message_not_found")
    if msg["notified_at"] is not None:
        return NotifyResult(notified=False, reason="already_notified")

    priority = _priority_for(msg["kind"], msg["to_agent"])
    if priority is None:
        return NotifyResult(notified=False, reason="rule_not_matched")

    if config.pushover.dry_run:
        body_preview = _format_body(msg["payload"])
        logger.info(
            "DRY_RUN push: kind=%s from=%s to=%s priority=%s body=%r",
            msg["kind"], msg["from_agent"], msg["to_agent"], priority, body_preview,
        )
        mark_notified(config.server.db_path, message_id, error="dry_run")
        return NotifyResult(notified=False, reason="dry_run")

    title = f"[{msg['from_agent']}] {msg['kind']}"
    body = _format_body(msg["payload"])
    try:
        async with httpx.AsyncClient(timeout=PUSHOVER_TIMEOUT_SECONDS) as client:
            r = await client.post(
                PUSHOVER_URL,
                data={
                    "token": config.pushover.app_token,
                    "user": config.pushover.user_key,
                    "title": title,
                    "message": body,
                    "priority": priority,
                },
            )
            r.raise_for_status()
    except Exception as e:
        mark_notified(config.server.db_path, message_id, error=str(e))
        return NotifyResult(notified=False, error=str(e), reason="push_failed")

    mark_notified(config.server.db_path, message_id, error=None)
    return NotifyResult(notified=True)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_notify.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/pfit_coord_mcp/notify.py tests/test_notify.py
git commit -m "feat(notify): rule matcher + dry-run path"
```

---

### Task 13: `notify.py` — live Pushover (mocked HTTP)

**Files:**
- Modify: `tests/test_notify.py`

- [ ] **Step 1: Append failing tests**

```python
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
    temp_db, live_config, httpx_mock,
):
    httpx_mock.add_response(
        method="POST",
        url=PUSHOVER_URL,
        json={"status": 1, "request": "abc"},
        status_code=200,
    )
    msg_id = post_message(
        temp_db, "codex", "alex", "stop_and_ask",
        json.dumps({"question": "approve plan?"}),
        None,
    )
    result = await maybe_notify(live_config, msg_id)
    assert result.notified is True
    assert result.error is None

    sent = httpx_mock.get_request()
    assert sent is not None
    body = dict([kv.split("=", 1) for kv in sent.content.decode().split("&")])
    # urlencoded — pytest-httpx exposes raw bytes; we decode and split.
    assert body["token"] == "a-test"
    assert body["user"] == "u-test"
    assert body["priority"] == "1"


@pytest.mark.asyncio
async def test_maybe_notify_uses_priority_0_for_handoff_to_alex(
    temp_db, live_config, httpx_mock,
):
    httpx_mock.add_response(method="POST", url=PUSHOVER_URL, json={"status": 1, "request": "x"}, status_code=200)
    msg_id = post_message(temp_db, "codex", "alex", "handoff", "{}", None)
    result = await maybe_notify(live_config, msg_id)
    assert result.notified is True
    sent = httpx_mock.get_request()
    body = dict([kv.split("=", 1) for kv in sent.content.decode().split("&")])
    assert body["priority"] == "0"


@pytest.mark.asyncio
async def test_maybe_notify_marks_notified_on_4xx_to_prevent_retry_loop(
    temp_db, live_config, httpx_mock,
):
    httpx_mock.add_response(
        method="POST", url=PUSHOVER_URL, status_code=400,
        json={"status": 0, "errors": ["bad request"]},
    )
    msg_id = post_message(temp_db, "codex", "alex", "stop_and_ask", "{}", None)
    result = await maybe_notify(live_config, msg_id)
    assert result.notified is False
    assert result.error is not None
    row = get_message(temp_db, msg_id)
    assert row["notified_at"] is not None  # set so we don't retry
    assert "400" in (row["notification_error"] or "")


@pytest.mark.asyncio
async def test_format_body_truncates_at_1024_chars():
    from pfit_coord_mcp.notify import _format_body
    long = json.dumps({"text": "x" * 2000})
    out = _format_body(long)
    assert len(out) == 1024
    assert out.endswith("[truncated]")


@pytest.mark.asyncio
async def test_format_body_prefers_text_field():
    from pfit_coord_mcp.notify import _format_body
    out = _format_body(json.dumps({"text": "hello", "extra": "ignored"}))
    assert out == "hello"
```

- [ ] **Step 2: Add `httpx_mock` import + URL constant import to top of file**

```python
from pfit_coord_mcp.notify import PUSHOVER_URL
```

- [ ] **Step 3: Run tests to verify pass**

```bash
pytest tests/test_notify.py -v
```

Expected: 6 + 5 = 11 passed.

- [ ] **Step 4: Commit**

```bash
git add tests/test_notify.py
git commit -m "test(notify): live pushover paths with mocked httpx"
```

---

### Task 14: `notify.py` — long-payload truncation safety

**Files:**
- Modify: `src/pfit_coord_mcp/notify.py` (no behavior change; verify edge case is covered)

- [ ] **Step 1: Add edge-case test for non-dict payload**

In `tests/test_notify.py`, append:

```python
def test_format_body_handles_non_dict_payload():
    from pfit_coord_mcp.notify import _format_body
    out = _format_body(json.dumps(["a", "b", "c"]))
    # falls through to json.dumps with indent
    assert "[" in out
    assert "]" in out


def test_format_body_handles_invalid_json_payload():
    from pfit_coord_mcp.notify import _format_body
    out = _format_body("not-json-at-all")
    assert out == "not-json-at-all"
```

- [ ] **Step 2: Run tests pass (no impl change needed)**

```bash
pytest tests/test_notify.py -v
```

Expected: 11 + 2 = 13 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_notify.py
git commit -m "test(notify): non-dict and invalid-json payload paths"
```

---

## Phase 5 — MCP tools + server core

### Task 15: Wire FastMCP server skeleton + ASGI app builder

**Files:**
- Create: `src/pfit_coord_mcp/server.py`

(Tests for tools come in Task 17 once the tools are wired. This task just builds the scaffolding.)

- [ ] **Step 1: Write `src/pfit_coord_mcp/server.py`**

```python
"""FastMCP server with bearer-auth + origin-validated streamable HTTP transport."""
from __future__ import annotations

import json
import logging
import os
from contextvars import ContextVar
from typing import Any

import uvicorn
from mcp.server.fastmcp import Context, FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from . import __version__
from .auth import (
    AGENT_ID_STATE_KEY,
    BearerTokenMiddleware,
    HEALTH_PATH,
    OriginAllowlistMiddleware,
)
from .config import Config, load_config
from .models import (
    CoordAckInput,
    CoordPostInput,
    CoordReadInput,
    CoordStatusInput,
    CoordThreadsInput,
)
from .notify import maybe_notify
from .store import (
    ack_messages,
    close_thread,
    create_thread,
    init_db,
    list_threads,
    post_message,
    read_messages,
)

logger = logging.getLogger(__name__)

# Per-request agent_id propagated from auth middleware. FastMCP tool handlers
# can't directly access starlette request.state, so the resolved agent_id is
# stashed in a contextvar inside a pure-ASGI middleware that runs after
# BearerTokenMiddleware. Tool handlers read it via _require_agent_id().
_current_agent: ContextVar[str | None] = ContextVar("_current_agent", default=None)


class AgentContextMiddleware:
    """Pure-ASGI middleware: copies scope['agent_id'] (set by BearerTokenMiddleware)
    into the _current_agent contextvar so tool handlers can read it.

    Why a top-level scope key instead of scope['state']: Starlette's
    request.state is a State() object (not a dict), and scope['state'] holds
    that object — it doesn't support .get('agent_id'). Writing a plain str at
    scope['agent_id'] keeps this pure-ASGI bridge simple.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        agent_id = scope.get("agent_id")
        token = _current_agent.set(agent_id)
        try:
            await self.app(scope, receive, send)
        finally:
            _current_agent.reset(token)


def _require_agent_id() -> str:
    aid = _current_agent.get()
    if aid is None:
        raise RuntimeError("agent_id is missing — auth middleware not applied?")
    return aid


def build_mcp(config: Config) -> FastMCP:
    """Build a FastMCP instance with the five coord_* tools registered."""
    mcp = FastMCP("pfit_coord_mcp")

    @mcp.tool(name="coord_post")
    async def coord_post(params: CoordPostInput, ctx: Context) -> dict[str, Any]:
        """Post a message to the coordination queue.

        The `kind` field determines routing and notification behavior:
        - 'stop_and_ask': any recipient -> high-priority Pushover push
        - 'handoff' / 'task_complete' / 'question': only when to_agent='alex' -> normal-priority push
        - 'status' / 'note' / 'answer': no push

        Returns: { message_id, from_agent, notified, notification_error }
        """
        from_agent = _require_agent_id()
        msg_id = post_message(
            db_path=config.server.db_path,
            from_agent=from_agent,
            to_agent=params.to_agent,
            kind=params.kind,
            payload=json.dumps(params.payload),
            thread_id=params.thread_id,
        )
        result = await maybe_notify(config, msg_id)
        return {
            "message_id": msg_id,
            "from_agent": from_agent,
            "notified": result.notified,
            "notification_reason": result.reason,
            "notification_error": result.error,
        }

    @mcp.tool(name="coord_read")
    async def coord_read(params: CoordReadInput, ctx: Context) -> dict[str, Any]:
        """Read messages addressed to your agent ID (or to broadcast).

        Defaults: most recent 50 messages. Use `since_id` to poll for new ones.
        Use `thread_id` to read a single thread, `kinds` to filter, `unread_only`
        to skip messages your agent has already acked.
        """
        agent_id = _require_agent_id()
        rows = read_messages(
            db_path=config.server.db_path,
            to_agent=agent_id,
            since_id=params.since_id,
            thread_id=params.thread_id,
            kinds=params.kinds,
            unread_only=params.unread_only,
            limit=params.limit,
        )
        return {
            "messages": [_row_to_dict(r) for r in rows],
            "count": len(rows),
        }

    @mcp.tool(name="coord_threads")
    async def coord_threads_tool(params: CoordThreadsInput, ctx: Context) -> dict[str, Any]:
        """Manage coordination threads (create / list / close)."""
        agent_id = _require_agent_id()
        if params.action == "create":
            if not params.title:
                raise ValueError("`title` is required for action='create'")
            tid = create_thread(config.server.db_path, params.title, created_by=agent_id)
            return {"thread_id": tid, "title": params.title}
        if params.action == "list":
            rows = list_threads(config.server.db_path, include_closed=params.include_closed)
            return {"threads": [dict(r) for r in rows]}
        if params.action == "close":
            if not params.thread_id:
                raise ValueError("`thread_id` is required for action='close'")
            close_thread(config.server.db_path, params.thread_id)
            return {"closed": params.thread_id}
        raise ValueError(f"unknown action: {params.action}")

    @mcp.tool(name="coord_ack")
    async def coord_ack(params: CoordAckInput, ctx: Context) -> dict[str, Any]:
        """Mark messages as read by your agent ID."""
        agent_id = _require_agent_id()
        n = ack_messages(config.server.db_path, params.message_ids, by_agent=agent_id)
        return {"acked": n}

    @mcp.tool(name="coord_status")
    async def coord_status(params: CoordStatusInput, ctx: Context) -> dict[str, Any]:
        """Post a lightweight status heartbeat to broadcast (no notification)."""
        from_agent = _require_agent_id()
        msg_id = post_message(
            db_path=config.server.db_path,
            from_agent=from_agent,
            to_agent="broadcast",
            kind="status",
            payload=json.dumps({"summary": params.summary}),
            thread_id=params.thread_id,
        )
        return {"message_id": msg_id, "from_agent": from_agent}

    return mcp


def _row_to_dict(row) -> dict[str, Any]:
    d = dict(row)
    if d.get("read_by"):
        try:
            d["read_by"] = json.loads(d["read_by"])
        except json.JSONDecodeError:
            pass
    if d.get("payload"):
        try:
            d["payload"] = json.loads(d["payload"])
        except json.JSONDecodeError:
            pass
    return d


async def health(_request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "version": __version__})


def build_app(config: Config) -> Starlette:
    """Compose Starlette app: /health unauthenticated; /mcp wrapped in middleware."""
    init_db(config.server.db_path)
    mcp = build_mcp(config)
    mcp_app = mcp.streamable_http_app()

    return Starlette(
        routes=[
            Route(HEALTH_PATH, health),
            Mount("/mcp", app=mcp_app),
        ],
        middleware=[
            Middleware(OriginAllowlistMiddleware, allowed_origins=config.allowed_origins),
            Middleware(BearerTokenMiddleware, token_map=config.tokens),
            Middleware(AgentContextMiddleware),
        ],
    )


def main() -> None:
    """Entry point used by `pfit-coord-mcp` script."""
    logging.basicConfig(
        level=os.environ.get("COORD_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config_path = os.environ.get("COORD_CONFIG", "./config.toml")
    config = load_config(config_path)
    app = build_app(config)
    # Bind to 0.0.0.0 inside the container — docker-compose maps to 127.0.0.1
    # so the host-side socket is not internet-reachable. Cloudflared connects
    # via the loopback mapping.
    uvicorn.run(app, host="0.0.0.0", port=config.server.port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify import**

```bash
python -c "from pfit_coord_mcp.server import build_app; print('ok')"
```

Expected: `ok`. If `mcp.server.fastmcp.server.ServerSession` import path differs in installed SDK, adjust to whatever the SDK README says (the API verified during pre-read uses this path; if it differs, surface and STOP).

- [ ] **Step 3: Commit**

```bash
git add src/pfit_coord_mcp/server.py
git commit -m "feat(server): FastMCP wiring + 5 tools + asgi composition"
```

---

### Task 16: Bridge agent_id from request.state into scope for the contextvar middleware

The `BearerTokenMiddleware` writes to `request.state` (a Starlette `State` object).
`AgentContextMiddleware` is a pure-ASGI middleware that reads from `scope["agent_id"]`
(a plain str at the top level of scope). They communicate via the scope dict, so
`BearerTokenMiddleware` must ALSO write the str to `scope["agent_id"]` — `request.state`
alone is invisible to pure-ASGI middlewares.

**Files:**
- Modify: `src/pfit_coord_mcp/auth.py`

- [ ] **Step 1: Update `BearerTokenMiddleware.dispatch` to also set `scope["agent_id"]`**

In `auth.py`, the line that currently reads:

```python
setattr(request.state, AGENT_ID_STATE_KEY, agent_id)
```

becomes two lines:

```python
setattr(request.state, AGENT_ID_STATE_KEY, agent_id)
# Top-level scope key (plain str) so pure-ASGI middlewares can read it.
# scope["state"] holds a State object, not a dict, so we write at the top level instead.
request.scope[AGENT_ID_STATE_KEY] = agent_id
```

- [ ] **Step 2: Re-run auth tests to confirm no regression**

```bash
pytest tests/test_auth.py -v
```

Expected: 8 passed.

- [ ] **Step 3: Add a test verifying agent_id propagates to scope**

Append to `tests/test_auth.py`:

```python
def test_agent_id_propagates_to_scope_top_level():
    """BearerTokenMiddleware must write agent_id to scope['agent_id'] so pure-ASGI middlewares see it."""
    from starlette.requests import Request
    from starlette.responses import PlainTextResponse

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
```

- [ ] **Step 4: Run tests pass**

```bash
pytest tests/test_auth.py -v
```

Expected: 8 + 1 = 9 passed.

- [ ] **Step 5: Commit**

```bash
git add src/pfit_coord_mcp/auth.py tests/test_auth.py
git commit -m "fix(auth): propagate agent_id to scope state for asgi middlewares"
```

---

### Task 17: Tool unit tests

**Files:**
- Create: `tests/test_tools.py`

These exercise the tool functions directly (bypassing FastMCP routing) by setting the contextvars manually. The end-to-end MCP request path is covered by the smoke test in Task 27.

- [ ] **Step 1: Write `tests/test_tools.py`**

```python
"""Direct unit tests on the tool functions (contextvars set manually)."""
from __future__ import annotations

import json

import pytest

from pfit_coord_mcp.models import (
    CoordAckInput,
    CoordPostInput,
    CoordReadInput,
    CoordStatusInput,
    CoordThreadsInput,
)
from pfit_coord_mcp.server import _current_agent, build_mcp
from pfit_coord_mcp.store import get_message


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
async def test_coord_read_returns_recipient_and_broadcast(mcp_with_config):
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
        assert "claude-web" not in targets
    finally:
        _current_agent.reset(reader)


@pytest.mark.asyncio
async def test_coord_threads_create_then_list_then_close(mcp_with_config):
    mcp, _ = mcp_with_config
    token = _set_agent("codex")
    try:
        created = await _get_tool(mcp, "coord_threads")(
            CoordThreadsInput(action="create", title="wave A"), ctx=None,
        )
        tid = created["thread_id"]
        listed = await _get_tool(mcp, "coord_threads")(
            CoordThreadsInput(action="list"), ctx=None,
        )
        assert any(t["id"] == tid for t in listed["threads"])
        await _get_tool(mcp, "coord_threads")(
            CoordThreadsInput(action="close", thread_id=tid), ctx=None,
        )
        listed_after = await _get_tool(mcp, "coord_threads")(
            CoordThreadsInput(action="list", include_closed=False), ctx=None,
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
            CoordPostInput(to_agent="alex", kind="note", payload={}), ctx=None,
        )
    finally:
        _current_agent.reset(poster)
    reader = _set_agent("alex")
    try:
        await _get_tool(mcp, "coord_ack")(CoordAckInput(message_ids=[posted["message_id"]]), ctx=None)
        await _get_tool(mcp, "coord_ack")(CoordAckInput(message_ids=[posted["message_id"]]), ctx=None)
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
            CoordStatusInput(summary="working on auth packet"), ctx=None,
        )
        row = get_message(cfg.server.db_path, result["message_id"])
        assert row["to_agent"] == "broadcast"
        assert row["kind"] == "status"
        assert row["notified_at"] is None  # status never notifies
    finally:
        _current_agent.reset(token)
```

- [ ] **Step 2: Run tests pass**

```bash
pytest tests/test_tools.py -v
```

Expected: 6 passed.

If `mcp._tool_manager._tools` access fails (SDK version drift), surface and replace with the current accessor. The known-good alternative: `await mcp.call_tool(name, params)`, but that adds session overhead — keep direct fn access for unit tests.

- [ ] **Step 3: Commit**

```bash
git add tests/test_tools.py
git commit -m "test(server): direct tool unit tests covering all 5 tools"
```

---

### Task 18: Verify the assembled ASGI app boots

**Files:**
- Modify: `tests/test_tools.py`

- [ ] **Step 1: Append a smoke-of-smoke test that builds the app and hits /health**

```python
def test_health_endpoint_returns_ok(temp_config):
    from starlette.testclient import TestClient
    from pfit_coord_mcp.server import build_app
    app = build_app(temp_config)
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body
```

- [ ] **Step 2: Run pass**

```bash
pytest tests/test_tools.py::test_health_endpoint_returns_ok -v
```

Expected: 1 passed.

- [ ] **Step 3: Append a test verifying /mcp requires auth**

```python
def test_mcp_endpoint_requires_auth(temp_config):
    from starlette.testclient import TestClient
    from pfit_coord_mcp.server import build_app
    app = build_app(temp_config)
    client = TestClient(app)
    r = client.post("/mcp", json={})
    assert r.status_code == 401
```

- [ ] **Step 4: Run pass**

```bash
pytest tests/test_tools.py -v
```

Expected: 6 + 2 = 8 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/test_tools.py
git commit -m "test(server): /health open + /mcp requires auth (assembled app)"
```

---

### Task 19: Run the full test suite + lint + mypy locally

- [ ] **Step 1: Full pytest**

```bash
pytest -v
```

Expected: 18 (store) + 9 (auth) + 13 (notify) + 4 (config) + 8 (tools) = 52 passed.

- [ ] **Step 2: Ruff**

```bash
ruff check .
```

Expected: clean. Fix any issues; do not blanket-ignore. If a true intentional pattern requires ignore, add a focused `per-file-ignores` entry with a comment explaining why (per the user's "don't dismiss linter warnings" feedback).

- [ ] **Step 3: Mypy strict**

```bash
mypy src
```

Expected: clean. Fix typing as needed; don't add `# type: ignore` without a comment justifying it.

- [ ] **Step 4: Commit any cleanup**

If any ruff/mypy fixes were needed:

```bash
git add -A
git commit -m "chore: ruff + mypy cleanup"
```

If nothing changed, skip the commit.

---

### Task 20: Manual server smoke (boot + curl)

- [ ] **Step 1: Generate three real bearer tokens**

```bash
python -c "import secrets; print('claude-web:', secrets.token_urlsafe(32))"
python -c "import secrets; print('claude-code:', secrets.token_urlsafe(32))"
python -c "import secrets; print('codex:', secrets.token_urlsafe(32))"
```

Save the three tokens to a scratch file (`scratch-tokens.txt` — gitignored via the broad `.env*` rule? No — add explicitly to `.gitignore` if not already covered):

```bash
echo "scratch-tokens.txt" >> .gitignore
```

Paste the three lines into `scratch-tokens.txt`. Do NOT commit.

- [ ] **Step 2: Create local `config.toml` from example**

```bash
cp config.toml.example config.toml
```

Edit `config.toml`:
- Replace the three `REPLACE_WITH_GENERATED_TOKEN_*` keys with the three real tokens from Step 1
- Leave Pushover values as `REPLACE_WITH_*` for now (config.py forces dry_run=true when they're empty/literal placeholders — ah, but `REPLACE_WITH_*` is non-empty. Set them to empty strings until Alex pastes real values.)

Set `pushover.user_key = ""` and `pushover.app_token = ""` for the smoke test, OR set `dry_run = true` explicitly.

- [ ] **Step 3: Boot the server**

```bash
COORD_CONFIG=./config.toml python -m pfit_coord_mcp.server &
SERVER_PID=$!
sleep 2
```

- [ ] **Step 4: Hit /health**

```bash
curl -s http://localhost:8765/health | python -m json.tool
```

Expected:
```json
{
    "status": "ok",
    "version": "0.1.0"
}
```

- [ ] **Step 5: Hit /mcp without auth**

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8765/mcp
```

Expected: `401`.

- [ ] **Step 6: Hit /mcp with bad token**

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer notreal" http://localhost:8765/mcp
```

Expected: `401`.

- [ ] **Step 7: Hit /mcp with the claude-web token + a JSON-RPC initialize request**

```bash
TOKEN=$(grep claude-web: scratch-tokens.txt | cut -d' ' -f2)
curl -s -X POST http://localhost:8765/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke-curl","version":"0.0.1"}}}'
```

Expected: an SSE stream or a JSON response containing `serverInfo.name = "pfit_coord_mcp"`. If the SDK rejects with an error about missing required init fields, surface and adapt to current SDK schema; do not paper over.

- [ ] **Step 8: Stop the server**

```bash
kill $SERVER_PID
```

- [ ] **Step 9: Commit nothing — this was a manual verification**

If the smoke uncovered a bug, fix it in a small commit before moving on.

---

## Phase 6 — CLI

### Task 21: `cli.py` — `read` and `tail` commands

**Files:**
- Create: `src/pfit_coord_mcp/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

```python
"""CLI tests."""
from __future__ import annotations

import json

from click.testing import CliRunner

from pfit_coord_mcp.cli import main as cli
from pfit_coord_mcp.store import post_message


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
    r = runner.invoke(cli, [
        "post",
        "--from-agent", "alex",
        "--to", "claude-code",
        "--kind", "answer",
        "--text", "go ahead",
    ])
    assert r.exit_code == 0
    # Verify via direct DB read
    from pfit_coord_mcp.store import read_messages
    rows = read_messages(temp_db, to_agent="claude-code")
    assert any(r_["from_agent"] == "alex" for r_ in rows)
```

- [ ] **Step 2: Run tests fail**

```bash
pytest tests/test_cli.py -v
```

Expected: ImportError on `cli`.

- [ ] **Step 3: Write `src/pfit_coord_mcp/cli.py`**

```python
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
                payload.get("text") or payload.get("summary")
                or payload.get("question") or json.dumps(payload)
            )
        except Exception:  # noqa: BLE001  # any malformed payload falls through to raw
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
def read(as_agent: str, since_id: int | None, thread_id: str | None,
         kinds: tuple[str, ...], unread: bool, limit: int) -> None:
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
        t.add_row(r["id"], r["title"], r["created_by"], r["created_at"], "yes" if r["closed"] else "no")
    console.print(t)


@main.command(name="thread-create")
@click.option("--title", required=True)
@click.option("--created-by", default="alex")
def thread_create(title: str, created_by: str) -> None:
    """Create a thread."""
    tid = create_thread(_db_path(), title=title, created_by=created_by)
    click.echo(tid)
```

- [ ] **Step 4: Run tests pass**

```bash
pytest tests/test_cli.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/pfit_coord_mcp/cli.py tests/test_cli.py
git commit -m "feat(cli): coord-cli read/tail/post/threads/thread-create"
```

---

### Task 22: CLI manual smoke

- [ ] **Step 1: Verify the entry point is installed**

```bash
which coord-cli  # macOS/Linux
# or
where.exe coord-cli  # Windows
```

Expected: a path inside `.venv/`.

- [ ] **Step 2: Create a thread, post, read**

```bash
coord-cli thread-create --title "smoke test"
# capture the returned thread id, e.g. thr-AbCd
coord-cli post --from-agent alex --to claude-code --kind note --text "test message" --thread thr-AbCd
coord-cli read --as-agent claude-code
```

Expected: rich table showing the message.

- [ ] **Step 3: Commit nothing (manual verification)**

---

### Task 23: Type-check the CLI

- [ ] **Step 1: Mypy on src/**

```bash
mypy src
```

Expected: clean. Fix any errors. The `_render_messages` function takes `list[Any]` due to sqlite3.Row typing; if mypy complains, narrow with TYPE_CHECKING blocks rather than blanket `Any`.

- [ ] **Step 2: Commit any fixes**

```bash
git add -A
git commit -m "chore(cli): mypy fixes"
```

(Skip if no changes.)

---

## Phase 7 — Local dev tooling (Docker, compose, Make)

### Task 24: `Dockerfile`

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`

- [ ] **Step 1: Write `Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# System deps for httpx (no special needs) — slim image is sufficient.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy only metadata first to leverage layer caching for deps.
COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

# Runtime data dir; mounted at compose level for persistence.
RUN mkdir -p /app/data

EXPOSE 8765

# Bind 0.0.0.0 inside the container; docker-compose maps the host port to 127.0.0.1
# so the host-side socket is not internet-reachable. cloudflared connects via loopback.
CMD ["python", "-m", "pfit_coord_mcp.server"]
```

- [ ] **Step 2: Write `.dockerignore`**

```text
.git
.github
.venv
.pytest_cache
.mypy_cache
.ruff_cache
__pycache__
*.pyc
data/*.db
data/*.db-wal
data/*.db-shm
.env
config.toml
docs/
tests/
scratch-*
```

- [ ] **Step 3: Build the image**

```bash
docker build -t pfit-coord-mcp:dev .
```

Expected: build succeeds. If Python 3.12 base image rejects `mcp[cli]>=1.0`, surface and STOP.

- [ ] **Step 4: Commit**

```bash
git add Dockerfile .dockerignore
git commit -m "feat(docker): runtime image"
```

---

### Task 25: `docker-compose.yml`

**Files:**
- Create: `docker-compose.yml`

- [ ] **Step 1: Write `docker-compose.yml`**

```yaml
services:
  coord-mcp:
    build: .
    image: pfit-coord-mcp:dev
    container_name: pfit-coord-mcp
    # Bind to 127.0.0.1 only — never expose this socket to the LAN. The
    # public surface is mediated by Cloudflare Tunnel (running on the host),
    # not by this port mapping.
    ports:
      - "127.0.0.1:8765:8765"
    volumes:
      - ./data:/app/data
      - ./config.toml:/app/config.toml:ro
    environment:
      COORD_CONFIG: /app/config.toml
      COORD_LOG_LEVEL: INFO
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8765/health').read()"]
      interval: 30s
      timeout: 5s
      retries: 3
```

- [ ] **Step 2: Bring it up**

```bash
docker compose up -d
sleep 3
curl -s http://localhost:8765/health
docker compose down
```

Expected: `/health` returns the version JSON; container shuts down clean.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(compose): localhost-only port mapping with healthcheck"
```

---

### Task 26: `Makefile`

**Files:**
- Create: `Makefile`

- [ ] **Step 1: Write `Makefile`**

```makefile
.PHONY: install up down logs test lint typecheck clean tunnel build

install:
	pip install -e ".[dev]"

up:
	docker compose up -d
	@echo "Server: http://localhost:8765 (health: /health)"

down:
	docker compose down

logs:
	docker compose logs -f

test:
	pytest -v

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .

typecheck:
	mypy src

build:
	docker build -t pfit-coord-mcp:dev .

tunnel:
	cloudflared tunnel run pfit-coord

clean:
	rm -rf data/*.db data/*.db-wal data/*.db-shm
	docker compose down -v
```

- [ ] **Step 2: Verify each target runs**

```bash
make lint
make typecheck
make test
```

Expected: all clean. If `ruff format --check` complains, run `make format` and re-add.

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "chore: makefile for common dev tasks"
```

---

## Phase 8 — End-to-end smoke test

### Task 27: ASGI-level round-trip via TestClient + mocked Pushover

**Files:**
- Create: `tests/test_smoke_e2e.py`

The smoke test exercises the assembled app via Starlette TestClient (in-process — no real socket, no real subprocess). It does NOT hit a real MCP JSON-RPC initialize handshake (FastMCP's session lifecycle is not the test target here — coverage of that is the manual smoke in Task 20). Instead, it tests the full middleware → tool → store → notify chain by using the same direct-tool access pattern from Task 17, but with Pushover mocked at the httpx layer and the assembled `build_app` ensuring the auth+origin+context wiring is correct end-to-end.

- [ ] **Step 1: Write the test**

```python
"""End-to-end round-trip: post stop_and_ask -> notify fires -> read as another agent -> ack -> reply."""
from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from pfit_coord_mcp.config import Config, PushoverConfig, ServerConfig
from pfit_coord_mcp.models import (
    CoordAckInput,
    CoordPostInput,
    CoordReadInput,
)
from pfit_coord_mcp.notify import PUSHOVER_URL
from pfit_coord_mcp.server import _current_agent, build_app, build_mcp
from pfit_coord_mcp.store import get_message, init_db


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
        method="POST", url=PUSHOVER_URL,
        json={"status": 1, "request": "ok"}, status_code=200,
    )
    mcp = build_mcp(live_config)
    posted_id: int | None = None

    # 1) codex posts a stop_and_ask to alex
    token = _current_agent.set("codex")
    try:
        post_fn = mcp._tool_manager._tools["coord_post"].fn
        result = await post_fn(
            CoordPostInput(
                to_agent="alex", kind="stop_and_ask",
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

    # 2) claude-web reads the queue (sees the message addressed to alex per packet rule:
    #    any client can read any message; to_agent is a routing hint, not access control)
    token = _current_agent.set("claude-web")
    try:
        read_fn = mcp._tool_manager._tools["coord_read"].fn
        # claude-web only sees messages addressed to claude-web or broadcast — by design.
        # The cross-agent visibility ("alex can be read by claude-web on alex's behalf")
        # comes from the human pasting/asking in the chat, not from the read API.
        # So the smoke test reads as ALEX (acting on alex's behalf during the chat).
        pass
    finally:
        _current_agent.reset(token)

    token = _current_agent.set("alex")
    try:
        read_fn = mcp._tool_manager._tools["coord_read"].fn
        # NOTE: alex doesn't have a bearer token at the MCP layer — it's a recipient
        # identity. The CLI reads alex's messages directly from SQLite. Reading via
        # the tool here exercises the route-by-recipient logic regardless.
        result = await read_fn(CoordReadInput(), ctx=None)
        assert any(m["id"] == posted_id for m in result["messages"]), \
            f"expected posted message in alex's queue; got {result}"
    finally:
        _current_agent.reset(token)

    # 3) ack as alex
    token = _current_agent.set("alex")
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
                to_agent="codex", kind="answer",
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
```

- [ ] **Step 2: Run pass**

```bash
pytest tests/test_smoke_e2e.py -v
```

Expected: 4 passed.

- [ ] **Step 3: Run the FULL suite**

```bash
pytest -v
```

Expected: 52 (Task 19) + 4 (smoke) = 56 passed.

- [ ] **Step 4: Commit**

```bash
git add tests/test_smoke_e2e.py
git commit -m "test(smoke): end-to-end round-trip with mocked pushover"
```

---

## Phase 9 — Docs

### Task 28: `docs/cloudflare-tunnel.md`

**Files:**
- Create: `docs/cloudflare-tunnel.md`

- [ ] **Step 1: Write the doc**

````markdown
# Cloudflare Tunnel Setup

The coordination server runs locally and is exposed at `https://mcp.asquaredhome.com`
via Cloudflare Tunnel. No port forwarding, no firewall changes. DNS for
`asquaredhome.com` is already managed by Cloudflare.

This doc is for Alex to follow on the workstation that hosts the server.
Verify each `cloudflared` command against `cloudflared --help` before running —
flags shift between point releases.

## Prerequisites

- `cloudflared` CLI installed:
  - **Windows:** download from <https://github.com/cloudflare/cloudflared/releases>
  - **macOS:** `brew install cloudflare/cloudflare/cloudflared`
  - **Linux:** see the GitHub releases page for the package matching your distro.
- A Cloudflare account with `asquaredhome.com` already on the dashboard.

## One-time setup

### 1. Authenticate

```bash
cloudflared tunnel login
```

A browser window opens; pick `asquaredhome.com`. A cert is written to
`~/.cloudflared/cert.pem` (Windows: `%USERPROFILE%\.cloudflared\cert.pem`).

### 2. Create the tunnel

```bash
cloudflared tunnel create pfit-coord
```

Returns a tunnel ID and writes credentials to
`~/.cloudflared/<tunnel-id>.json`. Note the ID — you need it in the config below.

### 3. Route DNS

```bash
cloudflared tunnel route dns pfit-coord mcp.asquaredhome.com
```

Adds a CNAME in Cloudflare DNS pointing `mcp.asquaredhome.com` to the tunnel.

### 4. Write the config file

Create `~/.cloudflared/config.yml`:

```yaml
tunnel: pfit-coord
credentials-file: /Users/<you>/.cloudflared/<tunnel-id>.json   # absolute path
# Windows example:
# credentials-file: C:\Users\<you>\.cloudflared\<tunnel-id>.json

ingress:
  - hostname: mcp.asquaredhome.com
    service: http://localhost:8765
    originRequest:
      connectTimeout: 30s
      # MCP streamable HTTP uses long-lived SSE responses for streaming tool
      # results. Keep chunked encoding ON (the default) so SSE flushes through.
      disableChunkedEncoding: false
  - service: http_status:404
```

## Running

### Foreground (debugging)

```bash
make tunnel
# or directly:
cloudflared tunnel run pfit-coord
```

### Background as a system service

```bash
# macOS/Linux:
sudo cloudflared service install
sudo systemctl enable --now cloudflared    # Linux
# macOS uses launchd via the install command above.

# Windows:
cloudflared service install
```

## Verification

```bash
# Reaches the server via the tunnel; auth required, so 401 is correct:
curl -i https://mcp.asquaredhome.com/mcp
# Expect: HTTP/2 401

# Health bypasses auth:
curl https://mcp.asquaredhome.com/health
# Expect: {"status": "ok", "version": "0.1.0"}
```

## Stopping

- Service: `sudo cloudflared service uninstall` (or `cloudflared service uninstall` on Windows)
- Foreground: Ctrl-C

## Notes

- Cloudflare Tunnel custom hostnames on a domain you own are free.
- SSE / long-lived HTTP work through tunnels by default. The `originRequest`
  block above sets a generous connect timeout to avoid premature disconnects.
- When `cloudflared` restarts, in-flight long-lived connections drop — clients
  reconnect automatically per MCP spec resumability rules.
````

- [ ] **Step 2: Commit**

```bash
git add docs/cloudflare-tunnel.md
git commit -m "docs: cloudflare tunnel setup walkthrough"
```

---

### Task 29: Three agent integration docs

**Files:**
- Create: `docs/claude-code-setup.md`
- Create: `docs/codex-setup.md`
- Create: `docs/claude-web-connector-setup.md`

- [ ] **Step 1: Write `docs/claude-code-setup.md`**

````markdown
# Claude Code Setup

## 1. Add the MCP server to your Claude Code config

In your Claude Code MCP config (typical paths: `~/.claude/mcp.json` on macOS/Linux,
`%USERPROFILE%\.claude\mcp.json` on Windows — verify with `claude --help` if unsure):

```json
{
  "mcpServers": {
    "pfit-coord": {
      "url": "https://mcp.asquaredhome.com/mcp",
      "headers": {
        "Authorization": "Bearer <CLAUDE_CODE_TOKEN>"
      }
    }
  }
}
```

Replace `<CLAUDE_CODE_TOKEN>` with the token from your local `config.toml`
mapped to `claude-code`.

## 2. Verify

In a Claude Code session:

> **You:** What MCP tools do you have available from pfit-coord?

Expected: `coord_post`, `coord_read`, `coord_threads`, `coord_ack`, `coord_status`.

## 3. First message

> **You:** Use coord_status to broadcast that you're online.

Then verify from the host shell:

```bash
coord-cli read --as-agent broadcast
```

You should see a `status` message from `claude-code`.
````

- [ ] **Step 2: Write `docs/codex-setup.md`**

````markdown
# Codex Setup

The Codex CLI's MCP config location varies by version. Run `codex --help` or
check the official docs to confirm the correct file. As of writing the file is
typically `~/.codex/mcp.json` or under `~/.config/codex/`.

## 1. Add the MCP server

```json
{
  "mcpServers": {
    "pfit-coord": {
      "url": "https://mcp.asquaredhome.com/mcp",
      "headers": {
        "Authorization": "Bearer <CODEX_TOKEN>"
      }
    }
  }
}
```

Replace `<CODEX_TOKEN>` with the token from your local `config.toml`
mapped to `codex`.

## 2. Verify

In a Codex session:

> **You:** Read the coord queue.

Expected: Codex calls `coord_read` and returns whatever messages are
addressed to `codex` (or `broadcast`).

## 3. First message

> **You:** Use coord_post to send a stop_and_ask to alex with the question "test ping".

Within ~30 seconds Alex's phone should receive a Pushover notification with:
- Title: `[codex] stop_and_ask`
- Body: `test ping`
- Priority: high (bypasses quiet hours)
````

- [ ] **Step 3: Write `docs/claude-web-connector-setup.md`**

````markdown
# Claude Web Connector Setup

Claude Web (claude.ai) supports custom remote MCP connectors via your account settings.

## Steps

1. In Claude Web, navigate to **Settings → Connectors → Add Custom Connector**.
2. Fill in:
   - **Name:** `pfit-coord`
   - **URL:** `https://mcp.asquaredhome.com/mcp`
   - **Authentication:** Bearer token
   - **Token:** `<CLAUDE_WEB_TOKEN>` (from `config.toml`)
3. Save. Toggle the connector on for the chats where you want it (or set it
   as always-on).

## Verify

Start a new chat:

> **You:** What tools do you have available from pfit-coord?

Expected: `coord_post`, `coord_read`, `coord_threads`, `coord_ack`, `coord_status`.

## Important: Claude Web cannot autonomously poll

Claude Web only sees `coord_*` tool results when you actively chat. If Codex
posts a STOP-AND-ASK at midnight and Claude Web is needed to resolve, the loop is:

1. Pushover notifies Alex's phone.
2. Alex starts a chat with Claude Web.
3. Claude Web reads the queue.
4. Alex relays the response back through Claude Web.

This is by design. Notifications go to a phone, not to a chat session.
````

- [ ] **Step 4: Commit**

```bash
git add docs/claude-code-setup.md docs/codex-setup.md docs/claude-web-connector-setup.md
git commit -m "docs: agent integration walkthroughs (claude-code, codex, claude-web)"
```

---

### Task 30: `docs/azure-migration.md` and `docs/e2e-checklist.md`

**Files:**
- Create: `docs/azure-migration.md`
- Create: `docs/e2e-checklist.md`

- [ ] **Step 1: Write `docs/azure-migration.md`**

````markdown
# Azure Migration Plan

When local + Cloudflare Tunnel becomes a constraint (uptime, multi-developer
access, etc.), migrate to Azure App Service or Container Apps. This doc
captures the migration path. **Not yet built** — when the time comes, this
becomes the spec.

## What changes

- Server runs as a containerized App Service or Container App, not locally.
- DNS flips from Cloudflare Tunnel to Azure Front Door (or direct CNAME to
  the App Service hostname).
- Pushover token moves from local `config.toml` into Azure Key Vault.
- SQLite stays for now; Azure SQL migration is a separate decision.

## What stays the same

- Server code: zero changes.
- Tool API: zero changes.
- Agent configs: only the URL changes if the hostname changes (it doesn't if
  `mcp.asquaredhome.com` stays).

## Steps

1. Build container, push to Azure Container Registry.
2. Create App Service plan (B1 ~$13/mo, or P0v3 if usage justifies).
3. Deploy container to App Service with health-check path `/health`.
4. Mount Azure Files share at `/app/data` for SQLite persistence.
5. Add Pushover credentials as App Service config (or Key Vault references).
6. Verify: `curl https://<app-service>.azurewebsites.net/health`.
7. Update Cloudflare DNS: change CNAME for `mcp.asquaredhome.com` from the
   tunnel to the App Service hostname.
8. Confirm traffic flows; tear down the local Cloudflare Tunnel.

## Cost estimate

| Component                          | Cost (USD/mo) |
| ---------------------------------- | ------------- |
| App Service B1                     | ~$13          |
| Azure Files (small)                | ~$1           |
| Container Registry Basic           | ~$5           |
| **Total**                          | **~$19**      |

## Alternative: Container Apps with scale-to-zero

Cheaper for low-traffic personal use (~$5–10/mo). Trade-off: cold-start
latency on the first request after idle. Probably the right pick for v1
production.
````

- [ ] **Step 2: Write `docs/e2e-checklist.md`**

````markdown
# Post-deploy E2E checklist

Run after deploying the server (locally or via Cloudflare Tunnel) and
configuring all three agents. Replace `https://mcp.asquaredhome.com` with
`http://localhost:8765` if testing pre-tunnel.

## Server reachability
- [ ] `curl https://mcp.asquaredhome.com/health` → 200 with version JSON
- [ ] `curl https://mcp.asquaredhome.com/mcp` (no auth) → 401
- [ ] `curl -H "Authorization: Bearer <bad>" https://mcp.asquaredhome.com/mcp` → 401

## Agent: Claude Code
- [ ] Tools list includes `coord_post`, `coord_read`, `coord_threads`, `coord_ack`, `coord_status`
- [ ] "Use coord_status to broadcast that you're online" → posts a status message
- [ ] `coord-cli read --as-agent broadcast` shows the status

## Agent: Codex
- [ ] Tools list complete
- [ ] "Read the coord queue" → returns the broadcast status from Claude Code
- [ ] "Use coord_post to send a stop_and_ask to alex saying 'test ping'" → posts

## Pushover delivery
- [ ] Notification arrives on Alex's phone within 30s
- [ ] Title is `[codex] stop_and_ask`
- [ ] Body is `test ping`
- [ ] Priority is high (bypasses quiet hours)

## Agent: Claude Web (acting on Alex's behalf)
- [ ] "Anything in the coord queue for me?" → reads, finds the test ping
- [ ] "Reply to codex with answer 'noted'" → posts a kind=answer; no Pushover fires

## CLI
- [ ] `coord-cli tail --as-agent broadcast` shows live updates as messages flow

## Failure modes (sanity)
- [ ] Stop the server (`make down`); curl returns connection refused (or 502 via tunnel)
- [ ] Restart (`make up`); curl returns 200 again within ~10s
- [ ] Cloudflare Tunnel restart drops live SSE; clients reconnect on next tool call
````

- [ ] **Step 3: Commit**

```bash
git add docs/azure-migration.md docs/e2e-checklist.md
git commit -m "docs: azure migration plan + post-deploy e2e checklist"
```

---

### Task 31: `README.md`

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write the README**

````markdown
# pfit-coord-mcp

Coordination MCP server hosting a shared message queue between Claude Web,
Claude Code, and Codex. STOP-AND-ASK and handoff-to-alex messages page Alex's
phone via Pushover.

## What it does

```
                ┌─────────────┐
                │ Claude Web  │ ─┐
                └─────────────┘  │
                ┌─────────────┐  │   bearer auth
                │ Claude Code │ ─┼──────────────►  ┌──────────────────┐
                └─────────────┘  │   streamable    │  pfit-coord-mcp  │
                ┌─────────────┐  │     HTTP        │  (FastMCP +      │
                │   Codex     │ ─┘                  │   SQLite + auth) │
                └─────────────┘                     └────────┬─────────┘
                                                             │
                            ┌────────────────────────────────┤
                            │                                │
                            ▼                                ▼
                  ┌─────────────────┐              ┌──────────────────┐
                  │ Pushover (push  │              │ coord-cli (alex  │
                  │ to Alex's phone)│              │ reads queue from │
                  └─────────────────┘              │ host shell)      │
                                                   └──────────────────┘

   Public URL: https://mcp.asquaredhome.com  ←  Cloudflare Tunnel  ←  localhost:8765
```

Five MCP tools:

- `coord_post` — post a message addressed to one of the agents (or `broadcast`)
- `coord_read` — read messages addressed to your agent ID + broadcast
- `coord_threads` — create / list / close coordination threads
- `coord_ack` — mark messages as read
- `coord_status` — lightweight status heartbeat (broadcast, no notification)

Server-enforced notification rules:

| Kind            | Recipient | Pushover priority |
| --------------- | --------- | ----------------- |
| `stop_and_ask`  | any       | high (bypass DND) |
| `handoff`       | `alex`    | normal            |
| `task_complete` | `alex`    | normal            |
| `question`      | `alex`    | normal            |
| anything else   | —         | none              |

## Quickstart (host)

```bash
git clone https://github.com/zelladir/pfit-coord-mcp
cd pfit-coord-mcp

# 1. Generate three bearer tokens
python -c "import secrets; print(secrets.token_urlsafe(32))"  # x3

# 2. Copy + edit config
cp config.toml.example config.toml
# Paste tokens into [tokens] (replace REPLACE_WITH_GENERATED_TOKEN_*)
# Paste your Pushover user_key + app_token into [pushover]
# (If creds are empty, server auto-forces dry_run=true.)

# 3. Boot
make build
make up

# 4. Health check
curl http://localhost:8765/health

# 5. Optional: set up Cloudflare Tunnel for public URL
# See docs/cloudflare-tunnel.md
```

## Setup docs

- [Claude Code](docs/claude-code-setup.md)
- [Codex](docs/codex-setup.md)
- [Claude Web (claude.ai connectors)](docs/claude-web-connector-setup.md)
- [Cloudflare Tunnel](docs/cloudflare-tunnel.md)
- [Post-deploy E2E checklist](docs/e2e-checklist.md)
- [Azure migration plan (future)](docs/azure-migration.md)

## CLI

```bash
coord-cli read --as-agent alex                  # show alex's queue
coord-cli read --thread thr-abcd                # filter to a thread
coord-cli tail --as-agent broadcast             # follow live
coord-cli post --from-agent alex --to codex \
              --kind answer --text "yes"        # admin post (bypasses MCP auth)
coord-cli threads                               # list open threads
coord-cli thread-create --title "wave A"        # create
```

## Architecture

- **Transport:** MCP streamable HTTP (single endpoint, POST + GET, SSE for streamed responses).
- **Auth:** Bearer token at the Starlette middleware layer (3 tokens, one per
  client identity). The `alex` identity is recipient-only — humans don't auth
  to the MCP; Alex reads via the CLI.
- **DNS-rebinding defense:** Origin allowlist middleware (per MCP spec MUST).
- **Store:** SQLite WAL mode at `./data/coord.db`. Backup is "copy the file."
  No replication. If the DB dies, you've lost a coordination log, not real work.
- **Notifications:** Server-enforced rules dispatch via Pushover. Each message
  pushes at most once (`notified_at` is set even on failure to prevent retry loops).

## Safety notes

- **Tokens are secrets.** Don't commit `config.toml`. Rotate immediately if leaked.
- **The DB has all coordination history.** Treat it like a private log.
- **The tunnel exposes the server publicly.** Bearer auth is the only protection;
  rotate tokens if any client device is compromised.
- **Pushover usage limits change May 1, 2026** (per Pushover banner at build
  time). If you start hitting unexpected 429s, check the Pushover dashboard.

## Development

```bash
make install      # install in editable mode with dev deps
make test         # full pytest suite
make lint         # ruff check + format check
make typecheck    # mypy strict
make format       # ruff format
```

## License

MIT — see [LICENSE](LICENSE).
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: readme with quickstart, architecture, CLI, safety notes"
```

---

### Task 32: Lint + format the docs

- [ ] **Step 1: Run any markdown linters available locally**

If `markdownlint` is installed: `markdownlint docs/ README.md`. Otherwise skip — the docs were written carefully.

- [ ] **Step 2: Visually scan each doc for placeholder leftovers**

```bash
grep -rEn "TODO|TBD|REPLACE_WITH|<your|<you>|XXX|FIXME" docs/ README.md
```

The only legitimate `REPLACE_WITH_*` matches should be in `config.toml.example`.
Any other matches in shipped docs are bugs — fix them.

- [ ] **Step 3: Commit any cleanup**

(Likely none.)

---

## Phase 10 — CI + PR

### Task 33: GitHub Actions CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Write the workflow**

```yaml
name: CI

on:
  push:
    branches:
      - main
  pull_request:

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install package + dev deps
        run: python -m pip install -e ".[dev]"

      - name: Ruff lint
        run: python -m ruff check src tests

      - name: Ruff format check
        run: python -m ruff format --check src tests

      - name: Mypy
        run: python -m mypy src

      - name: Pytest
        run: python -m pytest -v

      - name: Build wheel (smoke)
        run: python -m pip wheel --no-deps -w dist .
```

- [ ] **Step 2: Push the branch and verify CI is green**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: single validate job (lint, typecheck, test, wheel build)"
git push -u origin claude/coord-mcp-initial-build
```

Then watch:

```bash
gh pr checks --watch
```

(There's no PR yet, so use `gh run watch` against the most recent run.)

```bash
gh run list --branch claude/coord-mcp-initial-build --limit 1
gh run watch <run-id>
```

Expected: green. If anything fails, fix and push another commit. Don't open the
PR until CI is green on the branch.

---

### Task 34: Open the PR

- [ ] **Step 1: Open the PR**

```bash
gh pr create --title "Initial build: three-way coordination MCP server" --body "$(cat <<'EOF'
## Summary

- Build the three-way coordination MCP server per PACKET-COORD-MCP-01.
- Five MCP tools (`coord_post`, `coord_read`, `coord_threads`, `coord_ack`, `coord_status`) over streamable HTTP transport with Bearer-token auth + Origin allowlist.
- SQLite WAL store, Pushover notifications (rule-driven, deduplicated), CLI for direct DB access, Docker + docker-compose, full pre-deploy CI.

## Notable decisions / deviations from the packet

- **Added Origin-allowlist middleware** (not in packet). MCP streamable HTTP spec lists Origin validation as a MUST for DNS-rebinding defense; mandatory once a public tunnel is involved. Implemented as a sibling middleware to `BearerTokenMiddleware`; bypasses `/health`; allows requests with no Origin (CLI / curl).
- **`pushover.dry_run` is auto-forced True when creds are empty** (defensive default in `config.py`). Prevents accidental no-op pushes if someone clears creds without flipping the flag.
- **Container binds to `0.0.0.0:8765` inside, but `docker-compose` maps the host port to `127.0.0.1:8765` only.** Spec recommends localhost binding for local servers; this satisfies that without breaking Docker.
- **Python target bumped from 3.11 to 3.12** to match v2 repo convention.
- **Tool annotations (`readOnlyHint` etc.) omitted** — current SDK README does not document them. If they become first-class in a later SDK release, add in a follow-up.
- **Cross-recipient reads kept open per packet section 7.2** — any authenticated client can read any message; `to_agent` is a routing hint, not access control.

## Test coverage

- `test_config.py` (4) — TOML loader + agent-id validation + dry-run safeguard
- `test_store.py` (18) — schema, post/read filters, ack idempotency, notify tracking, threads
- `test_auth.py` (9) — bearer paths, origin allowlist, scope-state propagation
- `test_notify.py` (13) — rule matcher, dry-run, live (mocked) Pushover, truncation, error paths
- `test_tools.py` (8) — direct unit tests on each tool + assembled `/health` and `/mcp` 401
- `test_smoke_e2e.py` (4) — assembled-app round-trip with mocked Pushover (post → notify → read → ack → reply)

Total: 56 tests.

## Heads-up for follow-up

- **Pushover banner: "API usage limit changes coming May 1st, 2026"** (build was 2026-04-24). Monitor the Pushover dashboard after the change lands; if free-tier limits drop materially, factor into Azure migration timing.
- Cloudflare Tunnel setup is a manual post-merge task by Alex (per packet — agent doesn't have CF credentials). Doc walks through it.
- Real bearer tokens were generated locally during smoke testing; they live in `config.toml` (gitignored) and `scratch-tokens.txt` (gitignored). Alex regenerates / reuses as needed when configuring agents.
- The Pushover credentials slot is empty in the committed `config.toml.example`; Alex pastes real values into local `config.toml` post-merge.

## Test plan
- [ ] CI passes (lint, typecheck, pytest, wheel build)
- [ ] `make build && make up` boots the container; `/health` returns 200
- [ ] Walk the `docs/e2e-checklist.md` after Cloudflare Tunnel is configured

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 2: Watch CI**

```bash
gh pr checks --watch
```

Expected: green.

- [ ] **Step 3: Report back to Alex**

Print to the user:

- Repo URL: `https://github.com/zelladir/pfit-coord-mcp`
- PR URL: (output of `gh pr view --json url -q .url`)
- Test count: 56 (4 config + 18 store + 9 auth + 13 notify + 8 tools + 4 smoke)
- Deviations from packet (see PR body)
- Pushover prereq status: Alex has creds; pastes into local `config.toml` post-merge
- Cloudflare Tunnel status: not yet created — follow-up task per `docs/cloudflare-tunnel.md`
- Setup-doc paths: `docs/claude-code-setup.md`, `docs/codex-setup.md`, `docs/claude-web-connector-setup.md`
- Token generation: three real tokens generated locally in `scratch-tokens.txt`; never committed; never sent to Alex via this conversation
- Manual steps before live: (1) merge PR, (2) paste Pushover creds into local `config.toml`, (3) follow `docs/cloudflare-tunnel.md`, (4) configure each agent per its setup doc, (5) walk `docs/e2e-checklist.md`

- [ ] **Step 4: Wait for Alex review + merge**

Do not merge yourself. Alex reviews and merges. Codex post-build review (per packet) happens after merge.

---

## Final verification (before announcing PR ready)

- [ ] `make install` clean in fresh venv on Python 3.12
- [ ] `make test` — 56 passed
- [ ] `make lint` — ruff clean, format clean
- [ ] `make typecheck` — mypy strict clean
- [ ] `make build` — Docker image builds
- [ ] `make up` — container starts, `/health` returns 200, `/mcp` without auth returns 401
- [ ] `coord-cli read --as-agent alex` runs without error
- [ ] All four setup docs render (open in your editor's preview, scan)
- [ ] `grep -rEn "TODO|TBD|FIXME" src/ tests/ docs/ README.md` — no hits outside legitimate `REPLACE_WITH_*` in `config.toml.example`
- [ ] `.gitignore` excludes `.env`, `config.toml`, `data/*.db*`, `scratch-tokens.txt`
- [ ] CI green on the branch before opening PR

If any of the above fail, fix and re-run before opening.
