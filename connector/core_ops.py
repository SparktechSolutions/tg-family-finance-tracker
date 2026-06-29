"""Connector operations layer.

Thin, testable functions that reuse the existing core (`app.crud`, `app.reports`,
`app.parser`) and the SAME database as the WhatsApp bot. The MCP server (`server.py`)
wraps these as tools; tests call them directly with an injected session.

Each public function accepts an optional `db` session for tests. In normal use it opens
its own session, commits, and closes. The connector acts on ONE household group + a single
"Cowork user" member, both configurable via env:

    FINANCE_GROUP_ID   (default "cowork-household")
        Set this to the WhatsApp group's `wa_group_id` to share one ledger with the bot.
    FINANCE_MEMBER     (default "You")
        Display name used for things you log from Cowork.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, datetime

from sqlalchemy.orm import Session

from app import crud, reports
from app.config import settings
from app.db import SessionLocal
from app.parser import parse_expense

GROUP_ID = os.getenv("FINANCE_GROUP_ID", "cowork-household")
MEMBER_NAME = os.getenv("FINANCE_MEMBER", "You")


def _ctx(db: Session):
    group = crud.get_or_create_group(db, GROUP_ID)
    member = crud.get_or_create_member(
        db, group, wa_user_id=f"cowork:{MEMBER_NAME}", display_name=MEMBER_NAME
    )
    return group, member


def _mid() -> str:
    return f"cowork-{uuid.uuid4()}"


def _run(fn, db):
    """Run fn(db) managing the session lifecycle (own session unless one is injected)."""
    own = db is None
    db = db or SessionLocal()
    try:
        result = fn(db)
        db.commit() if own else db.flush()
        return result
    finally:
        if own:
            db.close()


# --- actions -------------------------------------------------------------------

def log_expense(amount: float | None = None, category: str | None = None,
                note: str | None = None, account: str | None = None,
                payer: str | None = None, text: str | None = None, *,
                db: Session | None = None) -> dict:
    """Log an expense. Either pass structured fields or a freeform `text` to be parsed."""
    def op(db):
        group, member = _ctx(db)
        amt, cat, n, acc_hint, payer_hint = amount, category, note, account, payer
        if text:
            parsed = parse_expense(text, default_currency=group.currency)
            if parsed is None:
                return {"ok": False, "error": "No amount found in text."}
            amt = amt if amt is not None else parsed.amount
            cat = cat or parsed.category
            n = n or parsed.note
            acc_hint = acc_hint or parsed.account_hint
            payer_hint = payer_hint or parsed.payer_hint
        if amt is None:
            return {"ok": False, "error": "amount is required"}

        who = member
        if payer_hint:
            who = crud.find_member_by_name(db, group, payer_hint) or \
                crud.get_or_create_member(db, group, payer_hint, display_name=payer_hint)
        acc = crud.find_account(db, group, acc_hint) if acc_hint else None
        exp = crud.create_expense(
            db, group=group, member=who, account=acc, amount=float(amt),
            currency=group.currency, category=(cat or "Uncategorized"),
            note=(n or cat or "Uncategorized"), spent_at=date.today(),
            raw_message=text or f"{n or cat} {amt}", wa_message_id=_mid(),
        )
        return {"ok": True, "amount": float(amt), "currency": group.currency,
                "category": exp.category, "account": (f"{acc.bank_name} ****{acc.last4}" if acc else None),
                "payer": who.display_name}
    return _run(op, db)


def log_refund(amount: float, category: str | None = None, note: str | None = None,
               account: str | None = None, *, db: Session | None = None) -> dict:
    """Record a refund (money back). Credits `account` and nets against category spend.
    Links to the most recent matching expense when possible."""
    def op(db):
        group, member = _ctx(db)
        acc = crud.find_account(db, group, account) if account else None
        original = crud.latest_expense(db, group, member=member, category=category) \
            or (crud.latest_expense(db, group, category=category) if category else None)
        refund = crud.create_refund(
            db, group=group, member=member, account=acc, amount=float(amount),
            currency=group.currency, category=(category or "Uncategorized"),
            note=(note or "refund"), spent_at=date.today(),
            raw_message=f"refund {amount} {category or ''}", wa_message_id=_mid(),
            original=original)
        return {"ok": True, "amount": float(amount), "currency": group.currency,
                "category": refund.category,
                "account": (f"{acc.bank_name} ****{acc.last4}" if acc else None),
                "linked": bool(refund.original_expense_id)}
    return _run(op, db)


def add_income(amount: float, source: str = "Income", account: str | None = None, *,
               db: Session | None = None) -> dict:
    """Record income (e.g. salary). Credits `account` if given (by bank name or last-4)."""
    def op(db):
        group, member = _ctx(db)
        acc = crud.find_account(db, group, account) if account else None
        inc = crud.create_income(
            db, group=group, member=member, account=acc, amount=float(amount),
            currency=group.currency, source=source.capitalize(), note=source,
            received_on=date.today(), raw_message=f"income {amount} {source}",
            wa_message_id=_mid(),
        )
        return {"ok": True, "amount": float(amount), "currency": group.currency,
                "source": inc.source, "account": (f"{acc.bank_name} ****{acc.last4}" if acc else None)}
    return _run(op, db)


def add_account(bank_name: str, last4: str, kind: str = "bank",
                balance: float = 0, *, db: Session | None = None) -> dict:
    """Add a bank account or credit card (kind='bank'|'credit_card'). Stores bank + last4 only.

    `balance` is the account's current balance: for a bank it's cash on hand; for a credit
    card it's the amount currently owed (stored internally as negative).
    """
    def op(db):
        group, member = _ctx(db)
        opening = -abs(float(balance)) if kind == "credit_card" else float(balance)
        acc = crud.add_account(db, group, member, bank_name=bank_name, last4=last4,
                               kind=kind, opening_balance=opening)
        return {"ok": True, "bank_name": acc.bank_name, "last4": acc.last4, "kind": acc.kind,
                "balance": balance}
    return _run(op, db)


def set_account_balance(account: str, balance: float, *, db: Session | None = None) -> dict:
    """Set an account's current balance (bank = cash; credit card = amount owed)."""
    def op(db):
        group, _ = _ctx(db)
        acc = crud.find_account(db, group, account)
        if acc is None:
            return {"ok": False, "error": f"No account matching '{account}'."}
        target = -abs(float(balance)) if acc.kind == "credit_card" else float(balance)
        crud.set_account_balance(db, acc, target)
        return {"ok": True, "account": f"{acc.bank_name} ****{acc.last4}",
                "kind": acc.kind, "balance": float(balance)}
    return _run(op, db)


def transfer(from_account: str, to_account: str, amount: float, *,
             db: Session | None = None) -> dict:
    """Move money between your own accounts (by bank name or last-4). Net worth unchanged."""
    def op(db):
        group, member = _ctx(db)
        src = crud.find_account(db, group, from_account)
        dst = crud.find_account(db, group, to_account)
        if src is None or dst is None:
            return {"ok": False, "error": "account not found"}
        if src.id == dst.id:
            return {"ok": False, "error": "pick two different accounts"}
        crud.create_transfer(db, group=group, member=member, from_account=src, to_account=dst,
                             amount=float(amount), currency=group.currency, on=date.today(),
                             wa_message_id=_mid())
        return {"ok": True, "amount": float(amount),
                "from": f"{src.bank_name} ****{src.last4}", "to": f"{dst.bank_name} ****{dst.last4}"}
    return _run(op, db)


def lend(amount: float, friend: str, account: str | None = None, *,
         db: Session | None = None) -> dict:
    """Record money you lent to a friend (they owe you). Optionally from an account."""
    return _add_loan("lent", amount, friend, account, db)


def borrow(amount: float, lender: str, account: str | None = None, *,
           db: Session | None = None) -> dict:
    """Record money you borrowed (you owe it). Optionally received into an account."""
    return _add_loan("borrowed", amount, lender, account, db)


def _add_loan(direction, amount, counterparty, account, db):
    def op(db):
        group, member = _ctx(db)
        acc = crud.find_account(db, group, account) if account else None
        crud.add_loan(db, group, member, direction=direction, counterparty=counterparty,
                      principal=float(amount), on=date.today(), account=acc)
        return {"ok": True, "direction": direction, "counterparty": counterparty,
                "amount": float(amount)}
    return _run(op, db)


def loan_payment(counterparty: str, amount: float, direction: str = "borrowed",
                 account: str | None = None, *, db: Session | None = None) -> dict:
    """Record a loan payment. direction='borrowed' = you repay; 'lent' = friend repays you."""
    def op(db):
        group, _ = _ctx(db)
        loan = crud.find_loan(db, group, counterparty, direction=direction)
        if loan is None:
            return {"ok": False, "error": f"no {direction} loan with '{counterparty}'"}
        acc = crud.find_account(db, group, account) if account else None
        crud.add_loan_payment(db, loan, amount=float(amount), on=date.today(), account=acc)
        return {"ok": True, "counterparty": counterparty, "paid": float(amount),
                "outstanding": reports.loan_outstanding(db, loan)}
    return _run(op, db)


def list_loans(*, db: Session | None = None) -> dict:
    """List loans (money you owe and money owed to you) with outstanding balances."""
    return _run(lambda db: {"loans": reports.loans_overview(db, _ctx(db)[0])}, db)


def set_budget(category: str, monthly_limit: float, *, db: Session | None = None) -> dict:
    """Set a monthly spending limit for a category."""
    def op(db):
        group, _ = _ctx(db)
        crud.set_budget(db, group, category.capitalize(), float(monthly_limit))
        return {"ok": True, "category": category.capitalize(), "monthly_limit": float(monthly_limit)}
    return _run(op, db)


def budget_status(*, db: Session | None = None) -> dict:
    """This month's spend vs limit for each budgeted category."""
    return _run(lambda db: {"budgets": reports.budget_status(db, _ctx(db)[0])}, db)


def add_recurring(flow: str, label: str, amount: float, day_of_month: int,
                  category: str | None = None, account: str | None = None, *,
                  db: Session | None = None) -> dict:
    """Add a recurring bill/EMI/subscription/salary (flow='expense'|'income') due on a day."""
    def op(db):
        group, member = _ctx(db)
        acc = crud.find_account(db, group, account) if account else None
        r = crud.add_recurring(db, group, member, flow=flow, label=label, amount=float(amount),
                               day_of_month=int(day_of_month), category=category, account=acc)
        return {"ok": True, "id": r.id, "label": r.label, "flow": r.flow,
                "day_of_month": r.day_of_month}
    return _run(op, db)


def list_recurring(*, db: Session | None = None) -> dict:
    """List recurring items with their next due dates."""
    return _run(lambda db: {"recurring": reports.recurring_overview(db, _ctx(db)[0])}, db)


def reminders(*, db: Session | None = None) -> dict:
    """Items (recurring + insurance premiums) due in the next 7 days."""
    return _run(lambda db: {"reminders": reports.reminders(db, _ctx(db)[0], within_days=7)}, db)


def add_investment(name: str, kind: str = "other", invested: float = 0,
                   current: float | None = None, *, db: Session | None = None) -> dict:
    """Add an investment holding. `current` defaults to `invested` if omitted."""
    def op(db):
        group, member = _ctx(db)
        inv = crud.add_investment(db, group, member, name=name, kind=kind,
                                  invested=float(invested),
                                  current=float(current if current is not None else invested),
                                  as_of=date.today())
        return {"ok": True, "name": inv.name, "kind": inv.kind,
                "invested": float(inv.invested_amount), "current_value": float(inv.current_value)}
    return _run(op, db)


def update_investment(name: str, value: float, *, db: Session | None = None) -> dict:
    """Update a holding's current value (passive update)."""
    def op(db):
        group, _ = _ctx(db)
        inv = crud.find_investment(db, group, name)
        if inv is None:
            return {"ok": False, "error": f"No investment named '{name}'."}
        crud.update_investment_value(db, inv, float(value), date.today())
        return {"ok": True, "name": inv.name, "current_value": float(value),
                "gain": round(float(value) - float(inv.invested_amount), 2)}
    return _run(op, db)


def add_insurance(name: str, kind: str = "other", premium: float = 0,
                  due_date: str | None = None, frequency: str = "yearly", *,
                  db: Session | None = None) -> dict:
    """Add an insurance policy. `due_date` is YYYY-MM-DD."""
    def op(db):
        group, member = _ctx(db)
        due = datetime.strptime(due_date, "%Y-%m-%d").date() if due_date else None
        ins = crud.add_insurance(db, group, member, name=name, kind=kind, provider=None,
                                 premium=float(premium), frequency=frequency, due_date=due)
        return {"ok": True, "name": ins.name, "kind": ins.kind,
                "premium": float(ins.premium_amount), "frequency": ins.frequency,
                "due_date": ins.due_date.isoformat() if ins.due_date else None}
    return _run(op, db)


# --- queries -------------------------------------------------------------------

def list_accounts(*, db: Session | None = None) -> dict:
    """List accounts with current balances."""
    return _run(lambda db: {"accounts": reports.accounts_overview(db, _ctx(db)[0])}, db)


def list_investments(*, db: Session | None = None) -> dict:
    """List investments with gain/loss."""
    return _run(lambda db: {"investments": reports.investments_overview(db, _ctx(db)[0])}, db)


def upcoming_premiums(*, db: Session | None = None) -> dict:
    """List insurance policies with days until each premium is due."""
    return _run(lambda db: {"insurance": reports.upcoming_premiums(db, _ctx(db)[0])}, db)


def net_worth(*, db: Session | None = None) -> dict:
    """Household snapshot: cash in accounts + investments value = net worth."""
    return _run(lambda db: reports.net_worth(db, _ctx(db)[0]), db)


def settle_up(*, db: Session | None = None) -> dict:
    """Equal-split who-owes-whom across the household."""
    def op(db):
        s = reports.settle_up(db, _ctx(db)[0])
        return {"settlements": [{"debtor": x.debtor, "creditor": x.creditor, "amount": x.amount}
                                for x in s]}
    return _run(op, db)


def monthly_summary(*, db: Session | None = None) -> dict:
    """This month's income, expenses, net, and a category breakdown."""
    def op(db):
        group = _ctx(db)[0]
        today = date.today()
        start, end = reports.month_bounds(today.year, today.month)
        return {
            "currency": group.currency,
            "income": reports.income_total(db, group, start=start, end=end),
            "expenses": reports.total(db, group, start=start, end=end),
            "by_category": [{"category": c, "amount": a}
                            for c, a in reports.by_category(db, group, start=start, end=end)],
        }
    return _run(op, db)


def recent_expenses(limit: int = 20, *, db: Session | None = None) -> dict:
    """Most recent expenses (for the dashboard)."""
    def op(db):
        from sqlalchemy import select
        from app.models import Expense, Member
        group = _ctx(db)[0]
        rows = db.execute(
            select(Expense, Member)
            .join(Member, Member.id == Expense.member_id, isouter=True)
            .where(Expense.group_id == group.id)
            .order_by(Expense.spent_at.desc(), Expense.id.desc())
            .limit(limit)
        ).all()
        return {"expenses": [{
            "amount": float(e.amount), "currency": e.currency, "category": e.category,
            "note": e.note, "payer": (m.display_name or m.wa_user_id) if m else None,
            "spent_at": e.spent_at.isoformat(),
        } for e, m in rows]}
    return _run(op, db)
