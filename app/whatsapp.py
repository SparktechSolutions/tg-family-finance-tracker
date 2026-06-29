"""Thin WhatsApp Cloud API client + webhook payload helpers."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import settings

log = logging.getLogger("whatsapp")


def graph_url() -> str:
    return (
        f"https://graph.facebook.com/{settings.whatsapp_api_version}"
        f"/{settings.whatsapp_phone_number_id}/messages"
    )


async def send_text(to: str, body: str, recipient_type: str = "individual") -> None:
    """Send a text message. For groups, pass the group id as `to` and
    recipient_type='group' (Cloud API group messaging, available since May 2026).

    No-ops with a log line if no access token is configured (e.g. local dev).
    """
    if not settings.whatsapp_access_token:
        log.info("[dry-run send] to=%s type=%s body=%s", to, recipient_type, body)
        return

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": recipient_type,
        "to": to,
        "type": "text",
        "text": {"body": body},
    }
    headers = {"Authorization": f"Bearer {settings.whatsapp_access_token}"}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(graph_url(), json=payload, headers=headers)
        if resp.status_code >= 400:
            log.error("send failed %s: %s", resp.status_code, resp.text)


def extract_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a Cloud API webhook body into a list of normalized message dicts.

    Returns items shaped like:
        {
          "wa_message_id": str,
          "from": str,            # sender wa id
          "text": str,            # message text (empty for non-text)
          "timestamp": str,       # unix seconds as string
          "group_id": str | None, # present for group messages
          "type": str,
        }

    NOTE for Claude Code: the exact group-id field name/shape is new (May 2026 Groups API).
    Verify against a real webhook payload and adjust `_group_id_of` below if needed.
    """
    out: list[dict[str, Any]] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []):
                out.append(
                    {
                        "wa_message_id": msg.get("id"),
                        "from": msg.get("from"),
                        "text": (msg.get("text") or {}).get("body", "") or "",
                        "timestamp": msg.get("timestamp"),
                        "group_id": _group_id_of(msg, value),
                        "type": msg.get("type"),
                    }
                )
    return out


def extract_events(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull non-message lifecycle events (e.g. bot added to a group) from the webhook.

    NOTE for Claude Code: the Groups API lifecycle payload shape is new (May 2026).
    Verify the exact `field` name and participant structure against a real webhook and
    adjust the heuristics below. We look for group_lifecycle / group_participants changes.
    """
    out: list[dict[str, Any]] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            field = change.get("field", "")
            value = change.get("value", {})
            group_id = value.get("group_id") or (value.get("group") or {}).get("id")
            if "group_lifecycle" in field or "group_participants" in field:
                action = value.get("action") or value.get("event")
                if action in ("add", "join", "created", "bot_added") or \
                   value.get("bot_added") is True:
                    out.append({"type": "bot_added_to_group", "group_id": group_id})
    return out


def _group_id_of(msg: dict[str, Any], value: dict[str, Any]) -> str | None:
    # Defensive: support a few likely shapes until confirmed against live payloads.
    for key in ("group_id", "group", "recipient_group_id"):
        if key in msg:
            g = msg[key]
            return g.get("id") if isinstance(g, dict) else g
    ctx = msg.get("context") or {}
    if "group_id" in ctx:
        return ctx["group_id"]
    return value.get("group_id")
