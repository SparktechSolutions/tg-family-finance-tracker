"""Aggregation / reporting queries. Used by both the bot commands and the web API."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    Account,
    Budget,
    Expense,
    Group,
    Income,
    Insurance,
    Investment,
    Loan,
    LoanPayment,
    Member,
    Recurring,
    Transfer,
)

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
              end: date | None = None, shared_only: bool = False) -> list[tuple[str, float]]:
    q = (
        select(func.coalesce(Member.display_name, Member.wa_user_id), func.sum(Expense.amount))
        .join(Member, Member.id == Expense.member_id, isouter=True)
        .where(Expense.group_id == group.id)
        .group_by(Member.id)
        .order_by(func.sum(Expense.amount).desc())
    )
    if shared_only:
        q = q.where(Expense.shared.is_(True))      # exclude personal expenses from the split
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


def _sum(db, col, *where) -> float:
    return float(db.scalar(select(func.coalesce(func.sum(col), 0)).where(*where)) or 0)


def account_balance(db: Session, account: Account, asof: date | None = None) -> float:
    """Computed balance: opening + income − expenses ± transfers ± loan cash flows.

    If `asof` is given, only flows dated strictly before `asof` are counted — this gives
    the balance "as of" that date (used for opening/closing balances over a period). The
    opening_balance baseline is always included.

    Loan cash flows (only when a loan/payment is linked to this account):
      • borrowed loan principal received here → +;  lent loan principal sent from here → −
      • paying a borrowed loan from here → −;       a lent loan repaid into here → +
    """
    aid = account.id

    def lt(col):
        return [col < asof] if asof is not None else []

    credits = _sum(db, Income.amount, Income.account_id == aid, *lt(Income.received_on))
    debits = _sum(db, Expense.amount, Expense.account_id == aid, *lt(Expense.spent_at))
    xfer_in = _sum(db, Transfer.amount, Transfer.to_account_id == aid, *lt(Transfer.transferred_on))
    xfer_out = _sum(db, Transfer.amount, Transfer.from_account_id == aid, *lt(Transfer.transferred_on))

    loan_in = _sum(db, Loan.principal, Loan.account_id == aid, Loan.direction == "borrowed",
                   *lt(Loan.opened_on))
    loan_out = _sum(db, Loan.principal, Loan.account_id == aid, Loan.direction == "lent",
                    *lt(Loan.opened_on))
    pay_received = float(db.scalar(
        select(func.coalesce(func.sum(LoanPayment.amount), 0))
        .join(Loan, Loan.id == LoanPayment.loan_id)
        .where(LoanPayment.account_id == aid, Loan.direction == "lent", *lt(LoanPayment.paid_on))
    ) or 0)
    pay_made = float(db.scalar(
        select(func.coalesce(func.sum(LoanPayment.amount), 0))
        .join(Loan, Loan.id == LoanPayment.loan_id)
        .where(LoanPayment.account_id == aid, Loan.direction == "borrowed", *lt(LoanPayment.paid_on))
    ) or 0)

    bal = (float(account.opening_balance) + credits - debits + xfer_in - xfer_out
           + loan_in - loan_out + pay_received - pay_made)
    return round(bal, 2)


def period_summary(db: Session, group: Group, start: date, end: date) -> dict:
    """Income/expense/category/member totals for a period, plus opening & closing balances.

    Opening = total account balances as of `start`; closing = as of `end` (period included).
    """
    accounts = db.scalars(
        select(Account).where(Account.group_id == group.id).order_by(Account.id)).all()
    acc_rows = []
    for a in accounts:
        owner = db.get(Member, a.member_id) if a.member_id else None
        opening = account_balance(db, a, asof=start)
        closing = account_balance(db, a, asof=end)
        acc_rows.append({
            "id": a.id, "bank_name": a.bank_name, "last4": a.last4, "kind": a.kind,
            "owner": (owner.display_name or owner.wa_user_id) if owner else None,
            "opening": opening, "closing": closing, "change": round(closing - opening, 2),
        })
    opening_total = round(sum(r["opening"] for r in acc_rows), 2)
    closing_total = round(sum(r["closing"] for r in acc_rows), 2)
    inc = income_total(db, group, start=start, end=end)
    exp = total(db, group, start=start, end=end)
    return {
        "start": start.isoformat(), "end": end.isoformat(),
        "income": inc, "expenses": exp, "net": round(inc - exp, 2),
        "opening_balance": opening_total, "closing_balance": closing_total,
        "net_change": round(closing_total - opening_total, 2),
        "by_category": [{"category": c, "amount": s}
                        for c, s in by_category(db, group, start=start, end=end)],
        "by_member": [{"member": m, "amount": s}
                      for m, s in by_member(db, group, start=start, end=end)],
        "accounts": acc_rows,
    }


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


def loan_outstanding(db: Session, loan: Loan) -> float:
    paid = _sum(db, LoanPayment.amount, LoanPayment.loan_id == loan.id)
    return round(float(loan.principal) - paid, 2)


def loans_overview(db: Session, group: Group) -> list[dict]:
    out = []
    for ln in db.scalars(
        select(Loan).where(Loan.group_id == group.id).order_by(Loan.id)
    ).all():
        owner = db.get(Member, ln.member_id) if ln.member_id else None
        acct = db.get(Account, ln.account_id) if ln.account_id else None
        out.append({
            "id": ln.id,
            "direction": ln.direction,                       # 'borrowed' | 'lent'
            "counterparty": ln.counterparty,
            "principal": float(ln.principal),
            "outstanding": loan_outstanding(db, ln),
            "owner": (owner.display_name or owner.wa_user_id) if owner else None,
            "account": (f"{acct.bank_name} ****{acct.last4}" if acct else None),
            "opened_on": ln.opened_on.isoformat(),
        })
    return out


def loan_totals(db: Session, group: Group) -> dict:
    rows = loans_overview(db, group)
    lent = round(sum(r["outstanding"] for r in rows if r["direction"] == "lent"), 2)
    borrowed = round(sum(r["outstanding"] for r in rows if r["direction"] == "borrowed"), 2)
    return {"lent_outstanding": lent, "borrowed_outstanding": borrowed}


def net_worth(db: Session, group: Group) -> dict:
    """Household snapshot: cash + investments + money owed to you − money you owe."""
    accounts = accounts_overview(db, group)
    cash = round(sum(a["balance"] for a in accounts), 2)
    invest = round(investments_value(db, group), 2)
    lt = loan_totals(db, group)
    nw = round(cash + invest + lt["lent_outstanding"] - lt["borrowed_outstanding"], 2)
    return {
        "cash_in_accounts": cash,
        "investments_value": invest,
        "lent_outstanding": lt["lent_outstanding"],        # friends owe you (asset)
        "borrowed_outstanding": lt["borrowed_outstanding"],  # you owe (liability)
        "net_worth": nw,
        "total_income": income_total(db, group),
        "total_expenses": total(db, group),
    }


def budget_status(db: Session, group: Group, *, on: date | None = None) -> list[dict]:
    """For each budget: this-month spend in that category, limit, remaining, and percent."""
    today = on or date.today()
    start, end = month_bounds(today.year, today.month)
    out = []
    for b in db.scalars(
        select(Budget).where(Budget.group_id == group.id).order_by(Budget.category)
    ).all():
        spent = total(db, group, category=b.category, start=start, end=end)
        limit = float(b.monthly_limit)
        pct = round(100 * spent / limit, 1) if limit else 0.0
        out.append({"category": b.category, "limit": limit, "spent": round(spent, 2),
                    "remaining": round(limit - spent, 2), "pct": pct})
    return out


def budget_alert_for(db: Session, group: Group, category: str,
                     on: date | None = None) -> str | None:
    """Return a warning string if the category has a budget and is near/over it, else None."""
    b = db.scalar(select(Budget).where(
        Budget.group_id == group.id, func.lower(Budget.category) == category.lower()))
    if b is None:
        return None
    today = on or date.today()
    start, end = month_bounds(today.year, today.month)
    spent = total(db, group, category=b.category, start=start, end=end)
    limit = float(b.monthly_limit)
    if limit <= 0:
        return None
    pct = 100 * spent / limit
    cur = group.currency
    if spent > limit:
        return f"🔴 Over {b.category} budget: {cur} {spent:,.0f} of {cur} {limit:,.0f}"
    if pct >= 80:
        return f"🟠 {pct:.0f}% of {b.category} budget used ({cur} {spent:,.0f}/{cur} {limit:,.0f})"
    return None


def _next_due(day_of_month: int, today: date) -> date:
    import calendar
    y, m = today.year, today.month
    dom = min(day_of_month, calendar.monthrange(y, m)[1])
    candidate = date(y, m, dom)
    if candidate < today:
        m2, y2 = (m + 1, y) if m < 12 else (1, y + 1)
        dom2 = min(day_of_month, calendar.monthrange(y2, m2)[1])
        candidate = date(y2, m2, dom2)
    return candidate


def recurring_overview(db: Session, group: Group) -> list[dict]:
    today = date.today()
    out = []
    for r in db.scalars(
        select(Recurring).where(Recurring.group_id == group.id, Recurring.active.is_(True))
        .order_by(Recurring.day_of_month)
    ).all():
        due = _next_due(r.day_of_month, today)
        out.append({"id": r.id, "flow": r.flow, "label": r.label, "amount": float(r.amount),
                    "category": r.category, "day_of_month": r.day_of_month,
                    "next_due": due.isoformat(), "days_until": (due - today).days})
    return out


def reminders(db: Session, group: Group, within_days: int = 3) -> list[str]:
    """Human-readable reminders for recurring items and insurance premiums due soon."""
    cur = group.currency
    out = []
    for r in recurring_overview(db, group):
        if 0 <= r["days_until"] <= within_days:
            verb = "due" if r["flow"] == "expense" else "expected"
            when = "today" if r["days_until"] == 0 else f"in {r['days_until']}d"
            out.append(f"• {r['label']} — {cur} {r['amount']:,.0f} {verb} {when} ({r['next_due']})")
    for p in upcoming_premiums(db, group):
        d = p["days_until_due"]
        if d is not None and 0 <= d <= within_days:
            when = "today" if d == 0 else f"in {d}d"
            out.append(f"• 🛡️ {p['name']} premium — {cur} {p['premium']:,.0f} due {when} ({p['due_date']})")
    return out


@dataclass
class Settlement:
    debtor: str
    creditor: str
    amount: float


def settle_up(db: Session, group: Group, *, start: date | None = None,
              end: date | None = None) -> list[Settlement]:
    """Equal-split 'who owes whom' over SHARED expenses only (personal ones are excluded).

    Returns a minimal-ish set of transfers to square everyone up. Members who paid
    nothing still owe their share, so we seed every group member at 0.
    """
    paid = dict(by_member(db, group, start=start, end=end, shared_only=True))
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
