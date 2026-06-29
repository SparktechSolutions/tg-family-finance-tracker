"""Tests for self-transfers and loans (borrowed / lent), and their net-worth effects."""
from app import commands, crud, reports


def _setup(db):
    g = crud.get_or_create_group(db, "g1")
    m = crud.get_or_create_member(db, g, "u1", "Anita")
    hdfc = crud.add_account(db, g, m, bank_name="HDFC", last4="1111", opening_balance=10000)
    icici = crud.add_account(db, g, m, bank_name="ICICI", last4="2222", opening_balance=0)
    return g, m, hdfc, icici


# --- self transfer ------------------------------------------------------------

def test_transfer_moves_cash_without_changing_networth(db):
    g, m, hdfc, icici = _setup(db)
    commands.handle(db, g, m, "/transfer 4000 hdfc icici")
    assert reports.account_balance(db, hdfc) == 6000
    assert reports.account_balance(db, icici) == 4000
    assert reports.net_worth(db, g)["net_worth"] == 10000   # unchanged


def test_transfer_same_account_rejected(db):
    g, m, hdfc, icici = _setup(db)
    assert "different accounts" in commands.handle(db, g, m, "/transfer 100 hdfc hdfc")


# --- lent to a friend ---------------------------------------------------------

def test_lend_and_collect(db):
    g, m, hdfc, _ = _setup(db)
    commands.handle(db, g, m, "/lend 3000 Raju >hdfc")
    assert reports.account_balance(db, hdfc) == 7000           # cash went out
    nw = reports.net_worth(db, g)
    assert nw["lent_outstanding"] == 3000
    assert nw["net_worth"] == 10000                            # cash down, receivable up
    # Friend repays 1000 into HDFC
    commands.handle(db, g, m, "/loan collect Raju 1000 >hdfc")
    assert reports.account_balance(db, hdfc) == 8000
    assert reports.net_worth(db, g)["lent_outstanding"] == 2000
    assert reports.net_worth(db, g)["net_worth"] == 10000


# --- borrowed from a bank -----------------------------------------------------

def test_borrow_and_pay(db):
    g, m, hdfc, _ = _setup(db)
    commands.handle(db, g, m, "/borrow 50000 SBI >hdfc")
    assert reports.account_balance(db, hdfc) == 60000          # loan landed in account
    nw = reports.net_worth(db, g)
    assert nw["borrowed_outstanding"] == 50000
    assert nw["net_worth"] == 10000                            # cash up, liability up
    commands.handle(db, g, m, "/loan pay SBI 20000 >hdfc")
    assert reports.account_balance(db, hdfc) == 40000
    assert reports.net_worth(db, g)["borrowed_outstanding"] == 30000
    assert reports.net_worth(db, g)["net_worth"] == 10000


def test_loans_listing(db):
    g, m, hdfc, _ = _setup(db)
    commands.handle(db, g, m, "/lend 3000 Raju")
    commands.handle(db, g, m, "/borrow 50000 SBI")
    out = commands.handle(db, g, m, "/loans")
    assert "Raju" in out and "SBI" in out
    assert "You owe" in out and "Owed to you" in out


def test_loan_without_account_still_tracks_outstanding(db):
    g, m, hdfc, _ = _setup(db)
    commands.handle(db, g, m, "/lend 2000 Sam")               # no >account
    nw = reports.net_worth(db, g)
    # No cash movement recorded, but the receivable is tracked; net worth rises by 2000.
    assert nw["lent_outstanding"] == 2000
    assert nw["cash_in_accounts"] == 10000
    assert nw["net_worth"] == 12000


def test_pay_unknown_loan(db):
    g, m, hdfc, _ = _setup(db)
    assert "No record" in commands.handle(db, g, m, "/loan pay Nobody 100")
