"""Tests for as-of balances and period summary (opening/closing/net change)."""
from datetime import date

from app import crud, reports


def _seed(db):
    g = crud.get_or_create_group(db, "g1")
    m = crud.get_or_create_member(db, g, "u1", "Anita")
    hdfc = crud.add_account(db, g, m, bank_name="HDFC", last4="1", opening_balance=10000)
    # Income in Jan, expense in Feb.
    crud.create_income(db, group=g, member=m, account=hdfc, amount=5000, currency="INR",
                       source="Salary", note="s", received_on=date(2026, 1, 10),
                       raw_message="x", wa_message_id="i1")
    crud.create_expense(db, group=g, member=m, account=hdfc, amount=2000, currency="INR",
                        category="Food", note="f", spent_at=date(2026, 2, 15),
                        raw_message="x", wa_message_id="e1")
    return g, m, hdfc


def test_balance_asof(db):
    g, m, hdfc = _seed(db)
    # Before any activity: just the opening baseline.
    assert reports.account_balance(db, hdfc, asof=date(2026, 1, 1)) == 10000
    # After Jan income, before Feb expense.
    assert reports.account_balance(db, hdfc, asof=date(2026, 2, 1)) == 15000
    # Current (all flows): 10000 + 5000 - 2000.
    assert reports.account_balance(db, hdfc) == 13000


def test_period_summary_opening_closing(db):
    g, m, hdfc = _seed(db)
    # February: opening = balance at Feb 1 (15000), closing = balance at Mar 1 (13000).
    p = reports.period_summary(db, g, date(2026, 2, 1), date(2026, 3, 1))
    assert p["opening_balance"] == 15000
    assert p["closing_balance"] == 13000
    assert p["net_change"] == -2000
    assert p["expenses"] == 2000 and p["income"] == 0
    assert p["accounts"][0]["opening"] == 15000 and p["accounts"][0]["closing"] == 13000


def test_period_summary_january(db):
    g, m, hdfc = _seed(db)
    p = reports.period_summary(db, g, date(2026, 1, 1), date(2026, 2, 1))
    assert p["opening_balance"] == 10000      # nothing before Jan
    assert p["closing_balance"] == 15000      # +5000 salary
    assert p["income"] == 5000 and p["net_change"] == 5000
