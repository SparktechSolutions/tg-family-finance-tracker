"""Aggregation / reporting queries. Used by both the bot commands and the web API."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Account, Expense, Group, Income, Insurance, Investment, Member

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


def month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, end


def total(db: Session, group: Group, *, category: str | None = None,
          start: date | None = None, end: date | None = None) -> float:
    q = select(func.coalesce(func.sum(Expense.amount), 0)).where(Expense.group_id == group.id)
    if category:
        q = q.where(func.lower(Expense.category) == category.lower())
    if start:
        q = q.where(Expense.spent_at >= start)
    if end:
        q = q.where(Expense.spent_at < end)
    return float(db.scalar(q) or 0)


def by_category(db: Session, group: Group, *, start: date | None = None,
                end: date | None = None) -> list[tuple[str, float]]:
    q = (
        select(Expense.category, func.sum(Expense.amount))
        .where(Expense.group_id == group.id)
        .group_by(Expense.category)
        .order_by(func.sum(Expense.amount).desc())
    )
    if start:
        q = q.where(Expense.spent_at >= start)
    if end:
        q = q.where(Expense.spent_at < end)
    return [(c, float(s)) for c, s in db.execute(q).all()]


def by_member(db: Session, group: Group, *, start: date | None = None,
              end: date | None = None) -> list[tuple[str, float]]:
    q = (
        select(func.coalesce(Member.display_name, Member.wa_user_id), func.sum(Expense.amount))
        .join(Member, Member.id == Expense.member_id, isouter=True)
        .where(Expense.group_id == group.id)
        .group_by(Member.id)
        .order_by(func.sum(Expense.amount).desc())
    )
    if start:
        q = q.where(Expense.spent_at >= start)
    if end:
        q = q.where(Expense.spent_at < end)
    return [(name or "Unknown", float(s)) for name, s in db.execute(q).all()]


def income_total(db: Session, group: Group, *, start: date | None = None,
                 end: date | None = None) -> float:
    q = select(func.coalesce(func.sum(Income.amount), 0)).where(Income.group_id == group.id)
    if start:
        q = q.where(Income.received_on >= start)
    if end:
        q = q.where(Income.received_on < end)
    return float(db.scalar(q) or 0)


def account_balance(db: Session, account: Account) -> float:
    """opening_balance + credits (income) - debits (expenses) on this account."""
    credits = float(db.scalar(
        select(func.coalesce(func.sum(Income.amount), 0))
        .where(Income.account_id == account.id)
    ) or 0)
    debits = float(db.scalar(
        select(func.coalesce(func.sum(Expense.amount), 0))
        .where(Expense.account_id == account.id)
    ) or 0)
    return round(float(account.opening_balance) + credits - debits, 2)


def accounts_overview(db: Session, group: Group) -> list[dict]:
    out = []
    accounts = db.scalars(
        select(Account).where(Account.group_id == group.id).order_by(Account.id)
    ).all()
    for a in accounts:
        owner = db.get(Member, a.member_id)
        out.append({
            "id": a.id,
            "owner": (owner.display_name or owner.wa_user_id) if owner else None,
            "kind": a.kind,
            "bank_name": a.bank_name,
            "last4": a.last4,
            "balance": account_balance(db, a),
        })
    return out


def investments_overview(db: Session, group: Group) -> list[dict]:
    out = []
    for inv in db.scalars(
        select(Investment).where(Investment.group_id == group.id).order_by(Investment.id)
    ).all():
        owner = db.get(Member, inv.member_id) if inv.member_id else None
        invested = float(inv.invested_amount)
        current = float(inv.current_value)
        out.append({
            "id": inv.id,
            "owner": (owner.display_name or owner.wa_user_id) if owner else None,
            "name": inv.name,
            "kind": inv.kind,
            "invested": invested,
            "current_value": current,
            "gain": round(current - invested, 2),
            "as_of": inv.as_of.isoformat(),
        })
    return out


def investments_value(db: Session, group: Group) -> float:
    return float(db.scalar(
        select(func.coalesce(func.sum(Investment.current_value), 0))
        .where(Investment.group_id == group.id)
    ) or 0)


def upcoming_premiums(db: Session, group: Group) -> list[dict]:
    out = []
    today = date.today()
    for ins in db.scalars(
        select(Insurance).where(Insurance.group_id == group.id)
        .order_by(Insurance.due_date.is_(None), Insurance.due_date)
    ).all():
        owner = db.get(Member, ins.member_id) if ins.member_id else None
        days = (ins.due_date - today).days if ins.due_date else None
        out.append({
            "id": ins.id,
            "owner": (owner.display_name or owner.wa_user_id) if owner else None,
            "name": ins.name,
            "kind": ins.kind,
            "provider": ins.provider,
            "premium": float(ins.premium_amount),
            "frequency": ins.frequency,
            "due_date": ins.due_date.isoformat() if ins.due_date else None,
            "days_until_due": days,
        })
    return out


def net_worth(db: Session, group: Group) -> dict:
    """Household snapshot: cash in accounts + investments value, plus income/expense flow."""
    accounts = accounts_overview(db, group)
    cash = round(sum(a["balance"] for a in accounts), 2)
    invest = round(investments_value(db, group), 2)
    return {
        "cash_in_accounts": cash,
        "investments_value": invest,
        "net_worth": round(cash + invest, 2),
        "total_income": income_total(db, group),
        "total_expenses": total(db, group),
    }


@dataclass
class Settlement:
    debtor: str
    creditor: str
    amount: float


def settle_up(db: Session, group: Group, *, start: date | None = None,
              end: date | None = None) -> list[Settlement]:
    """Equal-split 'who owes whom'. Assumes every member shares all expenses equally.

    Returns a minimal-ish set of transfers to square everyone up. Members who paid
    nothing still owe their share, so we seed every group member at 0.
    """
    paid = dict(by_member(db, group, start=start, end=end))
    if not paid:
        return []
    # Include all group members (even those who never paid) so they're charged a share.
    all_members = db.execute(
        select(func.coalesce(Member.display_name, Member.wa_user_id)).where(
            Member.group_id == group.id
        )
    ).scalars().all()
    for name in all_members:
        paid.setdefault(name or "Unknown", 0.0)
    members = list(paid.keys())
    grand_total = sum(paid.values())
    fair_share = grand_total / len(members)

    # net = paid - fair_share. Positive => owed money; negative => owes.
    balances = {m: round(paid[m] - fair_share, 2) for m in members}

    creditors = sorted(((m, b) for m, b in balances.items() if b > 0), key=lambda x: -x[1])
    debtors = sorted(((m, -b) for m, b in balances.items() if b < 0), key=lambda x: -x[1])

    settlements: list[Settlement] = []
    i = j = 0
    creditors = [list(c) for c in creditors]
    debtors = [list(d) for d in debtors]
    while i < len(debtors) and j < len(creditors):
        debtor, owe = debtors[i]
        creditor, due = creditors[j]
        pay = round(min(owe, due), 2)
        if pay > 0:
            settlements.append(Settlement(debtor=debtor, creditor=creditor, amount=pay))
        debtors[i][1] = round(owe - pay, 2)
        creditors[j][1] = round(due - pay, 2)
        if debtors[i][1] <= 0.01:
            i += 1
        if creditors[j][1] <= 0.01:
            j += 1
    return settlements
