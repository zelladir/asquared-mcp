# Security & Protocol Review — pfit-coord-mcp

> **Historical note:** this review was written when the project was named
> `pfit-coord-mcp`. The active code now lives at `src/asquared_mcp/` after
> the 2026-05-17 rename; the substantive findings still apply.

**Date:** 2026-04-27  
**Reviewer:** Codex 5.5 via PACKET-COORD-MCP-02  
**Scope:** `main` at SHA `a585e6f2be0a7eb92dc7b947183fc2cff85a0c5c`; server, middleware, tools, store, CLI, docs, Docker, CI, tracked history.  
**Reference baselines:** OWASP API Security Top 10 2023 (<https://owasp.org/API-Security/editions/2023/en/0x11-t10/>); MCP Streamable HTTP transport spec 2025-06-18 (<https://modelcontextprotocol.io/specification/2025-06-18/basic/transports#streamable-http>); Pushover Message API (<https://pushover.net/api>).

## Summary

- Findings: 10 (0 critical / 3 high / 4 medium / 3 low / 0 info)
- Go-live impact: 3 `blocks_go_live` findings, all fixed in this PR; 7 `fix_next_session`
- Fixed in this PR: 8
- Deferred: 2
- Tim/Alex decisions: 0

**Go-live recommendation:** Track A5 may proceed after this PR merges and the server is redeployed. The pre-fix `blocks_go_live` issues were: documented `/mcp` was not a working MCP endpoint, hosted Claude Web origins were blocked, and Claude Web could not read Alex-addressed messages.

## Findings

### F-001 (severity: high, area: protocol, impact: blocks_go_live)

**Location:** `src/pfit_coord_mcp/server.py:278`  
**Evidence:** Pre-fix app mounted the FastMCP Starlette app at `/mcp` even though FastMCP's own streamable route is `/mcp`, so authenticated `POST /mcp` reached 404. Once remounted, the SDK session manager also needed an outer lifespan hook or it raised "Task group is not initialized."  
**Recommendation:** Expose exactly one Streamable HTTP endpoint at `/mcp`, preserve the SDK lifespan, and cover authenticated initialize at that documented path.  
**Disposition:** Fixed in this PR. `Mount("/", app=mcp_asgi)` plus `lifespan=lambda app: mcp.session_manager.run()` now serves `/mcp`; tests assert initialize succeeds at `/mcp`.

### F-002 (severity: high, area: cors/protocol, impact: blocks_go_live)

**Location:** `src/pfit_coord_mcp/auth.py:76`; `src/pfit_coord_mcp/server.py:92`; `config.toml.example:30`  
**Evidence:** Literal configured allowlist was `https://mcp.asquaredhome.com`, `http://localhost:8765`, and `http://127.0.0.1:8765`. Pre-fix middleware required exact Origin matches, and FastMCP's default DNS-rebinding settings allowed only localhost hosts/origins. A hosted Claude Web connector with a rotating Origin would be rejected before auth/tool negotiation.  
**Recommendation:** Keep local browser DNS-rebinding protection, but trust requests that arrive for the configured public tunnel host; do not depend on knowing Claude Web's exact Origin. Avoid returning the supplied Origin in error bodies.  
**Disposition:** Fixed in this PR. Origin handling now allows hosted-client Origins when `Host` is a configured public HTTPS hostname, keeps local unmatched Origins blocked, and disables the SDK's narrower duplicate host/origin filter in favor of this middleware. Full-app tests cover `https://mcp.asquaredhome.com/mcp` with `Origin: https://claude.ai`.

### F-003 (severity: medium, area: auth, impact: fix_next_session)

**Location:** `src/pfit_coord_mcp/auth.py:33`  
**Evidence:** Pre-fix token resolution used direct dictionary lookup of the presented bearer token and returned different 401 messages for missing/malformed vs unknown tokens.  
**Recommendation:** Use `secrets.compare_digest` over configured tokens, reject whitespace-mutated bearer values, and return one generic unauthorized body for all auth failures.  
**Disposition:** Fixed in this PR. Auth tests cover `compare_digest`, generic 401 bodies, malformed whitespace, and query-string tokens not being accepted.

### F-004 (severity: high, area: authorization, impact: blocks_go_live)

**Location:** `src/pfit_coord_mcp/server.py:161`; `src/pfit_coord_mcp/store.py:164`  
**Evidence:** The packet says any authenticated client can read the shared queue and `to_agent` is a routing hint. Pre-fix `coord_read` called `read_messages(..., to_agent=agent_id)`, so Claude Web could not read a STOP-AND-ASK addressed to `alex`.  
**Recommendation:** Preserve server-derived `from_agent`, but make MCP `coord_read` read the shared queue while keeping CLI recipient filtering available for Alex's shell workflow.  
**Disposition:** Fixed in this PR. Store reads accept `to_agent=None` for shared queue reads, `coord_read` uses that path, and unread filtering still keys off the authenticated reader for read receipts.

### F-005 (severity: medium, area: input, impact: fix_next_session)

**Location:** `src/pfit_coord_mcp/models.py:25`  
**Evidence:** Pre-fix `coord_post.payload` was unbounded `dict[str, Any]`; `thread_id` had no length/character restriction; `coord_threads.title` had no cap; `coord_read.limit` was only capped in the store layer, not reflected in the MCP schema.  
**Recommendation:** Cap serialized payload JSON at 64 KiB, restrict thread IDs to `[A-Za-z0-9_-]` up to 200 chars, cap thread titles, and expose `limit <= 200` in the schema.  
**Disposition:** Fixed in this PR. Pydantic validators/fields enforce these limits and tests cover oversized/unsafe values.

### F-006 (severity: low, area: secret, impact: fix_next_session)

**Location:** `src/pfit_coord_mcp/notify.py:109`  
**Evidence:** Pre-fix Pushover failures stored and returned `str(e)`. Pushover 4xx bodies include an `errors` array and may echo invalid identifiers; carrying raw exception detail into message rows/tool output is unnecessary risk. The code also did not check a JSON `status != 1` body on HTTP 200.  
**Recommendation:** Store/return generic error classes and status codes only; log no response body; treat Pushover `status != 1` as push failure.  
**Disposition:** Fixed in this PR. Tests verify 4xx error bodies are not stored and `status: 0` is handled.

### F-007 (severity: low, area: protocol, impact: fix_next_session)

**Location:** `src/pfit_coord_mcp/server.py:99`  
**Evidence:** Pre-fix FastMCP tool metadata had `annotations: None` for all tools, so clients could not tell read-only vs write/destructive behavior from metadata.  
**Recommendation:** Add conservative MCP tool annotations: `coord_read` read-only, write tools not read-only, and `coord_threads` destructive because the combined tool can close threads.  
**Disposition:** Fixed in this PR. Tests assert the security-relevant annotations.

### F-008 (severity: low, area: secret, impact: fix_next_session)

**Location:** `README.md:61`; `.gitignore:28`  
**Evidence:** Setup did not document restrictive local permissions for `config.toml`. The build plan referenced local `scratch-tokens.txt`, but `.gitignore` did not ignore it.  
**Recommendation:** Document `chmod 600 config.toml` on macOS/Linux and make the scratch token file untracked by default.  
**Disposition:** Fixed in this PR.

### F-009 (severity: medium, area: ops, impact: fix_next_session)

**Location:** `src/pfit_coord_mcp/store.py:60`; `src/pfit_coord_mcp/server.py:122`  
**Evidence:** SQLite lock simulation raised `OperationalError: database is locked` after about 5.6 seconds. Deleting the DB file after startup led to `OperationalError: no such table: messages`. These propagate as generic server errors rather than structured 503/retry guidance.  
**Recommendation:** In a follow-up, catch `sqlite3.OperationalError` at the tool boundary and translate lock/contention to structured retryable errors; decide whether missing schema should recreate DB or fail closed.  
**Disposition:** Deferred. This is real ops hardening but not a Track A blocker for a single-user coordination queue.

### F-010 (severity: medium, area: ops, impact: fix_next_session)

**Location:** `src/pfit_coord_mcp/server.py:122`  
**Evidence:** There is no rate limit on `coord_post`; a compromised valid token could fill SQLite and trigger Pushover usage.  
**Recommendation:** Follow up with a no-new-dependency limiter or SQLite-backed per-agent quota if abuse becomes plausible; immediate mitigation is manual token rotation.  
**Disposition:** Deferred. Packet forbids adding a rate-limit dependency in this PR.

## Origin Matrix

| Scenario | Pre-fix | Post-fix | Rationale |
| --- | --- | --- | --- |
| No `Origin`, localhost Host | Allowed | Allowed | CLI, curl, and local MCP clients often omit Origin. |
| `Origin: http://localhost:8765`, localhost Host | Allowed | Allowed | Explicit local development origin. |
| `Origin: https://mcp.asquaredhome.com`, public Host | Blocked by FastMCP default Host allowlist | Allowed | Public tunnel hostname is configured. |
| Hosted Origin such as `https://claude.ai`, public Host | Blocked | Allowed | Does not require knowing Anthropic's rotating connector Origin. |
| Hosted/attacker Origin, localhost Host | Blocked | Blocked | Maintains local DNS-rebinding defense. |
| Any Origin, missing/wrong bearer | 401 or earlier 403 | 401 or earlier 403 | Origin is checked first; auth remains required for MCP routes. |

## Checklist Confirmations

- Authentication: missing, malformed, whitespace-mutated, unknown, and query-string tokens are rejected with JSON 401; lowercase `bearer` is accepted intentionally because HTTP auth schemes are case-insensitive.
- Authorization: `coord_post.from_agent` is server-derived from middleware context and not tool input; authenticated agents are peers for reads per packet design; `coord_ack` records the calling agent in `read_by` and read receipts remain non-authoritative.
- Input validation: `kind` and `to_agent` are literal-enum validated; malformed non-dict payloads are rejected; payload, thread ID, title, ack list, status summary, and read limit now have schema caps.
- Secret handling: no logger statements include configured bearer tokens, Pushover app token, or user key; `config.toml.example` contains placeholders only; `.gitignore` covers `.env`, `config.toml`, SQLite DB/WAL/SHM files, and now `scratch-tokens.txt`.
- History/artifacts: tracked files and git history scan found placeholders/test tokens only; no `config.toml`, `.env`, DB, WAL, SHM, or scratch token artifact is tracked.
- SQL/injection: store queries use parameter binding for user input. Dynamic SQL is limited to internally generated placeholders/constant clauses.
- MCP protocol: after fixes, authenticated initialize at `/mcp` succeeds with `Accept: application/json, text/event-stream`; FastMCP owns JSON-RPC response formatting and content-type validation; `/health` remains unauthenticated and returns only status/version.
- Pushover: endpoint and fields match the documented API (`https://api.pushover.net/1/messages.json`, `token`, `user`, `message`, `title`, `priority`); notification body remains capped at 1024 chars; push failure does not roll back the saved coordination message.
- CI/Docker/docs: CI installs package/dev deps, runs ruff, mypy, pytest, and wheel build without secrets. Dockerfile does not use build args or bake secrets; runtime config is mounted read-only from `config.toml`.

## OWASP API Security Mapping

- API1 Broken Object Level Authorization: shared queue reads are intentional for this peer-agent tool, now explicitly documented; no client can forge `from_agent`.
- API2 Broken Authentication: bearer-token comparison and generic failures fixed; token-in-query is not accepted.
- API3 Broken Object Property Level Authorization / excessive exposure: all authenticated clients can read payloads by design; treat DB/queue as private coordination history.
- API4 Unrestricted Resource Consumption: payload/read caps fixed; `coord_post` rate limiting remains deferred as F-010.
- API8 Security Misconfiguration: MCP path/lifespan and Origin/public-host behavior fixed; config examples are placeholders.

## Out-of-scope Items Observed

- The Docker image currently runs as the default container user. No secrets are baked into the image, and the public host port is bound to `127.0.0.1` in compose. Consider a non-root runtime user in a later hardening packet if this stops being a personal workstation service.
- Disk-full behavior was not practically simulated on this workstation. It is expected to surface as `sqlite3.OperationalError` under the same deferred handling bucket as F-009.

## Confirmation of Acceptable Design Choices

- Bearer tokens in local TOML remain acceptable for this phase; OAuth/mTLS/role models are intentionally out of scope.
- `/health` bypasses auth as specified and leaks no DB/env/secret state.
- Pushover failure is non-blocking for `coord_post`; messages persist even when push fails.
- `coord_status` is broadcast-only and does not notify.
- `coord_threads` is a combined create/list/close tool. Because annotations are tool-level, the review marks it conservatively destructive even though only `action="close"` is destructive.

## Verification Notes

- Local checks after fixes: `pytest -q` passed (75 tests), `ruff check .` passed, `ruff format --check .` passed, and `mypy --strict src/` passed.
- Literal `make test`, `make lint`, and `make typecheck` could not run because `make` is not installed on this Windows workstation. The equivalent Makefile commands were run directly through the repo `.venv`.
- `python -m pytest` from the system interpreter failed before install because the package was not on that interpreter's path. The repo `.venv` was used for verification.
- `pip-audit` was not installed in the repo `.venv`; no dependency changes were made in this packet.
