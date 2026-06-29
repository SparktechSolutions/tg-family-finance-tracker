"""Tests for setting account balances (bank cash) and credit-card owed amounts."""
from datetime import date

from app import commands, crud, onboarding, reports
from connector import core_ops


def _gm(db, name="Anita"):
    g = crud.get_or_create_group(db, "g1")
    m = crud.get_or_create_member(db, g, "u1", name)
    return g, m


# --- crud.set_account_balance preserves logged transactions -------------------

def test_set_balance_accounts_for_existing_transactions(db):
    g, m = _gm(db)
    acc = crud.add_account(db, g, m, bank_name="HDFC", last4="1234", opening_balance=0)
    crud.create_expense(db, group=g, member=m, account=acc, amount=2000, currency="INR",
                        category="Food", note="x", spent_at=date.today(),
                        raw_message="x", wa_message_id="e1")
    # Tell it the real current balance is 48000 (despite the -2000 already logged).
    crud.set_account_balance(db, acc, 48000)
    assert reports.account_balance(db, acc) == 48000
    # A further expense still moves it correctly.
    crud.create_expense(db, group=g, member=m, account=acc, amount=1000, currency="INR",
                        category="Food", note="y", spent_at=date.today(),
                        raw_message="y", wa_message_id="e2")
    assert reports.account_balance(db, acc) == 47000


# --- onboarding with optional balance ----------------------------------------

def test_onboarding_account_with_balance(db):
    g, m = _gm(db, name=None)
    onboarding.start(db, m)
    onboarding.handle(db, g, m, "Anita")
    onboarding.handle(db, g, m, "HDFC 1234 50000")
    onboarding.handle(db, g, m, "ICICI credit 5678 12000")
    accts = {a.bank_name: a for a in crud.list_accounts(db, g, m)}
    assert reports.account_balance(db, accts["HDFC"]) == 50000     # cash
    assert reports.account_balance(db, accts["ICICI"]) == -12000   # owed


# --- /account command ---------------------------------------------------------

def test_account_add_bank_with_balance(db):
    g, m = _gm(db)
    out = commands.handle(db, g, m, "/account add HDFC 1234 50000")
    assert "Added" in out
    acc = crud.find_account(db, g, "hdfc")
    assert reports.account_balance(db, acc) == 50000


def test_account_add_credit_card_owed(db):
    g, m = _gm(db)
    commands.handle(db, g, m, "/account add ICICI credit 5678 12000")
    acc = crud.find_account(db, g, "icici")
    assert acc.kind == "credit_card"
    assert reports.account_balance(db, acc) == -12000   # owe 12000


def test_account_balance_set_bank(db):
    g, m = _gm(db)
    crud.add_account(db, g, m, bank_name="HDFC", last4="1234")
    commands.handle(db, g, m, "/account balance HDFC 60000")
    assert reports.account_balance(db, crud.find_account(db, g, "hdfc")) == 60000


def test_account_balance_set_credit_owed(db):
    g, m = _gm(db)
    crud.add_account(db, g, m, bank_name="ICICI", last4="5678", kind="credit_card")
    commands.handle(db, g, m, "/account balance ICICI 9000")
    assert reports.account_balance(db, crud.find_account(db, g, "icici")) == -9000


def test_networth_reflects_card_debt(db):
    g, m = _gm(db)
    crud.add_account(db, g, m, bank_name="HDFC", last4="1", opening_balance=50000)
    crud.add_account(db, g, m, bank_name="Amex", last4="2", kind="credit_card",
                     opening_balance=-12000)
    nw = reports.net_worth(db, g)
    # Cash 50000 minus 12000 owed on the card = 38000.
    assert nw["cash_in_accounts"] == 38000


# --- connector tools ----------------------------------------------------------

def test_connector_add_account_and_set_balance(db):
    core_ops.add_account("HDFC", "1234", balance=50000, db=db)
    core_ops.add_account("ICICI", "5678", kind="credit_card", balance=12000, db=db)
    accts = {a["bank_name"]: a for a in core_ops.list_accounts(db=db)["accounts"]}
    assert accts["HDFC"]["balance"] == 50000
    assert accts["ICICI"]["balance"] == -12000          # owed stored negative

    core_ops.set_account_balance("HDFC", 60000, db=db)
    accts = {a["bank_name"]: a for a in core_ops.list_accounts(db=db)["accounts"]}
    assert accts["HDFC"]["balance"] == 60000
