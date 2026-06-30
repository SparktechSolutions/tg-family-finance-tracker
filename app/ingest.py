"""Channel-agnostic message dispatch.

Both the WhatsApp webhook and the Telegram bot resolve a (group, member) for their
channel and then call `handle_text` — the routing logic (onboarding → command → refund →
expense) is identical regardless of where the message came from.

`handle_text` does NOT manage the session or commit; the caller owns the transaction.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from . import commands, crud, onboarding, reports
from .models import Group, Member
from .parser import is_command, is_refund, parse_expense


def handle_text(db: Session, group: Group, member: Member, text: str, *,
                message_id: str, spent_on: date | None = None) -> str | None:
    """Route one inbound text message. Returns the reply text, or None to stay silent.

    `message_id` is the idempotency key (stored as the expense/refund wa_message_id), so a
    re-delivered or re-imported message never double-counts.
    """
    text = (text or "").strip()
    if not text:
        return None

    # 1. Mid-onboarding? The reply belongs to that flow, not the parser.
    if onboarding.is_active(db, member):
        return onboarding.handle(db, group, member, text)

    # 2. Commands (incl. /start, which begins onboarding).
    if is_command(text):
        return commands.handle(db, group, member, text)

    # 3. Refund keyword ("refund 500 #food >hdfc") -> credit + net against spend.
    if is_refund(text):
        return commands.record_refund(db, group, member, text, group.currency, message_id)

    # 4. Otherwise treat it as an expense.
    parsed = parse_expense(text, default_currency=group.currency)
    if parsed is None:
        return None  # chatter, no amount

    payer = member
    if parsed.payer_hint:
        payer = crud.find_member_by_name(db, group, parsed.payer_hint) or \
            crud.get_or_create_member(db, group, parsed.payer_hint, display_name=parsed.payer_hint)

    # Resolve the source account to debit. Prefer an explicit '>hint'; otherwise fall back
    # to an account named in plain English ("... hsbc card", "... from sbi 8656").
    account = crud.find_account(db, group, parsed.account_hint) \
        if parsed.account_hint else None
    if account is None:
        account = crud.find_account_in_text(db, group, text, member=payer,
                                             skip_amount=parsed.amount)

    exp = crud.create_expense(
        db, group=group, member=payer, account=account, amount=parsed.amount,
        currency=parsed.currency or group.currency, category=parsed.category,
        note=parsed.note, spent_at=spent_on or date.today(),
        raw_message=text, wa_message_id=message_id, shared=parsed.shared,
    )
    if exp is None:
        return None  # duplicate delivery; already stored

    who = f" · paid by {payer.display_name}" if parsed.payer_hint and payer.display_name else ""
    note = f" · {parsed.note}" if parsed.note and parsed.note != parsed.category else ""
    acct = f" · from {account.bank_name} ****{account.last4}" if account else ""
    tag = " · personal" if not parsed.shared else ""
    confirm = f"✅ Logged {exp.currency} {parsed.amount:,.2f} · {parsed.category}{note}{who}{acct}{tag}"
    alert = reports.budget_alert_for(db, group, parsed.category, on=spent_on)
    if alert:
        confirm += f"\n{alert}"
    return confirm
