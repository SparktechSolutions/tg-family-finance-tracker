"""Tests for the Cowork connector operations (connector.core_ops).

These exercise the same logic the MCP tools call, using the in-memory `db` fixture so no
MCP runtime or WhatsApp credentials are needed.
"""
from connector import core_ops


def test_add_account_and_list(db):
    core_ops.add_account("HDFC", "1234", db=db)
    out = core_ops.list_accounts(db=db)
    assert out["accounts"][0]["bank_name"] == "HDFC"
    assert out["accounts"][0]["balance"] == 0


def test_income_credits_and_expense_debits_account(db):
    core_ops.add_account("HDFC", "1234", db=db)
    core_ops.add_income(50000, "salary", account="hdfc", db=db)
    core_ops.log_expense(amount=2000, category="Food", account="hdfc", db=db)
    bal = core_ops.list_accounts(db=db)["accounts"][0]["balance"]
    assert bal == 48000


def test_log_expense_text(db):
    r = core_ops.log_expense(text="Lunch 250 #food >hdfc", db=db)
    assert r["ok"] is True
    assert r["amount"] == 250
    assert r["category"] == "Food"


def test_log_expense_requires_amount(db):
    r = core_ops.log_expense(text="just chatting", db=db)
    assert r["ok"] is False


def test_investment_add_update_list(db):
    core_ops.add_investment("Axis Bluechip", kind="mf", invested=100000, db=db)
    upd = core_ops.update_investment("Axis Bluechip", 118000, db=db)
    assert upd["gain"] == 18000
    invs = core_ops.list_investments(db=db)["investments"]
    assert invs[0]["current_value"] == 118000


def test_update_missing_investment(db):
    assert core_ops.update_investment("Ghost", 100, db=db)["ok"] is False


def test_insurance_and_premiums(db):
    core_ops.add_insurance("HDFC Ergo", kind="health", premium=24000,
                           due_date="2099-09-15", db=db)
    ins = core_ops.upcoming_premiums(db=db)["insurance"]
    assert ins[0]["premium"] == 24000
    assert ins[0]["due_date"] == "2099-09-15"


def test_net_worth_and_monthly_summary(db):
    core_ops.add_account("HDFC", "1234", db=db)
    core_ops.add_income(10000, "salary", account="hdfc", db=db)
    core_ops.add_investment("MF", kind="mf", invested=5000, current=6000, db=db)
    core_ops.log_expense(amount=1500, category="Food", account="hdfc", db=db)
    nw = core_ops.net_worth(db=db)
    assert nw["cash_in_accounts"] == 8500   # 10000 - 1500
    assert nw["investments_value"] == 6000
    assert nw["net_worth"] == 14500
    ms = core_ops.monthly_summary(db=db)
    assert ms["income"] == 10000 and ms["expenses"] == 1500


def test_recent_expenses(db):
    core_ops.log_expense(amount=100, category="Food", db=db)
    core_ops.log_expense(amount=200, category="Transport", db=db)
    rows = core_ops.recent_expenses(limit=10, db=db)["expenses"]
    assert len(rows) == 2


def test_log_refund_credits_and_nets(db):
    core_ops.add_account("HDFC", "1234", db=db)
    core_ops.add_income(10000, "salary", account="hdfc", db=db)
    core_ops.log_expense(amount=2000, category="Shopping", account="hdfc", db=db)
    r = core_ops.log_refund(500, category="Shopping", account="hdfc", db=db)
    assert r["ok"] is True
    bal = core_ops.list_accounts(db=db)["accounts"][0]["balance"]
    assert bal == 8500             # 10000 - 2000 + 500
    assert core_ops.net_worth(db=db)["total_expenses"] == 1500  # 2000 - 500


def test_server_module_imports():
    # The MCP server wires tools over core_ops; importing it must not raise.
    # The `mcp` package lives in the connector's own venv (it is NOT a base-app dep),
    # so skip this when mcp isn't installed in the current environment.
    import pytest
    pytest.importorskip("mcp")
    import connector.server as srv
    assert srv.mcp is not None
