"""Interactive onboarding flow (per-member state machine).

When a new family member first speaks (or sends /start), the bot walks them through:
  1. their name
  2. their accounts (bank name + last 4, or credit cards)
State is stored per member in ConversationState so several people can onboard at once
without their replies being mistaken for expenses.

A member's plain messages are routed here (instead of the expense parser) only while
they have an active onboarding state.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime

from sqlalchemy.orm import Session

from . import crud
from .models import ConversationState, Group, Member

FLOW = "onboarding"
STEP_NAME = "awaiting_name"
STEP_ACCOUNTS = "awaiting_accounts"

# "HDFC 1234", "ICICI credit 5678", "Amex cc 9012", and with an optional balance:
# "HDFC 1234 50000"  (bank cash balance) / "ICICI credit 5678 12000" (amount owed on card)
_ACCOUNT_LINE = re.compile(
    r"^\s*([A-Za-z][\w &]*?)\s+(?:(credit|cc|card)\s+)?(\d{4})"
    r"(?:\s+[₹$€£]?(\d[\d,]*(?:\.\d+)?))?\s*$",
    re.IGNORECASE,
)


def get_state(db: Session, member: Member) -> ConversationState | None:
    return db.get(ConversationState, member.id)


def start(db: Session, member: Member) -> str:
    """Begin onboarding for a member. Returns the first prompt."""
    state = db.get(ConversationState, member.id)
    if state is None:
        state = ConversationState(member_id=member.id, flow=FLOW, step=STEP_NAME,
                                  scratch=json.dumps({}))
        db.add(state)
    else:
        state.flow, state.step, state.scratch = FLOW, STEP_NAME, json.dumps({})
    state.updated_at = datetime.utcnow()
    db.flush()
    return "👋 Welcome! Let's set you up. *What's your name?*"


def is_active(db: Session, member: Member) -> bool:
    state = db.get(ConversationState, member.id)
    return state is not None and state.flow == FLOW


def handle(db: Session, group: Group, member: Member, text: str) -> str:
    """Advance the onboarding flow with the member's latest message."""
    state = db.get(ConversationState, member.id)
    if state is None:
        return start(db, member)

    text = text.strip()

    if state.step == STEP_NAME:
        name = text[:80].strip()
        if not name:
            return "Please tell me your name 🙂"
        member.display_name = name
        state.step = STEP_ACCOUNTS
        state.updated_at = datetime.utcnow()
        db.flush()
        return (
            f"Nice to meet you, *{name}*! 🏦\n"
            "Now add your accounts, one per message, like:\n"
            "• `HDFC 1234`  (bank)\n"
            "• `HDFC 1234 50000`  (bank + current balance)\n"
            "• `ICICI credit 5678`  (credit card)\n"
            "• `ICICI credit 5678 12000`  (card + amount currently owed)\n"
            "You can add as many as you like. Type *done* when finished, or *skip*."
        )

    if state.step == STEP_ACCOUNTS:
        low = text.lower()
        if low in ("done", "skip", "finish", "/done"):
            member.onboarded = True
            accounts = crud.list_accounts(db, group, member)
            _clear(db, state)
            summary = (
                "  " + "\n  ".join(f"• {a.bank_name} ****{a.last4}"
                                   f"{' (credit card)' if a.kind == 'credit_card' else ''}"
                                   for a in accounts)
                if accounts else "  (none added)"
            )
            return (
                f"✅ All set, {member.display_name}! Your accounts:\n{summary}\n\n"
                "Now you can log money. Try:\n"
                "• `Lunch 250 #food >hdfc` — an expense (debits HDFC)\n"
                "• `/income 50000 salary >hdfc` — income (credits HDFC)\n"
                "• `/help` — see everything I can do."
            )

        m = _ACCOUNT_LINE.match(text)
        if not m:
            return ("I didn't catch that. Use `<Bank> <last4>` e.g. `HDFC 1234` "
                    "(optionally a balance: `HDFC 1234 50000`), or `<Bank> credit <last4>` "
                    "for a card. Type *done* when finished.")
        bank, card_flag, last4, amt = (m.group(1).strip(), m.group(2), m.group(3), m.group(4))
        kind = "credit_card" if card_flag else "bank"
        # Bank balance is cash (positive); a credit-card balance is money owed (negative).
        opening = 0.0
        if amt:
            value = float(amt.replace(",", ""))
            opening = -value if kind == "credit_card" else value
        crud.add_account(db, group, member, bank_name=bank, last4=last4, kind=kind,
                         opening_balance=opening)
        db.flush()
        label = "credit card" if kind == "credit_card" else "account"
        bal = ""
        if amt:
            v = float(amt.replace(",", ""))
            bal = f", owe {v:,.0f}" if kind == "credit_card" else f", balance {v:,.0f}"
        return f"➕ Added {bank} ****{last4} ({label}{bal}). Add another, or type *done*."

    # Unknown step -> reset cleanly.
    _clear(db, state)
    return start(db, member)


def _clear(db: Session, state: ConversationState) -> None:
    db.delete(state)
    db.flush()


def welcome_message() -> str:
    """Posted to the group when the bot is added (group_lifecycle webhook)."""
    return (
        "👨‍👩‍👧‍👦 *Family Finance Tracker* is here!\n"
        "I'll help track expenses, income, accounts, investments and insurance for the whole family.\n\n"
        "Everyone: send *`/start`* and I'll set you up (your name + accounts). "
        "Your account details stay private — I only store the bank name and last 4 digits."
    )
