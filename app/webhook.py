"""Webhook routes: Meta verification (GET) + message receiver (POST).

Receives group messages, parses expenses, persists them (deduped), runs commands,
and replies into the group.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, Request, Response

import json

from . import crud, ingest, onboarding
from .config import settings
from .db import SessionLocal
from .whatsapp import extract_events, extract_messages, send_text

log = logging.getLogger("webhook")
router = APIRouter()


@router.get("/webhook")
async def verify(request: Request) -> Response:
    """Meta calls this once to verify the endpoint. Echo hub.challenge if the token matches."""
    params = request.query_params
    if params.get("hub.mode") == "subscribe" and \
       params.get("hub.verify_token") == settings.whatsapp_verify_token:
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    return Response(content="verification failed", status_code=403)


@router.post("/webhook")
async def receive(request: Request) -> dict:
    """Receive message events. Returns 200 quickly so Meta doesn't retry-storm."""
    payload = await request.json()

    # Bot added to a group -> post a welcome so the family can run /start.
    for ev in extract_events(payload):
        if ev["type"] == "bot_added_to_group" and ev.get("group_id"):
            await send_text(ev["group_id"], onboarding.welcome_message(),
                            recipient_type="group")

    messages = extract_messages(payload)
    for m in messages:
        log.info("msg id=%s from=%s group=%s text=%r",
                 m["wa_message_id"], m["from"], m["group_id"], m["text"])
        # Durably record the raw message first; skip if already seen (Meta re-delivery).
        is_new = _record_event(m)
        if not is_new:
            continue
        reply = _process(m)
        if reply:
            target = m["group_id"] or m["from"]
            rtype = "group" if m["group_id"] else "individual"
            await send_text(target, reply, recipient_type=rtype)

    return {"status": "received", "count": len(messages)}


def _record_event(m: dict) -> bool:
    """Persist the raw message to the inbound-event log. Returns True if it's new.

    This gives crash-safety (the event survives even if processing fails) and makes Meta's
    webhook retries idempotent (a re-delivered wa_message_id is recognised and skipped).
    """
    db = SessionLocal()
    try:
        _, is_new = crud.record_inbound_event(
            db, payload=json.dumps(m), dedupe_key=m.get("wa_message_id"), source="webhook")
        db.commit()
        return is_new
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("failed to record inbound event %s", m.get("wa_message_id"))
        return True  # fail open: still try to process
    finally:
        db.close()


def _process(m: dict) -> str | None:
    """Handle one normalized message. Returns reply text (or None to stay silent).

    DB work is synchronous + self-contained per message so a failure on one message
    doesn't poison the batch.
    """
    text = m.get("text") or ""
    if not text.strip():
        return None
    if not m.get("group_id") and not m.get("from"):
        return None

    db = SessionLocal()
    try:
        # A direct (non-group) message has no group id; bucket it under the sender.
        wa_group_id = m["group_id"] or f"dm:{m['from']}"
        group = crud.get_or_create_group(db, wa_group_id)
        member = crud.get_or_create_member(db, group, m["from"])

        reply = ingest.handle_text(
            db, group, member, text,
            message_id=m["wa_message_id"], spent_on=_ts_to_date(m.get("timestamp")),
        )
        db.commit()
        return reply
    except Exception:  # noqa: BLE001 - never let one message break the webhook
        db.rollback()
        log.exception("failed to process message %s", m.get("wa_message_id"))
        return None
    finally:
        db.close()


def _ts_to_date(ts: str | None) -> date:
    if not ts:
        return datetime.now(timezone.utc).date()
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
