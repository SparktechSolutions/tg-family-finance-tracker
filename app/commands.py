"""Bot command handlers. Each returns the text the bot should reply with.

Pure functions of (db, group, member, text) -> str, so they're unit-testable.
Structured commands (income/invest/insurance) use forgiving token parsing rather than
strict positional args, since real family members won't type perfect syntax.
"""
from __future__ import annotations

import re
from datetime import date, datetime

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
    "• `/income <amount> [source] [>account]` — e.g. `/income 50000 salary >hdfc`\n\n"
    "*Investments:*\n"
    "• `/invest add <kind> <amount> <name>` — e.g. `/invest add mf 100000 Axis Bluechip`\n"
    "• `/invest update <name> <value>` — passive value update\n"
    "• `/investments` — list holdings\n\n"
    "*Insurance:*\n"
    "• `/insurance add <kind> <premium> <YYYY-MM-DD> <name>`\n"
    "• `/due` — upcoming premiums\n\n"
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
    if cmd == "income":
        return _income(db, group, member, args, text, cur)
    if cmd in ("invest", "investment", "investments"):
        return _invest(db, group, member, args, cur)
    if cmd in ("insurance", "insurances"):
        return _insurance(db, group, member, args, cur)
    if cmd in ("due", "premiums"):
        return _due(db, group, cur)
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

def _accounts(db, group, cur) -> str:
    rows = reports.accounts_overview(db, group)
    if not rows:
        return "No accounts yet. Send /start to add yours."
    lines = ["🏦 *Accounts*"]
    for a in rows:
        tag = " 💳" if a["kind"] == "credit_card" else ""
        owner = f" ({a['owner']})" if a["owner"] else ""
        lines.append(f"• {a['bank_name']} ****{a['last4']}{tag}{owner}: {_fmt(a['balance'], cur)}")
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
