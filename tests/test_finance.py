"""Tests for accounts, income, account balances, investments, insurance, onboarding."""
from datetime import date

from app import commands, crud, onboarding, reports


def _group_member(db, name="Ravi", uid="u1"):
    g = crud.get_or_create_group(db, "g1")
    m = crud.get_or_create_member(db, g, uid, name)
    return g, m


# --- onboarding ---------------------------------------------------------------

def test_onboarding_flow(db):
    g, m = _group_member(db, name=None, uid="u1")
    # start -> asks for name
    assert "name" in onboarding.start(db, m).lower()
    assert onboarding.is_active(db, m)
    # provide name
    r = onboarding.handle(db, g, m, "Anita")
    assert "Anita" in r
    assert m.display_name == "Anita"
    # add a bank and a credit card
    onboarding.handle(db, g, m, "HDFC 1234")
    onboarding.handle(db, g, m, "ICICI credit 5678")
    accts = crud.list_accounts(db, g, m)
    assert len(accts) == 2
    assert {a.kind for a in accts} == {"bank", "credit_card"}
    # finish
    done = onboarding.handle(db, g, m, "done")
    assert "All set" in done
    assert m.onboarded is True
    assert not onboarding.is_active(db, m)


def test_onboarding_rejects_bad_account(db):
    g, m = _group_member(db, name=None, uid="u1")
    onboarding.start(db, m)
    onboarding.handle(db, g, m, "Anita")
    r = onboarding.handle(db, g, m, "this is not an account")
    assert "didn't catch" in r.lower()


# --- accounts: debit & credit -------------------------------------------------

def test_account_balance_debit_and_credit(db):
    g, m = _group_member(db)
    acc = crud.add_account(db, g, m, bank_name="HDFC", last4="1234", opening_balance=1000)
    # credit 5000 (income), debit 200 (expense)
    crud.create_income(db, group=g, member=m, account=acc, amount=5000, currency="INR",
                       source="Salary", note="salary", received_on=date.today(),
                       raw_message="x", wa_message_id="inc-1")
    crud.create_expense(db, group=g, member=m, account=acc, amount=200, currency="INR",
                        category="Food", note="lunch", spent_at=date.today(),
                        raw_message="x", wa_message_id="exp-1")
    assert reports.account_balance(db, acc) == 5800  # 1000 + 5000 - 200


def test_find_account_by_name_and_last4(db):
    g, m = _group_member(db)
    crud.add_account(db, g, m, bank_name="HDFC", last4="1234")
    assert crud.find_account(db, g, "hdfc") is not None
    assert crud.find_account(db, g, "1234") is not None
    assert crud.find_account(db, g, "nope") is None


# --- income command -----------------------------------------------------------

def test_income_command_credits_account(db):
    g, m = _group_member(db)
    crud.add_account(db, g, m, bank_name="HDFC", last4="1234")
    out = commands.handle(db, g, m, "/income 50000 salary >hdfc")
    assert "50,000" in out
    assert reports.income_total(db, g) == 50000
    acc = crud.find_account(db, g, "hdfc")
    assert reports.account_balance(db, acc) == 50000


# --- investments --------------------------------------------------------------

def test_investment_add_and_update(db):
    g, m = _group_member(db)
    add = commands.handle(db, g, m, "/invest add mf 100000 Axis Bluechip")
    assert "Axis Bluechip" in add
    upd = commands.handle(db, g, m, "/invest update Axis Bluechip 125000")
    assert "125,000" in upd
    rows = reports.investments_overview(db, g)
    assert rows[0]["current_value"] == 125000
    assert rows[0]["gain"] == 25000
    assert reports.investments_value(db, g) == 125000


# --- insurance ----------------------------------------------------------------

def test_insurance_add_and_due(db):
    g, m = _group_member(db)
    out = commands.handle(db, g, m, "/insurance add health 24000 2099-09-15 HDFC Ergo Family")
    assert "HDFC Ergo Family" in out
    rows = reports.upcoming_premiums(db, g)
    assert rows[0]["premium"] == 24000
    assert rows[0]["due_date"] == "2099-09-15"
    assert rows[0]["days_until_due"] > 0


# --- net worth ----------------------------------------------------------------

def test_networth_combines_cash_and_investments(db):
    g, m = _group_member(db)
    acc = crud.add_account(db, g, m, bank_name="HDFC", last4="1234", opening_balance=0)
    crud.create_income(db, group=g, member=m, account=acc, amount=10000, currency="INR",
                       source="Salary", note="s", received_on=date.today(),
                       raw_message="x", wa_message_id="i1")
    crud.add_investment(db, g, m, name="MF", kind="mf", invested=5000, current=6000,
                        as_of=date.today())
    nw = reports.net_worth(db, g)
    assert nw["cash_in_accounts"] == 10000
    assert nw["investments_value"] == 6000
    assert nw["net_worth"] == 16000


def test_networth_command(db):
    g, m = _group_member(db)
    assert "Net worth" in commands.handle(db, g, m, "/networth")
