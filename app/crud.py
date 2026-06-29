"""Persistence helpers. Pure DB logic, no FastAPI/HTTP here so it's easy to test."""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .config import settings
from .models import (
    Account,
    Budget,
    Expense,
    Group,
    InboundEvent,
    Income,
    Insurance,
    Investment,
    Loan,
    LoanPayment,
    Member,
    Recurring,
    Transfer,
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
    shared: bool = True,
) -> Expense | None:
    """Insert an expense. Returns None if this wa_message_id was already stored (idempotent).

    If `account` is given, the expense debits it (reflected by reports.account_balance).
    `shared=False` marks it personal — excluded from settle-up.
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
        shared=shared,
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


def set_account_balance(db: Session, account: Account, target_balance: float) -> Account:
    """Set the account's *current* displayed balance to `target_balance`.

    Because balance is computed (opening + income credited − expenses debited), we adjust
    the opening_balance so the displayed balance equals the target, preserving all logged
    transactions. For a credit card, pass a NEGATIVE target (it's money owed).
    """
    credits = float(db.scalar(
        select(func.coalesce(func.sum(Income.amount), 0)).where(Income.account_id == account.id)
    ) or 0)
    debits = float(db.scalar(
        select(func.coalesce(func.sum(Expense.amount), 0)).where(Expense.account_id == account.id)
    ) or 0)
    movement = credits - debits           # net effect of logged transactions
    account.opening_balance = round(float(target_balance) - movement, 2)
    db.flush()
    return account


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


# --- transfers (between own accounts) -----------------------------------------

def create_transfer(db: Session, *, group: Group, member: Member | None,
                    from_account: Account, to_account: Account, amount: float,
                    currency: str, on: date, note: str | None = None,
                    wa_message_id: str | None = None) -> Transfer | None:
    if wa_message_id and db.scalar(
            select(Transfer.id).where(Transfer.wa_message_id == wa_message_id)):
        return None
    t = Transfer(group_id=group.id, member_id=member.id if member else None,
                 from_account_id=from_account.id, to_account_id=to_account.id,
                 amount=float(amount), currency=currency, transferred_on=on, note=note,
                 wa_message_id=wa_message_id)
    db.add(t)
    db.flush()
    return t


# --- loans (borrowed from / lent to) ------------------------------------------

def add_loan(db: Session, group: Group, member: Member | None, *, direction: str,
             counterparty: str, principal: float, on: date,
             account: Account | None = None, note: str | None = None) -> Loan:
    ln = Loan(group_id=group.id, member_id=member.id if member else None,
              direction=direction, counterparty=counterparty, principal=float(principal),
              account_id=account.id if account else None, opened_on=on, note=note)
    db.add(ln)
    db.flush()
    return ln


def find_loan(db: Session, group: Group, counterparty: str,
              direction: str | None = None) -> Loan | None:
    q = select(Loan).where(Loan.group_id == group.id,
                           func.lower(Loan.counterparty) == counterparty.lower())
    if direction:
        q = q.where(Loan.direction == direction)
    return db.scalar(q.order_by(Loan.id.desc()))


def add_loan_payment(db: Session, loan: Loan, *, amount: float, on: date,
                     account: Account | None = None, note: str | None = None) -> LoanPayment:
    p = LoanPayment(loan_id=loan.id, amount=float(amount),
                    account_id=account.id if account else None, paid_on=on, note=note)
    db.add(p)
    db.flush()
    return p


def list_loans(db: Session, group: Group) -> list[Loan]:
    return list(db.scalars(
        select(Loan).where(Loan.group_id == group.id).order_by(Loan.id)).all())


# --- budgets ------------------------------------------------------------------

def find_budget(db: Session, group: Group, category: str) -> Budget | None:
    return db.scalar(select(Budget).where(
        Budget.group_id == group.id, func.lower(Budget.category) == category.lower()))


def set_budget(db: Session, group: Group, category: str, monthly_limit: float) -> Budget:
    b = find_budget(db, group, category)
    if b is None:
        b = Budget(group_id=group.id, category=category, monthly_limit=float(monthly_limit))
        db.add(b)
    else:
        b.monthly_limit = float(monthly_limit)
    db.flush()
    return b


def list_budgets(db: Session, group: Group) -> list[Budget]:
    return list(db.scalars(
        select(Budget).where(Budget.group_id == group.id).order_by(Budget.category)).all())


def delete_budget(db: Session, group: Group, category: str) -> bool:
    b = find_budget(db, group, category)
    if b is None:
        return False
    db.delete(b)
    db.flush()
    return True


# --- recurring ----------------------------------------------------------------

def add_recurring(db: Session, group: Group, member: Member | None, *, flow: str, label: str,
                  amount: float, day_of_month: int, category: str | None = None,
                  account: Account | None = None) -> Recurring:
    r = Recurring(group_id=group.id, member_id=member.id if member else None, flow=flow,
                  label=label, amount=float(amount), category=category,
                  account_id=account.id if account else None,
                  day_of_month=max(1, min(31, int(day_of_month))), active=True)
    db.add(r)
    db.flush()
    return r


def list_recurring(db: Session, group: Group, active_only: bool = True) -> list[Recurring]:
    q = select(Recurring).where(Recurring.group_id == group.id)
    if active_only:
        q = q.where(Recurring.active.is_(True))
    return list(db.scalars(q.order_by(Recurring.day_of_month)).all())


def get_recurring(db: Session, group: Group, rid: int) -> Recurring | None:
    return db.scalar(select(Recurring).where(
        Recurring.group_id == group.id, Recurring.id == rid))


def delete_recurring(db: Session, group: Group, rid: int) -> bool:
    r = get_recurring(db, group, rid)
    if r is None:
        return False
    db.delete(r)
    db.flush()
    return True
