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
    ("stop_and_ask", "*"): 1,  # high priority, bypasses quiet hours
    ("handoff", "alex"): 0,
    ("task_complete", "alex"): 0,
    ("question", "alex"): 0,
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
            msg["kind"],
            msg["from_agent"],
            msg["to_agent"],
            priority,
            body_preview,
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
            if r.json().get("status") != 1:
                error = "pushover_status_not_1"
                logger.warning("Pushover request failed with non-success status field")
                mark_notified(config.server.db_path, message_id, error=error)
                return NotifyResult(notified=False, error=error, reason="push_failed")
    except httpx.HTTPStatusError as e:
        error = f"pushover_http_{e.response.status_code}"
        logger.warning("Pushover request failed with HTTP %s", e.response.status_code)
        mark_notified(config.server.db_path, message_id, error=error)
        return NotifyResult(notified=False, error=error, reason="push_failed")
    except httpx.RequestError as e:
        error = f"pushover_request_error:{e.__class__.__name__}"
        logger.warning("Pushover request failed with request error %s", e.__class__.__name__)
        mark_notified(config.server.db_path, message_id, error=error)
        return NotifyResult(notified=False, error=error, reason="push_failed")
    except Exception as e:
        error = f"pushover_error:{e.__class__.__name__}"
        logger.warning("Pushover request failed with unexpected error %s", e.__class__.__name__)
        mark_notified(config.server.db_path, message_id, error=error)
        return NotifyResult(notified=False, error=error, reason="push_failed")

    mark_notified(config.server.db_path, message_id, error=None)
    return NotifyResult(notified=True)
