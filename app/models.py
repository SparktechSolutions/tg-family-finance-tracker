"""SQLAlchemy models. See docs/architecture.md section 4 for the design rationale.

Entities:
  Group, Member            - the chat and its participants
  Account                  - a bank account or credit card (bank name + last4 only)
  Expense                  - money out  (debits its source Account if given)
  Income                   - money in   (credits its destination Account if given)
  Investment               - a holding with a periodically-updated current value
  Insurance                - a policy with a recurring premium + due date
  ConversationState        - per-member state for the interactive onboarding flow
"""
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    wa_group_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    members: Mapped[list["Member"]] = relationship(back_populates="group")
    expenses: Mapped[list["Expense"]] = relationship(back_populates="group")


class Member(Base):
    __tablename__ = "members"
    __table_args__ = (UniqueConstraint("group_id", "wa_user_id", name="uq_group_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    wa_user_id: Mapped[str] = mapped_column(String(128), index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    onboarded: Mapped[bool] = mapped_column(Boolean, default=False)

    group: Mapped["Group"] = relationship(back_populates="members")
    accounts: Mapped[list["Account"]] = relationship(back_populates="member")


class Account(Base):
    """A bank account or credit card. Stores ONLY bank name + last 4 digits (privacy)."""
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    kind: Mapped[str] = mapped_column(String(16), default="bank")  # 'bank' | 'credit_card'
    bank_name: Mapped[str] = mapped_column(String(64))
    last4: Mapped[str] = mapped_column(String(4))
    opening_balance: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    member: Mapped["Member"] = relationship(back_populates="accounts")


class Expense(Base):
    """A money-out record.

    Refunds are stored here too, as a row with `is_refund=True` and a **negative**
    `amount`. Storing refunds as negative expenses means every SUM-based report
    (category totals, account balances, monthly net) nets out automatically — a refund
    reduces spend and credits the source account with no special-casing in the queries.
    The `is_refund` flag is only for display ("↩️ Refund …") and linking.
    """
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2))  # negative for refunds
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    category: Mapped[str] = mapped_column(String(64), default="Uncategorized")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    spent_at: Mapped[date] = mapped_column(Date)
    raw_message: Mapped[str] = mapped_column(Text)
    wa_message_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    is_refund: Mapped[bool] = mapped_column(Boolean, default=False)
    shared: Mapped[bool] = mapped_column(Boolean, default=True)   # False = personal, no split
    original_expense_id: Mapped[int | None] = mapped_column(
        ForeignKey("expenses.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    group: Mapped["Group"] = relationship(back_populates="expenses")
    member: Mapped["Member | None"] = relationship()
    account: Mapped["Account | None"] = relationship()


class Income(Base):
    __tablename__ = "incomes"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    source: Mapped[str] = mapped_column(String(64), default="Income")  # salary, bonus, ...
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_on: Mapped[date] = mapped_column(Date)
    raw_message: Mapped[str] = mapped_column(Text)
    wa_message_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    member: Mapped["Member | None"] = relationship()
    account: Mapped["Account | None"] = relationship()


class Investment(Base):
    """A holding. `current_value` is updated periodically ('passive updates')."""
    __tablename__ = "investments"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(32), default="other")  # stocks, mf, fd, crypto...
    invested_amount: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    current_value: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    as_of: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    member: Mapped["Member | None"] = relationship()


class Insurance(Base):
    __tablename__ = "insurances"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(32), default="other")  # life, health, motor...
    provider: Mapped[str | None] = mapped_column(String(120), nullable=True)
    premium_amount: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    frequency: Mapped[str] = mapped_column(String(16), default="yearly")  # monthly|quarterly|yearly
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    member: Mapped["Member | None"] = relationship()


class ConversationState(Base):
    """Per-member state for the interactive onboarding (and future guided flows)."""
    __tablename__ = "conversation_state"

    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), primary_key=True)
    flow: Mapped[str] = mapped_column(String(32))           # e.g. 'onboarding'
    step: Mapped[str] = mapped_column(String(32))           # e.g. 'awaiting_name'
    scratch: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON blob
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class InboundEvent(Base):
    """Durable log of every raw webhook payload, stored BEFORE processing.

    Purpose:
      • Crash-safety — if processing fails midway (server up, logic error), the raw event
        is already persisted and can be reprocessed; nothing is lost.
      • Idempotency/audit — Meta re-delivers webhooks; `dedupe_key` (the wa_message_id when
        present) lets us skip already-handled events and gives a full audit trail.

    NOTE: this does NOT recover messages that arrived while the server was fully OFF —
    WhatsApp has no history API. For that, use the chat-export importer (app/importer.py).
    """
    __tablename__ = "inbound_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(160), unique=True, index=True)
    payload: Mapped[str] = mapped_column(Text)              # raw JSON
    source: Mapped[str] = mapped_column(String(32), default="webhook")  # webhook|import|retry
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Transfer(Base):
    """A self-transfer of money between two of your own accounts.

    Moves cash from `from_account` to `to_account`; net worth is unchanged. Reflected in
    each account's computed balance (out −, in +), without touching income/expense reports.
    """
    __tablename__ = "transfers"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    from_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    to_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    amount: Mapped[float] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    transferred_on: Mapped[date] = mapped_column(Date)
    wa_message_id: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Loan(Base):
    """A loan, in one of two directions:

      • direction='borrowed' — you borrowed from `counterparty` (a bank/person). A liability
        that reduces net worth. If linked to an account, the principal was received there.
      • direction='lent'     — you lent to `counterparty` (a friend). An asset that increases
        net worth. If linked to an account, the principal went out from there.

    Outstanding = principal − sum(payments). Payments reduce it (you repaying a borrowed
    loan, or a friend repaying a lent loan).
    """
    __tablename__ = "loans"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    direction: Mapped[str] = mapped_column(String(16))          # 'borrowed' | 'lent'
    counterparty: Mapped[str] = mapped_column(String(120))      # bank or friend name
    principal: Mapped[float] = mapped_column(Numeric(14, 2))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    opened_on: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    payments: Mapped[list["LoanPayment"]] = relationship(back_populates="loan")


class Budget(Base):
    """A monthly spending limit for a category (per group)."""
    __tablename__ = "budgets"
    __table_args__ = (UniqueConstraint("group_id", "category", name="uq_group_category"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    category: Mapped[str] = mapped_column(String(64))
    monthly_limit: Mapped[float] = mapped_column(Numeric(12, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Recurring(Base):
    """A recurring money item (bill, EMI, subscription, salary) due on a day each month.

    Drives reminders; it does NOT auto-post transactions — the family confirms each one.
    """
    __tablename__ = "recurring"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"))
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), nullable=True)
    flow: Mapped[str] = mapped_column(String(16))            # 'expense' | 'income'
    label: Mapped[str] = mapped_column(String(120))
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    day_of_month: Mapped[int] = mapped_column()             # 1..31
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_reminded_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class LoanPayment(Base):
    """A payment against a loan. For a borrowed loan it's you paying it down; for a lent
    loan it's the friend repaying you. Reduces the loan's outstanding balance."""
    __tablename__ = "loan_payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    loan_id: Mapped[int] = mapped_column(ForeignKey("loans.id"))
    amount: Mapped[float] = mapped_column(Numeric(14, 2))
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id"), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_on: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    loan: Mapped["Loan"] = relationship(back_populates="payments")
