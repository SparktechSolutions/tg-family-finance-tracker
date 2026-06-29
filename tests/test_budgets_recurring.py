"""Tests for budgets (+ alerts) and recurring items (+ reminders)."""
from datetime import date

from app import commands, crud, ingest, reports


def _gm(db):
    g = crud.get_or_create_group(db, "g1")
    m = crud.get_or_create_member(db, g, "u1", "Anita")
    return g, m


# --- budgets ------------------------------------------------------------------

def test_set_and_status_budget(db):
    g, m = _gm(db)
    commands.handle(db, g, m, "/budget set Food 1000")
    ingest.handle_text(db, g, m, "lunch 300", message_id="m1")
    rows = reports.budget_status(db, g)
    assert rows[0]["category"] == "Food"
    assert rows[0]["spent"] == 300 and rows[0]["limit"] == 1000 and rows[0]["pct"] == 30


def test_budget_alert_near_and_over(db):
    g, m = _gm(db)
    commands.handle(db, g, m, "/budget set Food 1000")
    r1 = ingest.handle_text(db, g, m, "dinner 850", message_id="m1")   # 85% -> warn
    assert "budget used" in r1
    r2 = ingest.handle_text(db, g, m, "snacks 300", message_id="m2")   # over -> red
    assert "Over Food budget" in r2


def test_budget_remove(db):
    g, m = _gm(db)
    commands.handle(db, g, m, "/budget set Food 1000")
    assert "Removed" in commands.handle(db, g, m, "/budget remove Food")
    assert reports.budget_status(db, g) == []


# --- recurring ----------------------------------------------------------------

def test_add_recurring_and_overview(db):
    g, m = _gm(db)
    commands.handle(db, g, m, "/recurring add expense 15000 1 Rent")
    commands.handle(db, g, m, "/recurring add income 50000 1 Salary")
    rows = reports.recurring_overview(db, g)
    labels = {r["label"]: r for r in rows}
    assert labels["Rent"]["flow"] == "expense" and labels["Rent"]["amount"] == 15000
    assert labels["Salary"]["flow"] == "income"
    assert all(1 <= r["days_until"] <= 31 for r in rows)


def test_reminders_due_soon(db):
    g, m = _gm(db)
    today = date.today()
    # A recurring item due today.
    crud.add_recurring(db, g, m, flow="expense", label="Rent", amount=15000,
                       day_of_month=today.day)
    rem = reports.reminders(db, g, within_days=1)
    assert any("Rent" in r for r in rem)


def test_recurring_remove(db):
    g, m = _gm(db)
    commands.handle(db, g, m, "/recurring add expense 999 5 Netflix")
    rid = reports.recurring_overview(db, g)[0]["id"]
    assert "Removed" in commands.handle(db, g, m, f"/recurring remove {rid}")
    assert reports.recurring_overview(db, g) == []
