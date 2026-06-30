"""Bot command handlers. Each returns the text the bot should reply with.

Pure functions of (db, group, member, text) -> str, so they're unit-testable.
Structured commands (income/invest/insurance) use forgiving token parsing rather than
strict positional args, since real family members won't type perfect syntax.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import crud, onboarding, reports
from .models import Group, Member
from .parser import parse_refund

HELP_TEXT = (
    "💸 *Family Finance Tracker*\n"
    "*Log an expense:* `<what> <amount> [#category] [@payer] [>account]`\n"
    "  e.g. `Lunch 250 #food >hdfc`\n\n"
    "*Money & accounts:*\n"
    "• `/start` — set up your name + accounts\n"
    "• `/accounts` — list accounts & balances\n"
    "• `/account add HDFC 1234 50000` — add an account with a balance\n"
    "• `/account add ICICI credit 5678 12000` — add a card with amount owed\n"
    "• `/account balance HDFC 60000` — set a balance (or a card's owed) anytime\n"
    "• `/income <amount> [source] [>account]` — e.g. `/income 50000 salary >hdfc`\n\n"
    "*Investments:*\n"
    "• `/invest add <kind> <amount> <name>` — e.g. `/invest add mf 100000 Axis Bluechip`\n"
    "• `/invest update <name> <value>` — passive value update\n"
    "• `/investments` — list holdings\n\n"
    "*Insurance:*\n"
    "• `/insurance add <kind> <premium> <YYYY-MM-DD> <name>`\n"
    "• `/due` — upcoming premiums\n\n"
    "*Transfers & loans:*\n"
    "• `/transfer <amount> <from> <to>` — move money between your accounts\n"
    "• `/paycard <card> <amount> from <source>` — pay a card due (owed ↓, source ↓)\n"
    "• `/lend <amount> <friend> [>account]` — you lent money (they owe you)\n"
    "• `/borrow <amount> <lender> [>account]` — you borrowed (you owe)\n"
    "• `/loan pay <lender> <amount>` · `/loan collect <friend> <amount>` · `/loans`\n\n"
    "*Budgets & recurring:*\n"
    "• `/budget set <category> <amount>` · `/budget` — monthly limits + status\n"
    "• `/recurring add expense 15000 1 Rent` — bills/EMIs/subscriptions (day of month)\n"
    "• `/upcoming` — what's due soon\n\n"
    "*Personal expense:* add `!personal` to keep it out of the split (e.g. `Spa 1500 !personal`)\n\n"
    "*Refund:* `/refund <amount> [#category] [>account]` — money back (nets spend, credits account)\n\n"
    "*Reports:* `/total` · `/total <category>` · `/month <name>` · "
    "`/split` · `/networth` · `/undo` · `/help`"
)

_INVEST_KINDS = {"stocks", "stock", "equity", "mf", "mutualfund", "fd", "rd", "crypto",
                 "gold", "bonds", "bond", "etf", "ppf", "nps", "realestate", "property", "other"}
_INSURANCE_KINDS = {"life", "term", "health", "medical", "motor", "car", "bike", "home",
                    "travel", "other"}
_FREQ = {"monthly", "quarterly", "yearly", "annual", "annually", "halfyearly"}
_DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
_NUM_RE = re.compile(r"^[₹$€£]?\d[\d,]*(?:\.\d+)?$")


def _fmt(amount: float, currency: str) -> str:
    return f"{currency} {amount:,.2f}"


def _num(tok: str) -> float:
    return float(re.sub(r"[₹$€£,]", "", tok))


def _today() -> date:
    return date.today()


def handle(db: Session, group: Group, member: Member, text: str) -> str:
    parts = text.strip().lstrip("/!").split()
    if not parts:
        return HELP_TEXT
    cmd, args = parts[0].lower(), parts[1:]
    cur = group.currency

    if cmd == "help":
        return HELP_TEXT
    if cmd in ("start", "setup"):
        return onboarding.start(db, member)
    if cmd == "total":
        return _total(db, group, args, cur)
    if cmd == "month":
        return _month(db, group, args, cur)
    if cmd == "split":
        return _split(db, group, cur)
    if cmd == "undo":
        return _undo(db, group, member, cur)
    if cmd in ("refund", "refunded"):
        return _refund(db, group, member, text, cur)
    if cmd == "accounts":
        return _accounts(db, group, cur)
    if cmd == "account":
        return _account(db, group, member, args, cur)
    if cmd == "transfer":
        return _transfer(db, group, member, args, text, cur)
    if cmd in ("paycard", "paybill", "pay"):
        return _paycard(db, group, member, args, text, cur)
    if cmd in ("lend", "lent"):
        return _loan_add(db, group, member, args, text, cur, "lent")
    if cmd in ("borrow", "borrowed"):
        return _loan_add(db, group, member, args, text, cur, "borrowed")
    if cmd == "loan":
        return _loan(db, group, member, args, text, cur)
    if cmd == "loans":
        return _loans(db, group, cur)
    if cmd == "income":
        return _income(db, group, member, args, text, cur)
    if cmd in ("invest", "investment", "investments"):
        return _invest(db, group, member, args, cur)
    if cmd in ("insurance", "insurances"):
        return _insurance(db, group, member, args, cur)
    if cmd in ("due", "premiums"):
        return _due(db, group, cur)
    if cmd in ("budget", "budgets"):
        return _budget(db, group, args, cur)
    if cmd in ("recurring", "recurrings"):
        return _recurring(db, group, member, args, text, cur)
    if cmd in ("upcoming", "reminders"):
        return _upcoming(db, group, cur)
    if cmd in ("networth", "net", "worth"):
        return _networth(db, group, cur)

    return f"Unknown command: /{cmd}. Try /help."


# --- reports -------------------------------------------------------------------

def _total(db, group, args, cur) -> str:
    today = _today()
    start, end = reports.month_bounds(today.year, today.month)
    if args:
        category = args[0]
        amt = reports.total(db, group, category=category, start=start, end=end)
        return f"{category.capitalize()} this month: {_fmt(amt, cur)}"
    amt = reports.total(db, group, start=start, end=end)
    inc = reports.income_total(db, group, start=start, end=end)
    return (f"📊 This month\n• Income: {_fmt(inc, cur)}\n• Expenses: {_fmt(amt, cur)}\n"
            f"• Net: {_fmt(inc - amt, cur)}")


def _month(db, group, args, cur) -> str:
    if not args or args[0].lower() not in reports.MONTHS:
        return "Usage: /month <name>, e.g. /month june"
    m = reports.MONTHS[args[0].lower()]
    year = _today().year
    start, end = reports.month_bounds(year, m)
    rows = reports.by_category(db, group, start=start, end=end)
    if not rows:
        return f"No expenses recorded for {args[0].capitalize()}."
    total_amt = sum(s for _, s in rows)
    lines = [f"📅 *{args[0].capitalize()} {year}* — {_fmt(total_amt, cur)}"]
    lines += [f"• {c}: {_fmt(s, cur)}" for c, s in rows]
    return "\n".join(lines)


def _split(db, group, cur) -> str:
    settlements = reports.settle_up(db, group)
    if not settlements:
        return "Everyone's settled up 🎉 (or no expenses yet)."
    lines = ["💰 *Settle up:*"]
    lines += [f"• {s.debtor} → {s.creditor}: {_fmt(s.amount, cur)}" for s in settlements]
    return "\n".join(lines)


def _undo(db, group, member, cur) -> str:
    removed = crud.delete_last_expense(db, group, member)
    if removed is None:
        return "Nothing to undo — you have no expenses recorded."
    return f"↩️ Removed: {_fmt(float(removed.amount), removed.currency)} · {removed.category}"


def _refund(db, group, member, text, cur) -> str:
    import uuid
    return record_refund(db, group, member, text, cur, f"cmd-refund-{uuid.uuid4()}")


def record_refund(db, group, member, text: str, cur: str, wa_message_id: str) -> str:
    """Shared refund logic used by the /refund command and the 'refund …' keyword path.

    Records a refund (a negative-amount expense) that credits the source account and nets
    against category spend, linking it to the most recent matching expense when possible.
    """
    parsed = parse_refund(text, default_currency=cur)
    if parsed is None:
        return ("Usage: /refund <amount> [#category] [>account] [note]\n"
                "e.g. /refund 500 #food >hdfc returned items")
    account = crud.find_account(db, group, parsed.account_hint) if parsed.account_hint else None
    if account is None:
        account = crud.find_account_in_text(db, group, text, member=member,
                                             skip_amount=parsed.amount)
    # Try to link to the latest matching expense (same category, same payer) for context.
    original = crud.latest_expense(db, group, member=member, category=parsed.category) \
        or crud.latest_expense(db, group, category=parsed.category)
    refund = crud.create_refund(
        db, group=group, member=member, account=account, amount=parsed.amount,
        currency=cur, category=parsed.category, note=parsed.note,
        spent_at=date.today(), raw_message=text, wa_message_id=wa_message_id,
        original=original,
    )
    if refund is None:
        return None  # duplicate delivery
    acct = account or (db.get(crud.Account, refund.account_id) if refund.account_id else None)
    where = f" → {acct.bank_name} ****{acct.last4}" if acct else ""
    link = " (linked to a prior expense)" if refund.original_expense_id else ""
    return f"↩️ Refund {_fmt(abs(float(refund.amount)), cur)} · {refund.category}{where}{link}"


# --- accounts & income ---------------------------------------------------------

def _balance_label(a, cur) -> str:
    """Banks show their cash balance; credit cards show what's owed (negative balance)."""
    if a["kind"] == "credit_card":
        owed = -a["balance"] if a["balance"] < 0 else 0
        return f"owe {_fmt(owed, cur)}" if owed else f"{_fmt(a['balance'], cur)} (in credit)"
    return _fmt(a["balance"], cur)


def _accounts(db, group, cur) -> str:
    rows = reports.accounts_overview(db, group)
    if not rows:
        return "No accounts yet. Send /start, or use /account add HDFC 1234 50000."
    lines = ["🏦 *Accounts*"]
    for a in rows:
        tag = " 💳" if a["kind"] == "credit_card" else ""
        owner = f" ({a['owner']})" if a["owner"] else ""
        lines.append(f"• {a['bank_name']} ****{a['last4']}{tag}{owner}: {_balance_label(a, cur)}")
    return "\n".join(lines)


def _account(db, group, member, args, cur) -> str:
    """/account add <bank> [credit] <last4> [amount]  |  /account balance <bank|last4> <amount>"""
    if not args:
        return ("Usage:\n"
                "• `/account add HDFC 1234 50000` — add a bank account with a balance\n"
                "• `/account add ICICI credit 5678 12000` — add a card with amount owed\n"
                "• `/account balance HDFC 60000` — set an account's current balance\n"
                "• `/account balance ICICI 9000` — set a card's amount owed\n"
                "• `/accounts` — list accounts & balances")
    sub = args[0].lower()
    rest = args[1:]

    if sub == "add":
        kind_words = {"credit": "credit_card", "cc": "credit_card", "card": "credit_card",
                      "cash": "cash", "asset": "asset", "bank": "bank"}
        kind = next((kind_words[t.lower()] for t in rest if t.lower() in kind_words), "bank")
        rest_wo_kind = [t for t in rest if t.lower() not in kind_words]
        # Only bank/credit accounts have a last-4; for cash/asset a 4-digit token is the amount.
        last4 = None
        if kind in ("bank", "credit_card"):
            last4 = next((t for t in rest_wo_kind if re.fullmatch(r"\d{4}", t)), None)
        amounts = [t for t in rest_wo_kind if _NUM_RE.match(t) and t != last4]
        name_tokens = [t for t in rest_wo_kind if not _NUM_RE.match(t)]
        # Cash / assets don't need a last-4.
        if not name_tokens or (not last4 and kind in ("bank", "credit_card")):
            return ("Usage: /account add <name> [credit|cash|asset] [last4] [amount]\n"
                    "e.g. /account add HDFC 1234 50000 · /account add Wallet cash 2000 · "
                    "/account add Gold asset 150000")
        bank = " ".join(name_tokens)
        opening = 0.0
        if amounts:
            v = _num(amounts[0])
            opening = -v if kind == "credit_card" else v
        crud.add_account(db, group, member, bank_name=bank, last4=last4 or "", kind=kind,
                         opening_balance=opening)
        label = "credit card" if kind == "credit_card" else "account"
        extra = ""
        if amounts:
            v = _num(amounts[0])
            extra = f" · owe {_fmt(v, cur)}" if kind == "credit_card" else f" · balance {_fmt(v, cur)}"
        return f"➕ Added {bank} ****{last4} ({label}){extra}"

    if sub in ("balance", "bal", "set"):
        if len(rest) < 2 or not _NUM_RE.match(rest[-1]):
            return "Usage: /account balance <bank or last4> <amount>  e.g. /account balance HDFC 60000"
        token = " ".join(rest[:-1])
        amount = _num(rest[-1])
        acc = crud.find_account(db, group, token)
        if acc is None:
            return f"No account matching '{token}'. See /accounts."
        target = -amount if acc.kind == "credit_card" else amount
        crud.set_account_balance(db, acc, target)
        if acc.kind == "credit_card":
            return f"🟰 {acc.bank_name} ****{acc.last4}: now owe {_fmt(amount, cur)}"
        return f"🟰 {acc.bank_name} ****{acc.last4}: balance set to {_fmt(amount, cur)}"

    return "Usage: /account add … | /account balance … | /accounts"


# --- transfers & loans --------------------------------------------------------

def _acct_from_text(db, group, text):
    m = re.search(r">(\w+)", text)
    return crud.find_account(db, group, m.group(1)) if m else None


def _transfer(db, group, member, args, text, cur) -> str:
    # /transfer <amount> <from> <to>   (filler words from/to/-> are ignored)
    toks = [t for t in args if t.lower() not in ("from", "to", "->", "→")]
    nums = [t for t in toks if _NUM_RE.match(t)]
    names = [t for t in toks if not _NUM_RE.match(t)]
    if not nums or len(names) < 2:
        return "Usage: /transfer <amount> <from account> <to account>  e.g. /transfer 5000 hdfc icici"
    amount = _num(nums[0])
    src = crud.find_account(db, group, names[0])
    dst = crud.find_account(db, group, names[1])
    if src is None or dst is None:
        miss = names[0] if src is None else names[1]
        return f"No account matching '{miss}'. See /accounts."
    if src.id == dst.id:
        return "Pick two different accounts to transfer between."
    crud.create_transfer(db, group=group, member=member, from_account=src, to_account=dst,
                         amount=amount, currency=cur, on=_today(),
                         wa_message_id=f"cmd-xfer-{datetime.utcnow().timestamp()}")
    return (f"🔁 Transferred {_fmt(amount, cur)}: {src.bank_name} ****{src.last4} → "
            f"{dst.bank_name} ****{dst.last4}")


def _cards_matching(db, group, token):
    """All accounts whose name or last-4 matches `token` (used to pick the right card)."""
    from sqlalchemy import or_ as _or
    return db.scalars(select(crud.Account).where(
        crud.Account.group_id == group.id,
        _or(func.lower(crud.Account.bank_name) == token.lower(), crud.Account.last4 == token),
    ).order_by(crud.Account.id)).all()


def _paycard(db, group, member, args, text, cur) -> str:
    """Pay a credit-card due: reduce the card's owed and deduct from a source account.

    Usage: /paycard <card> <amount> [from <source>]
      e.g. /paycard hsbc 2000 from dcb   ·   /paycard 6511 5000 from hdfc 0611
    Recorded as a transfer source → card, so the card's owed drops and the source falls.
    """
    toks = [t.lstrip(">") for t in args if t.lower() not in ("from", "to", "->", "→")]
    # A token is an "account token" if it matches some account by name or last-4. The amount
    # is then the numeric token that is NOT an account's last-4 (so "/paycard 6511 500 from
    # hdfc 0611" reads 500 as the amount, not the card/source last-4 digits).
    acct_toks = [t for t in toks if _cards_matching(db, group, t)]
    amount_toks = [t for t in toks if _NUM_RE.match(t) and t not in acct_toks]
    if not amount_toks or not acct_toks:
        return ("Usage: /paycard <card> <amount> [from <source>]\n"
                "e.g. /paycard hsbc 2000 from dcb")
    amount = _num(amount_toks[0])
    if amount <= 0:
        return "Enter an amount greater than 0. e.g. /paycard hsbc 2000 from dcb"

    # Pick the card: the first account token that resolves to a credit card.
    card = None
    card_tok = None
    for n in acct_toks:
        cc = [a for a in _cards_matching(db, group, n) if a.kind == "credit_card"]
        if cc:
            card, card_tok = cc[0], n
            break
    if card is None:
        return ("Which card? Name it (or its last-4): /paycard <card> <amount> from <source>\n"
                "See /accounts for your cards.")

    # Pick the source: a non-card account named by a different token.
    source = None
    for n in acct_toks:
        if n == card_tok:
            continue
        banks = [a for a in _cards_matching(db, group, n) if a.kind != "credit_card"]
        if banks:
            source = banks[0]
            break
    if source is None:
        return (f"Pay {card.bank_name} ****{card.last4} from which account? "
                f"Add it: /paycard {card_tok} {amount_toks[0]} from <bank>")
    if source.id == card.id:
        return "The source and the card can't be the same account."

    crud.create_transfer(db, group=group, member=member, from_account=source, to_account=card,
                         amount=amount, currency=cur, on=_today(),
                         note=f"card payment: {card.bank_name} ****{card.last4}",
                         wa_message_id=f"cmd-paycard-{datetime.utcnow().timestamp()}")
    new_owed = -reports.account_balance(db, card)
    new_owed = max(new_owed, 0)
    return (f"💳 Paid {_fmt(amount, cur)} to {card.bank_name} ****{card.last4} "
            f"from {source.bank_name} ****{source.last4}\n"
            f"   Remaining owed: {_fmt(new_owed, cur)}")


def _loan_add(db, group, member, args, text, cur, direction) -> str:
    if not args:
        verb = "lend" if direction == "lent" else "borrow"
        who = "friend" if direction == "lent" else "lender/bank"
        return f"Usage: /{verb} <amount> <{who}> [>account]  e.g. /{verb} 5000 Raju >hdfc"
    acct = _acct_from_text(db, group, text)
    toks = [t for t in args if not t.startswith(">")]
    nums = [t for t in toks if _NUM_RE.match(t)]
    names = [t for t in toks if not _NUM_RE.match(t)]
    if not nums or not names:
        return "I need an amount and a name, e.g. /lend 5000 Raju >hdfc"
    amount = _num(nums[0])
    counterparty = " ".join(names)
    crud.add_loan(db, group, member, direction=direction, counterparty=counterparty,
                  principal=amount, on=_today(), account=acct)
    where = f" from {acct.bank_name} ****{acct.last4}" if (acct and direction == "lent") else (
        f" into {acct.bank_name} ****{acct.last4}" if acct else "")
    if direction == "lent":
        return f"🤝 Lent {_fmt(amount, cur)} to *{counterparty}*{where}. They owe you {_fmt(amount, cur)}."
    return f"🏦 Borrowed {_fmt(amount, cur)} from *{counterparty}*{where}. You owe {_fmt(amount, cur)}."


def _loan(db, group, member, args, text, cur) -> str:
    if not args or args[0].lower() in ("list", "all"):
        return _loans(db, group, cur)
    sub = args[0].lower()
    rest = [t for t in args[1:] if not t.startswith(">")]
    if sub in ("pay", "collect", "repaid", "repay"):
        nums = [t for t in rest if _NUM_RE.match(t)]
        names = [t for t in rest if not _NUM_RE.match(t)]
        if not nums or not names:
            return ("Usage: /loan pay <lender> <amount> [>account]  (you repay a loan)\n"
                    "       /loan collect <friend> <amount> [>account]  (friend repays you)")
        amount = _num(nums[0])
        counterparty = " ".join(names)
        direction = "borrowed" if sub in ("pay", "repay") else "lent"
        loan = crud.find_loan(db, group, counterparty, direction=direction)
        if loan is None:
            kind = "a loan you owe" if direction == "borrowed" else "money you lent"
            return f"No record of {kind} with '{counterparty}'. See /loans."
        acct = _acct_from_text(db, group, text)
        crud.add_loan_payment(db, loan, amount=amount, on=_today(), account=acct)
        left = reports.loan_outstanding(db, loan)
        if direction == "borrowed":
            return f"✅ Paid {_fmt(amount, cur)} to {counterparty}. You still owe {_fmt(left, cur)}."
        return f"✅ {counterparty} repaid {_fmt(amount, cur)}. They still owe you {_fmt(left, cur)}."
    return ("Usage:\n• `/lend <amount> <friend> [>account]`\n• `/borrow <amount> <lender> [>account]`\n"
            "• `/loan pay <lender> <amount> [>account]`\n• `/loan collect <friend> <amount> [>account]`\n"
            "• `/loans`")


def _loans(db, group, cur) -> str:
    rows = reports.loans_overview(db, group)
    active = [r for r in rows if r["outstanding"] > 0.005]
    if not active:
        return "No outstanding loans. Add one: /lend 5000 Raju  or  /borrow 100000 SBI"
    owe = [r for r in active if r["direction"] == "borrowed"]
    owed = [r for r in active if r["direction"] == "lent"]
    lines = ["💳 *Loans*"]
    if owe:
        lines.append("*You owe:*")
        lines += [f"• {r['counterparty']}: {_fmt(r['outstanding'], cur)}" for r in owe]
    if owed:
        lines.append("*Owed to you:*")
        lines += [f"• {r['counterparty']}: {_fmt(r['outstanding'], cur)}" for r in owed]
    return "\n".join(lines)


def _income(db, group, member, args, text, cur) -> str:
    if not args:
        return "Usage: /income <amount> [source] [>account]  e.g. /income 50000 salary >hdfc"
    # account hint
    acct = None
    m = re.search(r">(\w+)", text)
    if m:
        acct = crud.find_account(db, group, m.group(1))
    tokens = [t for t in args if not t.startswith(">")]
    amount = None
    source_words = []
    for t in tokens:
        if amount is None and _NUM_RE.match(t):
            amount = _num(t)  # first number is the amount
        elif not _NUM_RE.match(t):
            source_words.append(t)
    if amount is None:
        return "I couldn't find an amount. e.g. /income 50000 salary >hdfc"
    # No '>account'? Credit an account named in plain text ("/income 50000 salary to sbi 8656").
    if acct is None:
        acct = crud.find_account_in_text(db, group, text, member=member, skip_amount=amount)
    source = " ".join(source_words).strip() or "Income"
    inc = crud.create_income(
        db, group=group, member=member, account=acct, amount=amount, currency=cur,
        source=source.capitalize(), note=source, received_on=_today(),
        raw_message=text, wa_message_id=f"cmd-income-{datetime.utcnow().timestamp()}",
    )
    where = f" → {acct.bank_name} ****{acct.last4}" if acct else ""
    return f"💚 Income logged: {_fmt(amount, cur)} · {inc.source}{where}"


# --- investments ---------------------------------------------------------------

def _invest(db, group, member, args, cur) -> str:
    if not args:
        rows = reports.investments_overview(db, group)
        if not rows:
            return "No investments yet. Add one: /invest add mf 100000 Axis Bluechip"
        return _render_investments(rows, group, cur)

    sub = args[0].lower()

    if sub in ("list", "all"):
        return _render_investments(reports.investments_overview(db, group), group, cur)

    if sub == "update":
        rest = args[1:]
        if len(rest) < 2 or not _NUM_RE.match(rest[-1]):
            return "Usage: /invest update <name> <new value>  e.g. /invest update Axis Bluechip 125000"
        value = _num(rest[-1])
        name = " ".join(rest[:-1])
        inv = crud.find_investment(db, group, name)
        if inv is None:
            return f"No investment named '{name}'. See /investments."
        crud.update_investment_value(db, inv, value, _today())
        gain = value - float(inv.invested_amount)
        sign = "▲" if gain >= 0 else "▼"
        return f"🔄 {inv.name} updated to {_fmt(value, cur)}  {sign} {_fmt(abs(gain), cur)}"

    if sub == "add":
        rest = args[1:]
        kind = "other"
        if rest and rest[0].lower() in _INVEST_KINDS:
            kind = rest[0].lower()
            rest = rest[1:]
        nums = [t for t in rest if _NUM_RE.match(t)]
        if not nums:
            return "Usage: /invest add <kind> <amount> <name>  e.g. /invest add mf 100000 Axis Bluechip"
        invested = _num(nums[0])
        name_tokens = [t for t in rest if not _NUM_RE.match(t)]
        name = " ".join(name_tokens).strip() or kind.capitalize()
        inv = crud.add_investment(db, group, member, name=name, kind=kind,
                                  invested=invested, current=invested, as_of=_today())
        return (f"📈 Added investment: *{inv.name}* ({kind}) — invested {_fmt(invested, cur)}.\n"
                f"Update its value anytime: /invest update {name} <value>")

    return "Usage: /invest add … | /invest update … | /investments"


def _render_investments(rows, group, cur) -> str:
    if not rows:
        return "No investments yet."
    total_cur = sum(r["current_value"] for r in rows)
    total_inv = sum(r["invested"] for r in rows)
    gain = total_cur - total_inv
    sign = "▲" if gain >= 0 else "▼"
    lines = [f"📈 *Investments* — value {_fmt(total_cur, cur)}  {sign} {_fmt(abs(gain), cur)}"]
    for r in rows:
        g = r["gain"]
        gs = "▲" if g >= 0 else "▼"
        own = f" ({r['owner']})" if r["owner"] else ""
        lines.append(f"• {r['name']} [{r['kind']}]{own}: {_fmt(r['current_value'], cur)} "
                     f"{gs}{_fmt(abs(g), cur)}")
    return "\n".join(lines)


# --- insurance -----------------------------------------------------------------

def _insurance(db, group, member, args, cur) -> str:
    if not args or args[0].lower() in ("list", "all"):
        return _due(db, group, cur)

    if args[0].lower() == "add":
        rest = args[1:]
        kind = "other"
        if rest and rest[0].lower() in _INSURANCE_KINDS:
            kind = rest[0].lower()
            rest = rest[1:]
        joined = " ".join(rest)
        due = None
        dm = _DATE_RE.search(joined)
        if dm:
            due = datetime.strptime(dm.group(1), "%Y-%m-%d").date()
            rest = [t for t in rest if t != dm.group(1)]
        freq = "yearly"
        for f in list(rest):
            if f.lower() in _FREQ:
                freq = "yearly" if f.lower() in ("annual", "annually") else f.lower()
                rest = [t for t in rest if t != f]
        nums = [t for t in rest if _NUM_RE.match(t)]
        if not nums:
            return ("Usage: /insurance add <kind> <premium> <YYYY-MM-DD> <name>\n"
                    "e.g. /insurance add health 24000 2026-09-15 HDFC Ergo Family")
        premium = _num(nums[0])
        name_tokens = [t for t in rest if not _NUM_RE.match(t)]
        name = " ".join(name_tokens).strip() or kind.capitalize()
        ins = crud.add_insurance(db, group, member, name=name, kind=kind, provider=None,
                                 premium=premium, frequency=freq, due_date=due)
        due_s = f", due {ins.due_date.isoformat()}" if ins.due_date else ""
        return f"🛡️ Added insurance: *{ins.name}* ({kind}) — {_fmt(premium, cur)}/{freq}{due_s}"

    return _due(db, group, cur)


def _due(db, group, cur) -> str:
    rows = reports.upcoming_premiums(db, group)
    if not rows:
        return "No insurance policies yet. Add one: /insurance add health 24000 2026-09-15 HDFC Ergo"
    lines = ["🛡️ *Insurance & premiums*"]
    for r in rows:
        own = f" ({r['owner']})" if r["owner"] else ""
        if r["due_date"]:
            d = r["days_until_due"]
            when = "⚠️ overdue" if d is not None and d < 0 else (
                f"due in {d}d" if d is not None else f"due {r['due_date']}")
            due_s = f" — {r['due_date']} ({when})"
        else:
            due_s = " — no due date set"
        lines.append(f"• {r['name']} [{r['kind']}]{own}: {_fmt(r['premium'], cur)}/{r['frequency']}{due_s}")
    return "\n".join(lines)


# --- budgets ------------------------------------------------------------------

def _budget(db, group, args, cur) -> str:
    if not args or args[0].lower() in ("list", "status"):
        rows = reports.budget_status(db, group)
        if not rows:
            return "No budgets set. Try: /budget set Food 8000"
        lines = ["📊 *Budgets (this month)*"]
        for r in rows:
            bar = "🔴" if r["spent"] > r["limit"] else ("🟠" if r["pct"] >= 80 else "🟢")
            lines.append(f"{bar} {r['category']}: {_fmt(r['spent'], cur)} / {_fmt(r['limit'], cur)} "
                         f"({r['pct']:.0f}%)")
        return "\n".join(lines)
    sub = args[0].lower()
    if sub in ("set", "add"):
        rest = args[1:]
        nums = [t for t in rest if _NUM_RE.match(t)]
        names = [t for t in rest if not _NUM_RE.match(t)]
        if not nums or not names:
            return "Usage: /budget set <category> <monthly amount>  e.g. /budget set Food 8000"
        cat = " ".join(names).capitalize()
        crud.set_budget(db, group, cat, _num(nums[0]))
        return f"📊 Budget set: {cat} = {_fmt(_num(nums[0]), cur)}/month"
    if sub in ("remove", "delete", "rm"):
        cat = " ".join(args[1:]).strip()
        return (f"🗑️ Removed budget for {cat}." if crud.delete_budget(db, group, cat)
                else f"No budget for '{cat}'.")
    return "Usage: /budget · /budget set <category> <amount> · /budget remove <category>"


# --- recurring ----------------------------------------------------------------

def _recurring(db, group, member, args, text, cur) -> str:
    if not args or args[0].lower() in ("list", "all"):
        return _upcoming(db, group, cur)
    sub = args[0].lower()
    if sub == "add":
        rest = args[1:]
        flow = "income" if any(t.lower() in ("income", "in", "salary") for t in rest) else "expense"
        rest = [t for t in rest if t.lower() not in ("expense", "income", "in", "out")]
        acct = _acct_from_text(db, group, text)
        rest = [t for t in rest if not t.startswith(">")]
        tag = next((t[1:] for t in rest if t.startswith("#")), None)
        rest = [t for t in rest if not t.startswith("#")]
        nums = [t for t in rest if _NUM_RE.match(t)]
        names = [t for t in rest if not _NUM_RE.match(t)]
        if len(nums) < 2 or not names:
            return ("Usage: /recurring add <expense|income> <amount> <day 1-31> <label> [#category] [>account]\n"
                    "e.g. /recurring add expense 15000 1 Rent  ·  /recurring add income 50000 1 Salary")
        amount = _num(nums[0])
        day = int(float(nums[1]))
        label = " ".join(names)
        category = (tag.capitalize() if tag else label.capitalize()) if flow == "expense" else None
        r = crud.add_recurring(db, group, member, flow=flow, label=label, amount=amount,
                               day_of_month=day, category=category, account=acct)
        return (f"🔁 Recurring {flow} added: *{label}* {_fmt(amount, cur)} on day {r.day_of_month} "
                f"of each month. I'll remind the group when it's due.")
    if sub in ("remove", "delete", "rm"):
        if not args[1:] or not args[1].isdigit():
            return "Usage: /recurring remove <id>  (see ids in /recurring)"
        ok = crud.delete_recurring(db, group, int(args[1]))
        return "🗑️ Removed." if ok else "No such recurring item."
    return "Usage: /recurring add … | /recurring remove <id> | /recurring"


def _upcoming(db, group, cur) -> str:
    rows = reports.recurring_overview(db, group)
    rem = reports.reminders(db, group, within_days=3)
    lines = []
    if rows:
        lines.append("🔁 *Recurring items*")
        for r in rows:
            tag = "💸" if r["flow"] == "expense" else "💚"
            lines.append(f"{tag} [{r['id']}] {r['label']}: {_fmt(r['amount'], cur)} on day "
                         f"{r['day_of_month']} — next {r['next_due']} (in {r['days_until']}d)")
    if rem:
        lines.append("\n⏰ *Due soon:*")
        lines += rem
    return "\n".join(lines) if lines else "No recurring items. Add: /recurring add expense 15000 1 Rent"


# --- net worth -----------------------------------------------------------------

def _networth(db, group, cur) -> str:
    nw = reports.net_worth(db, group)
    return (
        "🏠 *Household snapshot*\n"
        f"• Cash in accounts: {_fmt(nw['cash_in_accounts'], cur)}\n"
        f"• Investments value: {_fmt(nw['investments_value'], cur)}\n"
        f"• *Net worth: {_fmt(nw['net_worth'], cur)}*\n"
        f"— total income: {_fmt(nw['total_income'], cur)} · "
        f"total expenses: {_fmt(nw['total_expenses'], cur)}"
    )
