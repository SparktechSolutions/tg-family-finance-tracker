"""Additional edge-case coverage across parser, reports, commands, and webhook helpers."""
from datetime import date

import pytest

from app import commands, crud, onboarding, reports
from app.parser import parse_expense
from app.whatsapp import extract_events, extract_messages


# --- parser edge cases --------------------------------------------------------

@pytest.mark.parametrize("text,amount,category", [
    ("Lunch 250 #food @ravi >hdfc", 250, "Food"),   # all hints together
    ("€45.50 dinner", 45.5, "Food"),                 # euro + decimal
    ("£12 movie", 12, "Entertainment"),              # pound
    ("petrol 3000", 3000, "Transport"),              # 4-digit no comma
    ("₹1,250.75 groceries", 1250.75, "Groceries"),   # western grouping + decimal
])
def test_parser_variants(text, amount, category):
    p = parse_expense(text)
    assert p is not None
    assert p.amount == amount
    assert p.category == category


def test_parser_all_hints_extracted():
    p = parse_expense("Lunch 250 #food @ravi >hdfc")
    assert p.payer_hint == "ravi"
    assert p.account_hint == "hdfc"
    assert p.category == "Food"
    assert p.amount == 250


def test_parser_bang_command_is_not_expense():
    assert parse_expense("!help") is None


# --- settle up with three members --------------------------------------------

def test_settle_three_members(db):
    g = crud.get_or_create_group(db, "g1")
    a = crud.get_or_create_member(db, g, "u1", "A")
    b = crud.get_or_create_member(db, g, "u2", "B")
    c = crud.get_or_create_member(db, g, "u3", "C")
    # A pays 300, B pays 60, C pays 0. Total 360, fair share 120 each.
    # A is owed 180, B owes 60, C owes 120.
    crud.create_expense(db, group=g, member=a, amount=300, currency="INR", category="X",
                        note="x", spent_at=date.today(), raw_message="x", wa_message_id="1")
    crud.create_expense(db, group=g, member=b, amount=60, currency="INR", category="X",
                        note="x", spent_at=date.today(), raw_message="x", wa_message_id="2")
    settlements = reports.settle_up(db, g)
    paid_to_a = sum(s.amount for s in settlements if s.creditor == "A")
    assert round(paid_to_a, 2) == 180
    assert all(s.creditor == "A" for s in settlements)  # only A is owed


# --- credit card + account scoping -------------------------------------------

def test_credit_card_balance(db):
    g = crud.get_or_create_group(db, "g1")
    m = crud.get_or_create_member(db, g, "u1", "A")
    cc = crud.add_account(db, g, m, bank_name="Amex", last4="9012", kind="credit_card")
    crud.create_expense(db, group=g, member=m, account=cc, amount=1500, currency="INR",
                        category="Shopping", note="x", spent_at=date.today(),
                        raw_message="x", wa_message_id="e1")
    # Spending on a card shows as a negative balance (you owe the card).
    assert reports.account_balance(db, cc) == -1500


def test_find_account_scoped_to_member(db):
    g = crud.get_or_create_group(db, "g1")
    a = crud.get_or_create_member(db, g, "u1", "A")
    b = crud.get_or_create_member(db, g, "u2", "B")
    crud.add_account(db, g, a, bank_name="HDFC", last4="1111")
    crud.add_account(db, g, b, bank_name="HDFC", last4="2222")
    # Same bank name; scoping by member disambiguates.
    assert crud.find_account(db, g, "hdfc", member=a).last4 == "1111"
    assert crud.find_account(db, g, "hdfc", member=b).last4 == "2222"


# --- income dedupe + no-account ----------------------------------------------

def test_income_dedupe(db):
    g = crud.get_or_create_group(db, "g1")
    m = crud.get_or_create_member(db, g, "u1", "A")
    assert crud.create_income(db, group=g, member=m, account=None, amount=100,
                              currency="INR", source="S", note="s", received_on=date.today(),
                              raw_message="x", wa_message_id="dup") is not None
    assert crud.create_income(db, group=g, member=m, account=None, amount=100,
                              currency="INR", source="S", note="s", received_on=date.today(),
                              raw_message="x", wa_message_id="dup") is None
    assert reports.income_total(db, g) == 100


# --- insurance overdue --------------------------------------------------------

def test_insurance_overdue_is_negative_days(db):
    g = crud.get_or_create_group(db, "g1")
    m = crud.get_or_create_member(db, g, "u1", "A")
    crud.add_insurance(db, g, m, name="Old", kind="life", provider=None, premium=1000,
                       frequency="yearly", due_date=date(2000, 1, 1))
    rows = reports.upcoming_premiums(db, g)
    assert rows[0]["days_until_due"] < 0


# --- commands: case-insensitive category, invalid month ----------------------

def test_total_category_case_insensitive(db):
    g = crud.get_or_create_group(db, "g1")
    m = crud.get_or_create_member(db, g, "u1", "A")
    crud.create_expense(db, group=g, member=m, amount=200, currency="INR", category="Food",
                        note="x", spent_at=date.today(), raw_message="x", wa_message_id="1")
    assert "200" in commands.handle(db, g, m, "/total FOOD")


def test_invalid_month_usage(db):
    g = crud.get_or_create_group(db, "g1")
    m = crud.get_or_create_member(db, g, "u1", "A")
    assert "Usage" in commands.handle(db, g, m, "/month notamonth")


def test_invest_update_missing(db):
    g = crud.get_or_create_group(db, "g1")
    m = crud.get_or_create_member(db, g, "u1", "A")
    assert "No investment" in commands.handle(db, g, m, "/invest update Ghost 100")


def test_onboarding_skip(db):
    g = crud.get_or_create_group(db, "g1")
    m = crud.get_or_create_member(db, g, "u1", None)
    onboarding.start(db, m)
    onboarding.handle(db, g, m, "Sam")
    out = onboarding.handle(db, g, m, "skip")
    assert "All set" in out
    assert crud.list_accounts(db, g, m) == []


# --- webhook payload helpers --------------------------------------------------

def test_extract_messages_flattens_text():
    payload = {"entry": [{"changes": [{"value": {"messages": [
        {"id": "m1", "from": "u1", "type": "text", "timestamp": "1",
         "group_id": "g1", "text": {"body": "hi"}}]}}]}]}
    msgs = extract_messages(payload)
    assert msgs[0]["wa_message_id"] == "m1"
    assert msgs[0]["group_id"] == "g1"
    assert msgs[0]["text"] == "hi"


def test_extract_messages_ignores_non_text_gracefully():
    payload = {"entry": [{"changes": [{"value": {"messages": [
        {"id": "m2", "from": "u1", "type": "image", "timestamp": "1",
         "group_id": "g1", "image": {"id": "x"}}]}}]}]}
    msgs = extract_messages(payload)
    assert msgs[0]["text"] == ""  # no body -> empty, never crashes


def test_extract_events_detects_bot_added():
    payload = {"entry": [{"changes": [{"field": "group_lifecycle_update",
        "value": {"group_id": "g1", "action": "add"}}]}]}
    events = extract_events(payload)
    assert events and events[0]["type"] == "bot_added_to_group"
    assert events[0]["group_id"] == "g1"
