"""Persistence helpers. Pure DB logic, no FastAPI/HTTP here so it's easy to test."""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .config import settings
from .models import (
    Account,
    Expense,
    Group,
    InboundEvent,
    Income,
    Insurance,
    Investment,
    Member,
)


# --- get-or-create -------------------------------------------------------------

def get_or_create_group(db: Session, wa_group_id: str, name: str | None = None) -> Group:
    group = db.scalar(select(Group).where(Group.wa_group_id == wa_group_id))
    if group is None:
        group = Group(wa_group_id=wa_group_id, name=name, currency=settings.default_currency)
        db.add(group)
        db.flush()
    return group


def get_or_create_member(
    db: Session, group: Group, wa_user_id: str, display_name: str | None = None
) -> Member:
    member = db.scalar(
        select(Member).where(Member.group_id == group.id, Member.wa_user_id == wa_user_id)
    )
    if member is None:
        member = Member(group_id=group.id, wa_user_id=wa_user_id, display_name=display_name)
        db.add(member)
        db.flush()
    elif display_name and not member.display_name:
        member.display_name = display_name
    return member


def find_member_by_name(db: Session, group: Group, name: str) -> Member | None:
    """Resolve a '@name' payer hint to a member (case-insensitive display_name match)."""
    return db.scalar(
        select(Member).where(
            Member.group_id == group.id,
            func.lower(Member.display_name) == name.lower(),
        )
    )


# --- expenses ------------------------------------------------------------------

def expense_exists(db: Session, wa_message_id: str) -> bool:
    return db.scalar(select(Expense.id).where(Expense.wa_message_id == wa_message_id)) is not None


def create_expense(
    db: Session,
    *,
    group: Group,
    member: Member | None,
    amount: float,
    currency: str,
    category: str,
    note: str,
    spent_at: date,
    raw_message: str,
    wa_message_id: str,
    account: Account | None = None,
) -> Expense | None:
    """Insert an expense. Returns None if this wa_message_id was already stored (idempotent).

    If `account` is given, the expense debits it (reflected by reports.account_balance).
    """
    if expense_exists(db, wa_message_id):
        return None
    exp = Expense(
        group_id=group.id,
        member_id=member.id if member else None,
        account_id=account.id if account else None,
        amount=amount,
        currency=currency,
        category=category,
        note=note,
        spent_at=spent_at,
        raw_message=raw_message,
        wa_message_id=wa_message_id,
    )
    db.add(exp)
    db.flush()
    return exp


def latest_expense(db: Session, group: Group, member: Member | None = None,
                   category: str | None = None) -> Expense | None:
    """Find the most recent real expense (not a refund) — used to link a refund to it."""
    q = select(Expense).where(Expense.group_id == group.id, Expense.is_refund.is_(False))
    if member is not None:
        q = q.where(Expense.member_id == member.id)
    if category is not None:
        q = q.where(func.lower(Expense.category) == category.lower())
    return db.scalar(q.order_by(Expense.created_at.desc(), Expense.id.desc()).limit(1))


def create_refund(
    db: Session,
    *,
    group: Group,
    member: Member | None,
    amount: float,
    currency: str,
    category: str,
    note: str,
    spent_at: date,
    raw_message: str,
    wa_message_id: str,
    account: Account | None = None,
    original: Expense | None = None,
) -> Expense | None:
    """Record a refund as a negative-amount expense (credits the account, reduces spend).

    Idempotent on wa_message_id. If `original` is given, the refund is linked to it and
    inherits its category/account when not otherwise specified.
    """
    if expense_exists(db, wa_message_id):
        return None
    if original is not None:
        category = category or original.category
        if account is None:
            account = db.get(Account, original.account_id) if original.account_id else None
    refund = Expense(
        group_id=group.id,
        member_id=member.id if member else None,
        account_id=account.id if account else None,
        amount=-abs(float(amount)),          # negative => nets against spend, credits account
        currency=currency,
        category=category or "Uncategorized",
        note=note,
        spent_at=spent_at,
        raw_message=raw_message,
        wa_message_id=wa_message_id,
        is_refund=True,
        original_expense_id=original.id if original else None,
    )
    db.add(refund)
    db.flush()
    return refund


def delete_last_expense(db: Session, group: Group, member: Member) -> Expense | None:
    """For /undo: remove the caller's most recent expense in this group."""
    exp = db.scalar(
        select(Expense)
        .where(Expense.group_id == group.id, Expense.member_id == member.id)
        .order_by(Expense.created_at.desc(), Expense.id.desc())
        .limit(1)
    )
    if exp is not None:
        db.delete(exp)
    return exp


# --- accounts ------------------------------------------------------------------

def add_account(db: Session, group: Group, member: Member, *, bank_name: str,
                last4: str, kind: str = "bank", opening_balance: float = 0) -> Account:
    acc = Account(group_id=group.id, member_id=member.id, bank_name=bank_name,
                  last4=last4, kind=kind, opening_balance=opening_balance)
    db.add(acc)
    db.flush()
    return acc


def list_accounts(db: Session, group: Group, member: Member | None = None) -> list[Account]:
    q = select(Account).where(Account.group_id == group.id)
    if member is not None:
        q = q.where(Account.member_id == member.id)
    return list(db.scalars(q.order_by(Account.id)).all())


def find_account(db: Session, group: Group, token: str,
                 member: Member | None = None) -> Account | None:
    """Resolve a '>hdfc' or '>1234' hint to an account (by bank name or last4)."""
    token = token.strip()
    q = select(Account).where(
        Account.group_id == group.id,
        or_(func.lower(Account.bank_name) == token.lower(), Account.last4 == token),
    )
    if member is not None:
        q = q.where(Account.member_id == member.id)
    return db.scalar(q.order_by(Account.id))


# --- income --------------------------------------------------------------------

def create_income(db: Session, *, group: Group, member: Member | None,
                  account: Account | None, amount: float, currency: str, source: str,
                  note: str, received_on: date, raw_message: str,
                  wa_message_id: str) -> Income | None:
    if db.scalar(select(Income.id).where(Income.wa_message_id == wa_message_id)):
        return None
    inc = Income(group_id=group.id, member_id=member.id if member else None,
                 account_id=account.id if account else None, amount=amount,
                 currency=currency, source=source, note=note, received_on=received_on,
                 raw_message=raw_message, wa_message_id=wa_message_id)
    db.add(inc)
    db.flush()
    return inc


# --- investments ---------------------------------------------------------------

def find_investment(db: Session, group: Group, name: str) -> Investment | None:
    return db.scalar(
        select(Investment).where(
            Investment.group_id == group.id,
            func.lower(Investment.name) == name.lower(),
        )
    )


def add_investment(db: Session, group: Group, member: Member | None, *, name: str,
                   kind: str, invested: float, current: float, as_of: date,
                   note: str | None = None) -> Investment:
    inv = Investment(group_id=group.id, member_id=member.id if member else None,
                     name=name, kind=kind, invested_amount=invested,
                     current_value=current, as_of=as_of, note=note)
    db.add(inv)
    db.flush()
    return inv


def update_investment_value(db: Session, inv: Investment, current: float,
                            as_of: date) -> Investment:
    inv.current_value = current
    inv.as_of = as_of
    db.flush()
    return inv


def list_investments(db: Session, group: Group) -> list[Investment]:
    return list(db.scalars(
        select(Investment).where(Investment.group_id == group.id).order_by(Investment.id)
    ).all())


# --- insurance -----------------------------------------------------------------

def add_insurance(db: Session, group: Group, member: Member | None, *, name: str,
                  kind: str, provider: str | None, premium: float, frequency: str,
                  due_date: date | None, note: str | None = None) -> Insurance:
    ins = Insurance(group_id=group.id, member_id=member.id if member else None,
                    name=name, kind=kind, provider=provider, premium_amount=premium,
                    frequency=frequency, due_date=due_date, note=note)
    db.add(ins)
    db.flush()
    return ins


def list_insurances(db: Session, group: Group) -> list[Insurance]:
    return list(db.scalars(
        select(Insurance).where(Insurance.group_id == group.id)
        .order_by(Insurance.due_date.is_(None), Insurance.due_date)
    ).all())


# --- inbound event log (durability + idempotency) ------------------------------

def record_inbound_event(db: Session, *, payload: str, dedupe_key: str | None,
                         source: str = "webhook") -> tuple[InboundEvent, bool]:
    """Persist a raw event before processing. Returns (event, is_new).

    If an event with the same dedupe_key already exists (Meta re-delivery), returns the
    existing one with is_new=False so the caller can skip reprocessing.
    """
    if dedupe_key:
        existing = db.scalar(select(InboundEvent).where(InboundEvent.dedupe_key == dedupe_key))
        if existing is not None:
            return existing, False
    ev = InboundEvent(payload=payload, dedupe_key=dedupe_key, source=source, processed=False)
    db.add(ev)
    db.flush()
    return ev, True


def mark_event_processed(db: Session, event: InboundEvent, error: str | None = None) -> None:
    event.processed = error is None
    event.error = error
    db.flush()


def unprocessed_events(db: Session) -> list[InboundEvent]:
    return list(db.scalars(
        select(InboundEvent).where(InboundEvent.processed.is_(False)).order_by(InboundEvent.id)
    ).all())
