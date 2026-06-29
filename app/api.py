"""Read-only JSON + CSV API that powers the dashboard."""
from __future__ import annotations

import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import reports
from .db import get_session
from .models import Expense, Group, Member

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


@router.get("/summary")
def summary(group_id: int | None = None, db: Session = Depends(get_session)):
    g = _get_group(db, group_id, None)
    today = date.today()
    m_start, m_end = reports.month_bounds(today.year, today.month)
    nw = reports.net_worth(db, g)
    return {
        "group": {"id": g.id, "name": g.name, "currency": g.currency},
        "total_all_time": reports.total(db, g),
        "total_this_month": reports.total(db, g, start=m_start, end=m_end),
        "income_this_month": reports.income_total(db, g, start=m_start, end=m_end),
        "income_all_time": reports.income_total(db, g),
        "net_worth": nw,
        "by_category": [{"category": c, "amount": s} for c, s in reports.by_category(db, g)],
        "by_member": [{"member": m, "amount": s} for m, s in reports.by_member(db, g)],
        "accounts": reports.accounts_overview(db, g),
        "investments": reports.investments_overview(db, g),
        "insurance": reports.upcoming_premiums(db, g),
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


@router.get("/expenses")
def list_expenses(
    group_id: int | None = None,
    category: str | None = None,
    limit: int = Query(200, le=1000),
    db: Session = Depends(get_session),
):
    g = _get_group(db, group_id, None)
    q = (
        select(Expense, Member)
        .join(Member, Member.id == Expense.member_id, isouter=True)
        .where(Expense.group_id == g.id)
        .order_by(Expense.spent_at.desc(), Expense.id.desc())
        .limit(limit)
    )
    if category:
        q = q.where(Expense.category == category)
    out = []
    for exp, mem in db.execute(q).all():
        out.append({
            "id": exp.id,
            "amount": float(exp.amount),
            "currency": exp.currency,
            "category": exp.category,
            "note": exp.note,
            "payer": (mem.display_name or mem.wa_user_id) if mem else None,
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
