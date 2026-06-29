"""Tests for persistence, reporting, and split math."""
from datetime import date

from app import crud, reports


def _add(db, group, member, amount, category, wa_id, spent=None, currency="INR"):
    return crud.create_expense(
        db, group=group, member=member, amount=amount, currency=currency,
        category=category, note=category, spent_at=spent or date.today(),
        raw_message=f"{category} {amount}", wa_message_id=wa_id,
    )


def test_get_or_create_is_idempotent(db):
    g1 = crud.get_or_create_group(db, "g1")
    g2 = crud.get_or_create_group(db, "g1")
    assert g1.id == g2.id
    m1 = crud.get_or_create_member(db, g1, "u1", "Ravi")
    m2 = crud.get_or_create_member(db, g1, "u1")
    assert m1.id == m2.id


def test_dedupe_by_message_id(db):
    g = crud.get_or_create_group(db, "g1")
    m = crud.get_or_create_member(db, g, "u1", "Ravi")
    assert _add(db, g, m, 100, "Food", "msg-1") is not None
    assert _add(db, g, m, 100, "Food", "msg-1") is None  # duplicate webhook
    assert reports.total(db, g) == 100


def test_totals_and_categories(db):
    g = crud.get_or_create_group(db, "g1")
    m = crud.get_or_create_member(db, g, "u1", "Ravi")
    _add(db, g, m, 250, "Food", "a")
    _add(db, g, m, 120, "Transport", "b")
    _add(db, g, m, 80, "Food", "c")
    assert reports.total(db, g) == 450
    assert reports.total(db, g, category="Food") == 330
    cats = dict(reports.by_category(db, g))
    assert cats["Food"] == 330 and cats["Transport"] == 120


def test_undo_removes_last(db):
    g = crud.get_or_create_group(db, "g1")
    m = crud.get_or_create_member(db, g, "u1", "Ravi")
    _add(db, g, m, 250, "Food", "a")
    _add(db, g, m, 120, "Transport", "b")
    removed = crud.delete_last_expense(db, g, m)
    assert float(removed.amount) == 120
    assert reports.total(db, g) == 250


def test_settle_up_equal_split(db):
    g = crud.get_or_create_group(db, "g1")
    ravi = crud.get_or_create_member(db, g, "u1", "Ravi")
    sam = crud.get_or_create_member(db, g, "u2", "Sam")
    # Ravi paid 300, Sam paid 0. Fair share each = 150. Sam owes Ravi 150.
    _add(db, g, ravi, 300, "Food", "a")
    settlements = reports.settle_up(db, g)
    assert len(settlements) == 1
    s = settlements[0]
    assert s.debtor == "Sam" and s.creditor == "Ravi" and s.amount == 150


def test_month_filtering(db):
    g = crud.get_or_create_group(db, "g1")
    m = crud.get_or_create_member(db, g, "u1", "Ravi")
    _add(db, g, m, 100, "Food", "jan", spent=date(2026, 1, 15))
    _add(db, g, m, 200, "Food", "jun", spent=date(2026, 6, 10))
    start, end = reports.month_bounds(2026, 6)
    assert reports.total(db, g, start=start, end=end) == 200
