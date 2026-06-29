"""Tests for the shared dispatcher (app.ingest) and Telegram update handling."""
from datetime import date

import pytest

from app import crud, ingest, reports


# --- shared dispatcher (channel-agnostic) ------------------------------------

def _gm(db):
    g = crud.get_or_create_group(db, "tg:-100")
    m = crud.get_or_create_member(db, g, "tg:1", "Anita")
    return g, m


def test_ingest_logs_expense(db):
    g, m = _gm(db)
    reply = ingest.handle_text(db, g, m, "Lunch 250 #food", message_id="tg-1")
    assert "Logged" in reply and "250" in reply
    assert reports.total(db, g) == 250


def test_ingest_command(db):
    g, m = _gm(db)
    assert "Family Finance Tracker" in ingest.handle_text(db, g, m, "/help", message_id="tg-2")


def test_ingest_refund_nets(db):
    g, m = _gm(db)
    ingest.handle_text(db, g, m, "Shoes 2000 #shopping", message_id="tg-1")
    ingest.handle_text(db, g, m, "refund 500 #shopping", message_id="tg-2")
    assert reports.total(db, g) == 1500


def test_ingest_dedupe_on_message_id(db):
    g, m = _gm(db)
    ingest.handle_text(db, g, m, "coffee 80", message_id="tg-dup")
    ingest.handle_text(db, g, m, "coffee 80", message_id="tg-dup")  # same id -> ignored
    assert reports.total(db, g) == 80


def test_ingest_chatter_ignored(db):
    g, m = _gm(db)
    assert ingest.handle_text(db, g, m, "are we meeting tonight?", message_id="tg-3") is None


def test_ingest_uses_message_date(db):
    g, m = _gm(db)
    ingest.handle_text(db, g, m, "gift 500", message_id="tg-4", spent_on=date(2026, 1, 9))
    start, end = reports.month_bounds(2026, 1)
    assert reports.total(db, g, start=start, end=end) == 500


# --- Telegram update mapping --------------------------------------------------

def test_telegram_process_update_logs_expense(db, monkeypatch):
    from app import telegram_bot as tg

    # Route the bot's DB sessions to the in-memory test session, and capture replies.
    monkeypatch.setattr(tg, "SessionLocal", lambda: db)
    sent = []
    monkeypatch.setattr(tg, "send_message", lambda chat_id, text: sent.append((chat_id, text)))
    # Don't actually close the shared test session.
    monkeypatch.setattr(db, "close", lambda: None)

    update = {
        "update_id": 1,
        "message": {
            "message_id": 10, "date": 1782000000,
            "chat": {"id": -100123, "type": "group"},
            "from": {"id": 42, "first_name": "Anita"},
            "text": "Lunch 250 #food",
        },
    }
    tg.process_update(update)

    assert sent and "Logged" in sent[0][1]
    g = crud.get_or_create_group(db, "tg:-100123")
    assert reports.total(db, g) == 250


def test_telegram_bot_added_welcomes(db, monkeypatch):
    from app import telegram_bot as tg
    sent = []
    monkeypatch.setattr(tg, "send_message", lambda chat_id, text: sent.append((chat_id, text)))
    update = {"update_id": 2, "message": {
        "message_id": 1, "date": 1782000000, "chat": {"id": -55, "type": "group"},
        "from": {"id": 1, "first_name": "Anita"},
        "new_chat_members": [{"id": 999, "is_bot": True, "first_name": "FinanceBot"}],
    }}
    tg.process_update(update)
    assert sent and "Family Finance Tracker" in sent[0][1]
