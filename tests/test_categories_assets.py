"""Tests for the expanded category map and cash/asset account types."""
import pytest

from app import commands, crud, reports
from app.parser import parse_expense


@pytest.mark.parametrize("text,cat", [
    ("doctor 500", "Health"),
    ("medicine 200", "Health"),
    ("school fees 15000", "Education"),
    ("groceries 1200", "Groceries"),
    ("electricity 900", "Utilities"),
    ("netflix 199", "Subscriptions"),
    ("flight 8000", "Travel"),
    ("gift 1000", "Gifts"),
    ("maid 3000", "Domestic Help"),
    ("gym 1500", "Fitness"),
    ("haircut 300", "Personal Care"),
])
def test_expanded_categories(text, cat):
    assert parse_expense(text).category == cat


def test_custom_category_via_tag():
    # Any #tag becomes a category, so custom categories work out of the box.
    assert parse_expense("offering 500 #festival").category == "Festival"


def test_cash_and_asset_accounts(db):
    g = crud.get_or_create_group(db, "g1")
    m = crud.get_or_create_member(db, g, "u1", "Anita")
    commands.handle(db, g, m, "/account add Wallet cash 2000")
    commands.handle(db, g, m, "/account add Gold asset 150000")
    accts = {a["bank_name"]: a for a in reports.accounts_overview(db, g)}
    assert accts["Wallet"]["kind"] == "cash" and accts["Wallet"]["balance"] == 2000
    assert accts["Gold"]["kind"] == "asset" and accts["Gold"]["balance"] == 150000
    # Both count toward net worth.
    assert reports.net_worth(db, g)["cash_in_accounts"] == 152000
