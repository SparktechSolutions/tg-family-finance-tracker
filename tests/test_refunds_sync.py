"""Tests for refunds, the inbound-event log, and the chat-export importer."""
from datetime import date

from app import commands, crud, reports
from app.importer import import_chat_text
from app.parser import is_refund, parse_refund


# --- refunds ------------------------------------------------------------------

def _seed_account_and_expense(db):
    g = crud.get_or_create_group(db, "g1")
    m = crud.get_or_create_member(db, g, "u1", "Anita")
    acc = crud.add_account(db, g, m, bank_name="HDFC", last4="1234", opening_balance=0)
    crud.create_income(db, group=g, member=m, account=acc, amount=10000, currency="INR",
                       source="Salary", note="s", received_on=date.today(),
                       raw_message="x", wa_message_id="inc1")
    crud.create_expense(db, group=g, member=m, account=acc, amount=2000, currency="INR",
                        category="Shopping", note="shoes", spent_at=date.today(),
                        raw_message="shoes 2000", wa_message_id="exp1")
    return g, m, acc


def test_refund_nets_spend_and_credits_account(db):
    g, m, acc = _seed_account_and_expense(db)
    # balance after income 10000 - expense 2000 = 8000
    assert reports.account_balance(db, acc) == 8000
    assert reports.total(db, g) == 2000

    commands.record_refund(db, g, m, "refund 500 #shopping >hdfc", "INR", "ref1")

    # Refund credits the account (+500) and reduces net spend (-500).
    assert reports.account_balance(db, acc) == 8500
    assert reports.total(db, g) == 1500
    cats = dict(reports.by_category(db, g))
    assert cats["Shopping"] == 1500


def test_refund_links_to_prior_expense(db):
    g, m, acc = _seed_account_and_expense(db)
    commands.record_refund(db, g, m, "refund 500 #shopping", "INR", "ref1")
    # The refund row should reference the original shopping expense, with a negative amount.
    from sqlalchemy import select
    from app.models import Expense
    r = db.scalar(select(Expense).where(Expense.is_refund.is_(True)))
    assert r.original_expense_id is not None
    assert float(r.amount) == -500


def test_refund_command_dedupe(db):
    g, m, acc = _seed_account_and_expense(db)
    assert commands.record_refund(db, g, m, "refund 500 #shopping", "INR", "ref1") is not None
    # Same wa_message_id again -> no double refund.
    assert commands.record_refund(db, g, m, "refund 500 #shopping", "INR", "ref1") is None
    assert reports.total(db, g) == 1500


def test_refund_keyword_detection():
    assert is_refund("refund 500 #food")
    assert is_refund("Refunded 200 groceries")
    assert not is_refund("refundable deposit 5000")  # 'refundable' must not trigger...
    p = parse_refund("refund 500 #food >hdfc")
    assert p is not None and p.amount == 500 and p.category == "Food"


# --- inbound event log --------------------------------------------------------

def test_inbound_event_dedupe(db):
    ev1, new1 = crud.record_inbound_event(db, payload="{}", dedupe_key="m1")
    ev2, new2 = crud.record_inbound_event(db, payload="{}", dedupe_key="m1")
    assert new1 is True and new2 is False
    assert ev1.id == ev2.id
    crud.mark_event_processed(db, ev1)
    assert ev1.processed is True
    assert crud.unprocessed_events(db) == []


# --- chat-export importer -----------------------------------------------------

SAMPLE_EXPORT = """12/06/2026, 21:34 - Anita: Lunch 250 #food
12/06/2026, 21:35 - Ravi: uber 120 #transport
12/06/2026, 21:36 - Anita: how was your day?
12/06/2026, 21:40 - Ravi: refund 50 #transport
[13/06/2026, 9:00:01 AM] Anita: groceries 1500
"""


def test_import_chat_backfills_and_is_idempotent(db):
    g = crud.get_or_create_group(db, "fam")
    res = import_chat_text(SAMPLE_EXPORT, wa_group_id="fam", db=db)
    assert res.expenses == 3          # lunch, uber, groceries
    assert res.refunds == 1           # transport refund
    assert res.skipped >= 1           # "how was your day?" has no amount

    total_before = reports.total(db, g)
    # Re-import the same export -> everything deduped, totals unchanged.
    res2 = import_chat_text(SAMPLE_EXPORT, wa_group_id="fam", db=db)
    assert res2.expenses == 0 and res2.refunds == 0
    assert res2.duplicates >= 4
    assert reports.total(db, g) == total_before


def test_import_net_total(db):
    g = crud.get_or_create_group(db, "fam")
    import_chat_text(SAMPLE_EXPORT, wa_group_id="fam", db=db)
    # 250 + 120 + 1500 - 50 refund = 1820
    assert reports.total(db, g) == 1820
