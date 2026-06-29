"""Tests for personal vs shared expenses and their effect on settle-up."""
from datetime import date

from app import crud, ingest, reports
from app.parser import parse_expense


def test_personal_marker_parsed():
    p = parse_expense("Spa 1500 !personal")
    assert p.shared is False
    assert "personal" not in p.note.lower()
    assert p.amount == 1500
    assert parse_expense("Lunch 250").shared is True


def test_personal_expense_excluded_from_settle(db):
    g = crud.get_or_create_group(db, "g1")
    a = crud.get_or_create_member(db, g, "u1", "A")
    b = crud.get_or_create_member(db, g, "u2", "B")
    # A pays a shared 300; B pays a personal 1000 (should NOT be split).
    ingest.handle_text(db, g, a, "dinner 300", message_id="m1")
    ingest.handle_text(db, g, b, "spa 1000 !personal", message_id="m2")

    settlements = reports.settle_up(db, g)
    # Only the 300 shared expense splits: fair share 150 each, B owes A 150.
    assert len(settlements) == 1
    s = settlements[0]
    assert s.debtor == "B" and s.creditor == "A" and s.amount == 150
    # But the personal expense still counts in B's own totals / category spend.
    assert reports.total(db, g) == 1300


def test_all_personal_means_no_settlement(db):
    g = crud.get_or_create_group(db, "g1")
    a = crud.get_or_create_member(db, g, "u1", "A")
    b = crud.get_or_create_member(db, g, "u2", "B")
    ingest.handle_text(db, g, a, "shoes 2000 !personal", message_id="m1")
    ingest.handle_text(db, g, b, "bag 3000 !mine", message_id="m2")
    assert reports.settle_up(db, g) == []
