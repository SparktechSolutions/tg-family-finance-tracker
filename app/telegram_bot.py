"""Telegram bot ingestion — a free, official, real-time alternative to WhatsApp.

Uses **long polling** (getUpdates), so it needs NO public URL, no ngrok, and no hosting —
just run it on any machine with internet:

    TELEGRAM_BOT_TOKEN=123:abc  python -m app.telegram_bot      # or: ./run.sh telegram

Setup (see docs/TELEGRAM.md): create a bot with @BotFather, DISABLE its group privacy
(BotFather → /setprivacy → Disable) so it can read all group messages, then add it to your
family group.

Each Telegram message is routed through the SAME core as WhatsApp (app.ingest.handle_text),
so the parser, commands, onboarding, refunds, accounts, dashboard, and connector all work
unchanged. Group = Telegram chat id; member = Telegram user id.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import httpx

from . import crud, ingest, onboarding
from .config import settings
from .db import SessionLocal, init_db

log = logging.getLogger("telegram")

API = "https://api.telegram.org/bot{token}/{method}"


def _call(method: str, **params):
    url = API.format(token=settings.telegram_bot_token, method=method)
    resp = httpx.post(url, json=params, timeout=70)
    data = resp.json()
    if not data.get("ok"):
        log.error("telegram %s failed: %s", method, data)
    return data


def send_message(chat_id, text: str) -> None:
    if not settings.telegram_bot_token:
        log.info("[dry-run telegram] to=%s text=%s", chat_id, text)
        return
    _call("sendMessage", chat_id=chat_id, text=text)


def _group_key(chat: dict) -> str:
    return f"tg:{chat.get('id')}"


def _member_key(user: dict) -> str:
    return f"tg:{user.get('id')}"


def _display_name(user: dict) -> str:
    name = " ".join(p for p in (user.get("first_name"), user.get("last_name")) if p).strip()
    return name or user.get("username") or str(user.get("id"))


def _msg_date(message: dict) -> date:
    ts = message.get("date")
    if not ts:
        return date.today()
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).date()


def process_update(update: dict) -> None:
    """Handle one Telegram update: bot-added welcome, or a text message → dispatch."""
    message = update.get("message") or update.get("edited_message")
    if not message:
        return
    chat = message.get("chat") or {}
    chat_id = chat.get("id")

    # Bot just added to a group -> welcome the family.
    for member_added in message.get("new_chat_members", []) or []:
        if member_added.get("is_bot"):
            send_message(chat_id, onboarding.welcome_message())
            return

    text = message.get("text")
    user = message.get("from") or {}
    if not text or not user:
        return

    message_id = f"tg-{chat_id}-{message.get('message_id')}"

    db = SessionLocal()
    try:
        # Idempotency / durability: record before processing; skip if already seen.
        _, is_new = crud.record_inbound_event(
            db, payload=text[:2000], dedupe_key=message_id, source="telegram")
        db.commit()
        if not is_new:
            return

        group = crud.get_or_create_group(db, _group_key(chat))
        member = crud.get_or_create_member(
            db, group, _member_key(user), display_name=_display_name(user))
        reply = ingest.handle_text(
            db, group, member, text, message_id=message_id, spent_on=_msg_date(message))
        db.commit()
    except Exception:  # noqa: BLE001 - never let one message kill the poller
        db.rollback()
        log.exception("failed to process telegram update")
        reply = None
    finally:
        db.close()

    if reply:
        send_message(chat_id, reply)


def run() -> None:
    """Long-poll Telegram for updates and process them forever."""
    if not settings.telegram_bot_token:
        raise SystemExit(
            "TELEGRAM_BOT_TOKEN is not set. Create a bot with @BotFather, then set it in "
            ".env (TELEGRAM_BOT_TOKEN=...). See docs/TELEGRAM.md.")
    init_db()
    log.info("Telegram bot started (long polling). Press Ctrl-C to stop.")
    offset = None
    while True:
        try:
            params = {"timeout": 50, "allowed_updates": ["message"]}
            if offset is not None:
                params["offset"] = offset
            data = _call("getUpdates", **params)
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                process_update(update)
        except KeyboardInterrupt:
            log.info("Stopping.")
            break
        except Exception:  # noqa: BLE001 - keep polling through transient errors
            log.exception("poll error; retrying")


def main() -> None:
    logging.basicConfig(level=settings.log_level)
    run()


if __name__ == "__main__":
    main()
