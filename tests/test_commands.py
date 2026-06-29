"""Tests for the bot command handlers."""
from datetime import date

from app import commands, crud


def _seed(db):
    g = crud.get_or_create_group(db, "g1")
    ravi = crud.get_or_create_member(db, g, "u1", "Ravi")
    sam = crud.get_or_create_member(db, g, "u2", "Sam")
    today = date.today()
    crud.create_expense(db, group=g, member=ravi, amount=250, currency="INR",
                        category="Food", note="lunch", spent_at=today,
                        raw_message="lunch 250", wa_message_id="a")
    crud.create_expense(db, group=g, member=sam, amount=120, currency="INR",
                        category="Transport", note="uber", spent_at=today,
                        raw_message="uber 120", wa_message_id="b")
    return g, ravi, sam


def test_help(db):
    g = crud.get_or_create_group(db, "g1")
    m = crud.get_or_create_member(db, g, "u1", "Ravi")
    assert "Family Finance Tracker" in commands.handle(db, g, m, "/help")


def test_total(db):
    g, ravi, _ = _seed(db)
    out = commands.handle(db, g, ravi, "/total")
    assert "370" in out


def test_total_category(db):
    g, ravi, _ = _seed(db)
    out = commands.handle(db, g, ravi, "/total food")
    assert "250" in out and "Food" in out


def test_split(db):
    g, ravi, _ = _seed(db)
    out = commands.handle(db, g, ravi, "/split")
    assert "Sam" in out and "Ravi" in out


def test_undo(db):
    g, ravi, _ = _seed(db)
    out = commands.handle(db, g, ravi, "/undo")
    assert "Removed" in out


def test_unknown(db):
    g = crud.get_or_create_group(db, "g1")
    m = crud.get_or_create_member(db, g, "u1", "Ravi")
    assert "Unknown command" in commands.handle(db, g, m, "/frobnicate")
