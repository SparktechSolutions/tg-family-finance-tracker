"""JSON + CSV API that powers the dashboard (reads + management writes)."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import crud, reports
from .db import get_session
from .models import Account, Expense, Group, Insurance, Investment, Member

router = APIRouter(prefix="/api")


def _get_group(db: Session, group_id: int | None, wa_group_id: str | None) -> Group:
    if group_id is not None:
        g = db.get(Group, group_id)
    elif wa_group_id is not None:
        g = db.scalar(select(Group).where(Group.wa_group_id == wa_group_id))
    else:
        g = db.scalar(select(Group).order_by(Group.id))  # default: first group
    if g is None:
        raise HTTPException(404, "group not found")
    return g


@router.get("/groups")
def list_groups(db: Session = Depends(get_session)):
    rows = db.scalars(select(Group).order_by(Group.id)).all()
    return [{"id": g.id, "name": g.name, "wa_group_id": g.wa_group_id, "currency": g.currency}
            for g in rows]


def _parse_d(s: str | None) -> date | None:
    return datetime.strptime(s, "%Y-%m-%d").date() if s else None


@router.get("/summary")
def summary(group_id: int | None = None, start: str | None = None, end: str | None = None,
            db: Session = Depends(get_session)):
    g = _get_group(db, group_id, None)
    today = date.today()
    m_start, m_end = reports.month_bounds(today.year, today.month)
    # Period defaults to the current month when not specified.
    p_start = _parse_d(start) or m_start
    p_end = _parse_d(end) or m_end
    period = reports.period_summary(db, g, p_start, p_end)
    nw = reports.net_worth(db, g)
    return {
        "group": {"id": g.id, "name": g.name, "currency": g.currency},
        "period": period,
        "total_all_time": reports.total(db, g),
        "total_this_month": period["expenses"],
        "income_this_month": period["income"],
        "income_all_time": reports.income_total(db, g),
        "net_worth": nw,
        "by_category": period["by_category"],
        "by_member": period["by_member"],
        "accounts": reports.accounts_overview(db, g),
        "investments": reports.investments_overview(db, g),
        "insurance": reports.upcoming_premiums(db, g),
        "loans": reports.loans_overview(db, g),
        "budgets": reports.budget_status(db, g),
        "recurring": reports.recurring_overview(db, g),
        "settlements": [
            {"debtor": s.debtor, "creditor": s.creditor, "amount": s.amount}
            for s in reports.settle_up(db, g)
        ],
    }


@router.get("/accounts")
def accounts(group_id: int | None = None, db: Session = Depends(get_session)):
    return reports.accounts_overview(db, _get_group(db, group_id, None))


@router.get("/investments")
def investments(group_id: int | None = None, db: Session = Depends(get_session)):
    return reports.investments_overview(db, _get_group(db, group_id, None))


@router.get("/insurance")
def insurance(group_id: int | None = None, db: Session = Depends(get_session)):
    return reports.upcoming_premiums(db, _get_group(db, group_id, None))


# --- members ------------------------------------------------------------------

@router.get("/members")
def list_members(group_id: int | None = None, db: Session = Depends(get_session)):
    g = _get_group(db, group_id, None)
    rows = db.scalars(select(Member).where(Member.group_id == g.id).order_by(Member.id)).all()
    return [{"id": m.id, "name": m.display_name or m.wa_user_id} for m in rows]


def _default_member(db: Session, g: Group, member_id: int | None) -> Member:
    if member_id is not None:
        m = db.get(Member, member_id)
        if m is not None:
            return m
    m = db.scalar(select(Member).where(Member.group_id == g.id).order_by(Member.id))
    if m is not None:
        return m
    return crud.get_or_create_member(db, g, "dashboard:Family", display_name="Family")


# --- management: accounts -----------------------------------------------------

class AccountIn(BaseModel):
    group_id: int | None = None
    member_id: int | None = None
    bank_name: str
    last4: str
    kind: str = "bank"          # "bank" | "credit_card"
    balance: float = 0          # bank: cash; credit_card: amount owed


class BalanceIn(BaseModel):
    balance: float


def _signed_opening(kind: str, balance: float) -> float:
    return -abs(float(balance)) if kind == "credit_card" else float(balance)


@router.post("/accounts")
def add_account(body: AccountIn, db: Session = Depends(get_session)):
    g = _get_group(db, body.group_id, None)
    member = _default_member(db, g, body.member_id)
    acc = crud.add_account(db, g, member, bank_name=body.bank_name, last4=body.last4,
                           kind=body.kind, opening_balance=_signed_opening(body.kind, body.balance))
    db.commit()
    return {"id": acc.id, "ok": True}


@router.patch("/accounts/{account_id}")
def update_account(account_id: int, body: dict, db: Session = Depends(get_session)):
    acc = db.get(Account, account_id)
    if acc is None:
        raise HTTPException(404, "account not found")
    if "bank_name" in body and body["bank_name"]:
        acc.bank_name = body["bank_name"]
    if "last4" in body and body["last4"]:
        acc.last4 = str(body["last4"])
    if "kind" in body and body["kind"] in ("bank", "credit_card"):
        acc.kind = body["kind"]
    if "balance" in body and body["balance"] is not None:
        crud.set_account_balance(db, acc, _signed_opening(acc.kind, body["balance"]))
    db.commit()
    return {"ok": True}


@router.delete("/accounts/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_session)):
    acc = db.get(Account, account_id)
    if acc is None:
        raise HTTPException(404, "account not found")
    db.delete(acc)
    db.commit()
    return {"ok": True}


# --- management: investments --------------------------------------------------

class InvestmentIn(BaseModel):
    group_id: int | None = None
    member_id: int | None = None
    name: str
    kind: str = "other"
    invested: float = 0
    current: float | None = None


@router.post("/investments")
def add_investment(body: InvestmentIn, db: Session = Depends(get_session)):
    g = _get_group(db, body.group_id, None)
    member = _default_member(db, g, body.member_id)
    inv = crud.add_investment(db, g, member, name=body.name, kind=body.kind,
                              invested=body.invested,
                              current=body.current if body.current is not None else body.invested,
                              as_of=date.today())
    db.commit()
    return {"id": inv.id, "ok": True}


@router.patch("/investments/{inv_id}")
def update_investment(inv_id: int, body: dict, db: Session = Depends(get_session)):
    inv = db.get(Investment, inv_id)
    if inv is None:
        raise HTTPException(404, "investment not found")
    if "current_value" in body and body["current_value"] is not None:
        crud.update_investment_value(db, inv, float(body["current_value"]), date.today())
    if "name" in body and body["name"]:
        inv.name = body["name"]
    db.commit()
    return {"ok": True}


@router.delete("/investments/{inv_id}")
def delete_investment(inv_id: int, db: Session = Depends(get_session)):
    inv = db.get(Investment, inv_id)
    if inv is None:
        raise HTTPException(404, "investment not found")
    db.delete(inv)
    db.commit()
    return {"ok": True}


# --- management: insurance ----------------------------------------------------

class InsuranceIn(BaseModel):
    group_id: int | None = None
    member_id: int | None = None
    name: str
    kind: str = "other"
    premium: float = 0
    due_date: str | None = None     # YYYY-MM-DD
    frequency: str = "yearly"


@router.post("/insurance")
def add_insurance(body: InsuranceIn, db: Session = Depends(get_session)):
    g = _get_group(db, body.group_id, None)
    member = _default_member(db, g, body.member_id)
    due = datetime.strptime(body.due_date, "%Y-%m-%d").date() if body.due_date else None
    ins = crud.add_insurance(db, g, member, name=body.name, kind=body.kind, provider=None,
                             premium=body.premium, frequency=body.frequency, due_date=due)
    db.commit()
    return {"id": ins.id, "ok": True}


@router.delete("/insurance/{ins_id}")
def delete_insurance(ins_id: int, db: Session = Depends(get_session)):
    ins = db.get(Insurance, ins_id)
    if ins is None:
        raise HTTPException(404, "insurance not found")
    db.delete(ins)
    db.commit()
    return {"ok": True}


# --- management: income (cash inflow) -----------------------------------------

class IncomeIn(BaseModel):
    group_id: int | None = None
    member_id: int | None = None
    amount: float
    source: str = "Income"
    account_id: int | None = None


@router.get("/incomes")
def incomes(group_id: int | None = None, start: str | None = None, end: str | None = None,
            limit: int = Query(300, le=1000), db: Session = Depends(get_session)):
    g = _get_group(db, group_id, None)
    return crud.list_incomes(db, g, start=_parse_d(start), end=_parse_d(end), limit=limit)


@router.post("/incomes")
def add_income(body: IncomeIn, db: Session = Depends(get_session)):
    g = _get_group(db, body.group_id, None)
    acc = db.get(Account, body.account_id) if body.account_id else None
    import uuid as _uuid
    inc = crud.create_income(
        db, group=g, member=_default_member(db, g, body.member_id), account=acc,
        amount=body.amount, currency=g.currency, source=body.source.capitalize(),
        note=body.source, received_on=date.today(),
        raw_message=f"income {body.amount} {body.source}", wa_message_id=f"dash-inc-{_uuid.uuid4()}")
    db.commit()
    return {"id": inc.id if inc else None, "ok": inc is not None}


@router.delete("/incomes/{income_id}")
def delete_income(income_id: int, group_id: int | None = None, db: Session = Depends(get_session)):
    g = _get_group(db, group_id, None)
    ok = crud.delete_income(db, g, income_id)
    db.commit()
    return {"ok": ok}


# --- management: transfers & loans --------------------------------------------

class TransferIn(BaseModel):
    group_id: int | None = None
    member_id: int | None = None
    from_account_id: int
    to_account_id: int
    amount: float


@router.post("/transfers")
def add_transfer(body: TransferIn, db: Session = Depends(get_session)):
    g = _get_group(db, body.group_id, None)
    src = db.get(Account, body.from_account_id)
    dst = db.get(Account, body.to_account_id)
    if src is None or dst is None:
        raise HTTPException(404, "account not found")
    if src.id == dst.id:
        raise HTTPException(400, "pick two different accounts")
    crud.create_transfer(db, group=g, member=_default_member(db, g, body.member_id),
                         from_account=src, to_account=dst, amount=body.amount,
                         currency=g.currency, on=date.today())
    db.commit()
    return {"ok": True}


@router.get("/loans")
def loans(group_id: int | None = None, db: Session = Depends(get_session)):
    return reports.loans_overview(db, _get_group(db, group_id, None))


class LoanIn(BaseModel):
    group_id: int | None = None
    member_id: int | None = None
    direction: str               # 'borrowed' | 'lent'
    counterparty: str
    principal: float
    account_id: int | None = None


@router.post("/loans")
def add_loan(body: LoanIn, db: Session = Depends(get_session)):
    g = _get_group(db, body.group_id, None)
    if body.direction not in ("borrowed", "lent"):
        raise HTTPException(400, "direction must be 'borrowed' or 'lent'")
    acc = db.get(Account, body.account_id) if body.account_id else None
    ln = crud.add_loan(db, g, _default_member(db, g, body.member_id), direction=body.direction,
                       counterparty=body.counterparty, principal=body.principal,
                       on=date.today(), account=acc)
    db.commit()
    return {"id": ln.id, "ok": True}


class LoanPaymentIn(BaseModel):
    amount: float
    account_id: int | None = None


@router.post("/loans/{loan_id}/payments")
def add_loan_payment(loan_id: int, body: LoanPaymentIn, db: Session = Depends(get_session)):
    from .models import Loan
    ln = db.get(Loan, loan_id)
    if ln is None:
        raise HTTPException(404, "loan not found")
    acc = db.get(Account, body.account_id) if body.account_id else None
    crud.add_loan_payment(db, ln, amount=body.amount, on=date.today(), account=acc)
    db.commit()
    return {"ok": True, "outstanding": reports.loan_outstanding(db, ln)}


@router.delete("/loans/{loan_id}")
def delete_loan(loan_id: int, db: Session = Depends(get_session)):
    from .models import Loan, LoanPayment
    ln = db.get(Loan, loan_id)
    if ln is None:
        raise HTTPException(404, "loan not found")
    for p in db.scalars(select(LoanPayment).where(LoanPayment.loan_id == loan_id)).all():
        db.delete(p)
    db.delete(ln)
    db.commit()
    return {"ok": True}


# --- management: budgets & recurring ------------------------------------------

class BudgetIn(BaseModel):
    group_id: int | None = None
    category: str
    monthly_limit: float


@router.get("/budgets")
def budgets(group_id: int | None = None, db: Session = Depends(get_session)):
    return reports.budget_status(db, _get_group(db, group_id, None))


@router.post("/budgets")
def set_budget(body: BudgetIn, db: Session = Depends(get_session)):
    g = _get_group(db, body.group_id, None)
    crud.set_budget(db, g, body.category, body.monthly_limit)
    db.commit()
    return {"ok": True}


@router.delete("/budgets/{category}")
def delete_budget(category: str, group_id: int | None = None, db: Session = Depends(get_session)):
    g = _get_group(db, group_id, None)
    ok = crud.delete_budget(db, g, category)
    db.commit()
    return {"ok": ok}


class RecurringIn(BaseModel):
    group_id: int | None = None
    member_id: int | None = None
    flow: str = "expense"          # 'expense' | 'income'
    label: str
    amount: float
    day_of_month: int
    category: str | None = None
    account_id: int | None = None


@router.get("/recurring")
def recurring(group_id: int | None = None, db: Session = Depends(get_session)):
    return reports.recurring_overview(db, _get_group(db, group_id, None))


@router.post("/recurring")
def add_recurring(body: RecurringIn, db: Session = Depends(get_session)):
    g = _get_group(db, body.group_id, None)
    acc = db.get(Account, body.account_id) if body.account_id else None
    r = crud.add_recurring(db, g, _default_member(db, g, body.member_id), flow=body.flow,
                           label=body.label, amount=body.amount, day_of_month=body.day_of_month,
                           category=body.category, account=acc)
    db.commit()
    return {"id": r.id, "ok": True}


@router.delete("/recurring/{rid}")
def delete_recurring(rid: int, group_id: int | None = None, db: Session = Depends(get_session)):
    g = _get_group(db, group_id, None)
    ok = crud.delete_recurring(db, g, rid)
    db.commit()
    return {"ok": ok}


@router.get("/reminders")
def reminders(group_id: int | None = None, db: Session = Depends(get_session)):
    return {"reminders": reports.reminders(db, _get_group(db, group_id, None), within_days=7)}


@router.post("/import/chat")
async def import_chat(request: Request, wa_group_id: str, currency: str = "INR",
                      db: Session = Depends(get_session)):
    """Backfill from a WhatsApp chat export. POST the raw .txt as the request body.

    Used to catch up after the server was offline (WhatsApp has no message-history API).
    Re-imports are idempotent — already-seen lines are skipped.
    """
    from .importer import import_chat_text
    body = (await request.body()).decode("utf-8", errors="ignore")
    res = import_chat_text(body, wa_group_id=wa_group_id, currency=currency, db=db)
    db.commit()
    return {"expenses": res.expenses, "refunds": res.refunds,
            "duplicates": res.duplicates, "skipped": res.skipped, "messages": res.lines}


class ExpenseIn(BaseModel):
    group_id: int | None = None
    member_id: int | None = None       # payer; defaults to the group's first member
    amount: float
    note: str = ""                     # free-text description
    category: str | None = None        # None/"Auto" -> inferred from the note
    account_id: int | None = None      # source to debit (bank balance down / card owed up)
    spent_at: str | None = None        # ISO date; defaults to today
    shared: bool = True                # False = personal (excluded from settle-up)


@router.post("/expenses")
def add_expense(body: ExpenseIn, db: Session = Depends(get_session)):
    """Log an expense from the dashboard, debiting an optional source account."""
    g = _get_group(db, body.group_id, None)
    if not body.amount or body.amount <= 0:
        raise HTTPException(400, "amount must be greater than 0")
    acc = db.get(Account, body.account_id) if body.account_id else None
    if body.account_id and acc is None:
        raise HTTPException(404, "account not found")
    note = (body.note or "").strip()
    # Infer the category from the description unless one was explicitly chosen.
    cat = (body.category or "").strip()
    if not cat or cat.lower() == "auto":
        from .parser import _infer_category
        cat = _infer_category(note, None)
    import uuid as _uuid
    exp = crud.create_expense(
        db, group=g, member=_default_member(db, g, body.member_id), account=acc,
        amount=float(body.amount), currency=g.currency, category=cat,
        note=note or cat, spent_at=_parse_d(body.spent_at) or date.today(),
        raw_message=note or f"{cat} {body.amount}",
        wa_message_id=f"dash-exp-{_uuid.uuid4()}", shared=body.shared)
    db.commit()
    return {"id": exp.id if exp else None, "ok": exp is not None,
            "category": cat,
            "account": (f"{acc.bank_name} ****{acc.last4}" if acc else None)}


@router.delete("/expenses/{expense_id}")
def remove_expense(expense_id: int, group_id: int | None = None,
                   db: Session = Depends(get_session)):
    g = _get_group(db, group_id, None)
    ok = crud.delete_expense(db, g, expense_id)
    db.commit()
    return {"ok": ok}


@router.get("/expenses")
def list_expenses(
    group_id: int | None = None,
    category: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = Query(200, le=1000),
    db: Session = Depends(get_session),
):
    g = _get_group(db, group_id, None)
    q = (
        select(Expense, Member, Account)
        .join(Member, Member.id == Expense.member_id, isouter=True)
        .join(Account, Account.id == Expense.account_id, isouter=True)
        .where(Expense.group_id == g.id)
        .order_by(Expense.spent_at.desc(), Expense.id.desc())
        .limit(limit)
    )
    if category:
        q = q.where(Expense.category == category)
    if start:
        q = q.where(Expense.spent_at >= _parse_d(start))
    if end:
        q = q.where(Expense.spent_at < _parse_d(end))
    out = []
    for exp, mem, acc in db.execute(q).all():
        out.append({
            "id": exp.id,
            "amount": float(exp.amount),
            "currency": exp.currency,
            "category": exp.category,
            "note": exp.note,
            "payer": (mem.display_name or mem.wa_user_id) if mem else None,
            "account": (f"{acc.bank_name} ****{acc.last4}" if acc else None),
            "account_id": exp.account_id,
            "spent_at": exp.spent_at.isoformat(),
            "is_refund": bool(exp.is_refund),
        })
    return out


@router.get("/expenses.csv")
def export_csv(group_id: int | None = None, db: Session = Depends(get_session)):
    g = _get_group(db, group_id, None)
    rows = list_expenses(group_id=g.id, db=db, limit=1000)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["date", "amount", "currency", "category", "note", "payer"])
    for r in rows:
        writer.writerow([r["spent_at"], r["amount"], r["currency"], r["category"],
                         r["note"], r["payer"]])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="expenses_group_{g.id}.csv"'},
    )
