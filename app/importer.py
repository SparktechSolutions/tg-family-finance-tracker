"""Backfill from an exported WhatsApp chat (.txt).

WhatsApp has no API to fetch past group messages, so if the server was OFFLINE for longer
than Meta's webhook-retry window, this is how you catch up: in WhatsApp, open the group →
Export chat → Without media, and feed the .txt here. Each expense/refund line is replayed
through the normal parser.

Re-imports are safe: each line gets a **deterministic** id
(`import-<sha1(timestamp|sender|text)>`), so importing an overlapping export — or the same
file twice — never double-counts (dedupe is the same `wa_message_id` uniqueness used for
live webhooks).

CLI:
    python -m app.importer path/to/chat.txt --group <wa_group_id> [--currency INR]
"""
from __future__ import annotations

import argparse
import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.orm import Session

from . import commands, crud
from .db import SessionLocal, init_db
from .parser import is_command, is_refund, parse_expense

# Matches common WhatsApp export line formats, e.g.:
#   "12/06/2026, 21:34 - Ravi: Lunch 250 #food"
#   "[12/06/2026, 9:34:01 PM] Ravi: uber 120"
_LINE_RE = re.compile(
    r"^\[?(?P<date>\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}),?\s+"
    r"(?P<time>\d{1,2}:\d{2}(?::\d{2})?(?:\s?[APap][Mm])?)\]?\s*[-\s]\s*"
    r"(?P<sender>[^:]{1,60}?):\s(?P<text>.*)$"
)


@dataclass
class ImportResult:
    expenses: int = 0
    refunds: int = 0
    duplicates: int = 0
    skipped: int = 0
    lines: int = 0


def _mid(ts: str, sender: str, text: str) -> str:
    h = hashlib.sha1(f"{ts}|{sender}|{text}".encode()).hexdigest()[:24]
    return f"import-{h}"


def _parse_date(d: str) -> date:
    for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d/%m/%y", "%m/%d/%y", "%d.%m.%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(d, fmt).date()
        except ValueError:
            continue
    return date.today()


def import_chat_text(text: str, *, wa_group_id: str, currency: str = "INR",
                     db: Session | None = None) -> ImportResult:
    """Replay an exported chat. Multi-line messages are joined to their header line."""
    own = db is None
    db = db or SessionLocal()
    res = ImportResult()
    try:
        group = crud.get_or_create_group(db, wa_group_id)
        if currency:
            group.currency = group.currency or currency

        # Group raw lines into messages (continuation lines have no header).
        records: list[tuple[str, str, str]] = []  # (ts, sender, text)
        for raw in text.splitlines():
            m = _LINE_RE.match(raw)
            if m:
                ts = f"{m.group('date')} {m.group('time')}"
                records.append((ts, m.group("sender").strip(), m.group("text")))
            elif records:
                ts, sender, prev = records[-1]
                records[-1] = (ts, sender, prev + "\n" + raw)

        for ts, sender, body in records:
            res.lines += 1
            spent = _parse_date(ts.split()[0])
            member = crud.get_or_create_member(
                db, group, wa_user_id=f"import:{sender}", display_name=sender)
            wa_id = _mid(ts, sender, body)

            if crud.expense_exists(db, wa_id):
                res.duplicates += 1
                continue

            if is_command(body):
                res.skipped += 1            # don't replay commands from history
                continue

            if is_refund(body):
                reply = commands.record_refund(db, group, member, body, group.currency, wa_id)
                if reply:
                    res.refunds += 1
                else:
                    res.duplicates += 1
                continue

            parsed = parse_expense(body, default_currency=group.currency)
            if parsed is None:
                res.skipped += 1            # chatter, no amount
                continue
            account = crud.find_account(db, group, parsed.account_hint) if parsed.account_hint else None
            payer = member
            if parsed.payer_hint:
                payer = crud.find_member_by_name(db, group, parsed.payer_hint) or member
            exp = crud.create_expense(
                db, group=group, member=payer, account=account, amount=parsed.amount,
                currency=parsed.currency or group.currency, category=parsed.category,
                note=parsed.note, spent_at=spent, raw_message=body, wa_message_id=wa_id)
            res.expenses += 1 if exp else 0
            res.duplicates += 0 if exp else 1

        db.commit() if own else db.flush()
        return res
    finally:
        if own:
            db.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="Import a WhatsApp chat export (.txt)")
    ap.add_argument("file")
    ap.add_argument("--group", required=True, help="wa_group_id to import into")
    ap.add_argument("--currency", default="INR")
    args = ap.parse_args()
    init_db()
    with open(args.file, encoding="utf-8") as fh:
        res = import_chat_text(fh.read(), wa_group_id=args.group, currency=args.currency)
    print(f"Imported: {res.expenses} expenses, {res.refunds} refunds | "
          f"{res.duplicates} duplicates skipped, {res.skipped} non-expense lines, "
          f"{res.lines} messages scanned.")


if __name__ == "__main__":
    main()
