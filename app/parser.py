"""Parse a raw WhatsApp message into a structured expense.

This is intentionally dependency-free and fully unit-testable (see tests/test_parser.py).
Claude Code: this is the highest-leverage module to improve. Add categories, currencies,
date overrides ("yesterday", "12 Jun"), and split syntax here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# keyword -> category. Extend freely (later: move to the `category` DB table per group).
CATEGORY_KEYWORDS: dict[str, str] = {
    # Dining out
    "lunch": "Food", "dinner": "Food", "breakfast": "Food", "coffee": "Food",
    "tea": "Food", "snacks": "Food", "restaurant": "Food", "food": "Food",
    "swiggy": "Food", "zomato": "Food", "takeout": "Food",
    # Groceries (distinct from dining)
    "groceries": "Groceries", "grocery": "Groceries", "supermarket": "Groceries",
    "vegetables": "Groceries", "milk": "Groceries", "kirana": "Groceries",
    # Transport
    "uber": "Transport", "ola": "Transport", "cab": "Transport", "taxi": "Transport",
    "bus": "Transport", "train": "Transport", "metro": "Transport", "auto": "Transport",
    "fuel": "Transport", "petrol": "Transport", "diesel": "Transport", "parking": "Transport",
    "toll": "Transport", "transport": "Transport",
    # Housing
    "rent": "Housing", "maintenance": "Housing", "repair": "Housing", "furniture": "Housing",
    # Utilities / Bills
    "electricity": "Utilities", "water": "Utilities", "gas": "Utilities", "internet": "Utilities",
    "wifi": "Utilities", "broadband": "Utilities", "mobile": "Utilities", "recharge": "Utilities",
    "dth": "Utilities", "bill": "Bills",
    # Health
    "doctor": "Health", "medicine": "Health", "medicines": "Health", "pharmacy": "Health",
    "hospital": "Health", "clinic": "Health", "dentist": "Health", "medical": "Health",
    "checkup": "Health",
    # Education
    "school": "Education", "tuition": "Education", "schoolfees": "Education", "books": "Education",
    "course": "Education", "college": "Education", "stationery": "Education", "exam": "Education",
    # Fees & charges (bank fees, transaction fees, late fees, fines, commissions)
    "fee": "Fees", "fees": "Fees", "charge": "Fees", "charges": "Fees", "commission": "Fees",
    "penalty": "Fees", "fine": "Fees", "latefee": "Fees", "convenience": "Fees",
    # Childcare / Pets
    "daycare": "Childcare", "diapers": "Childcare", "toys": "Childcare", "babysitter": "Childcare",
    "pet": "Pets", "vet": "Pets",
    # Entertainment / Subscriptions
    "movie": "Entertainment", "movies": "Entertainment", "concert": "Entertainment",
    "game": "Entertainment", "netflix": "Subscriptions", "spotify": "Subscriptions",
    "prime": "Subscriptions", "hotstar": "Subscriptions", "subscription": "Subscriptions",
    # Shopping / Personal care / Fitness
    "shopping": "Shopping", "clothes": "Shopping", "amazon": "Shopping", "flipkart": "Shopping",
    "salon": "Personal Care", "haircut": "Personal Care", "cosmetics": "Personal Care",
    "gym": "Fitness", "fitness": "Fitness", "yoga": "Fitness",
    # Travel
    "flight": "Travel", "hotel": "Travel", "trip": "Travel", "vacation": "Travel",
    "holiday": "Travel", "travel": "Travel",
    # Gifts / Donations / Taxes / Domestic help
    "gift": "Gifts", "gifts": "Gifts", "donation": "Donations", "charity": "Donations",
    "tax": "Taxes", "taxes": "Taxes", "gst": "Taxes",
    "maid": "Domestic Help", "cook": "Domestic Help", "driver": "Domestic Help",
}

# amount: optional currency symbol, digits with optional thousands sep + decimals.
# First alternative requires >=1 comma group (e.g. 1,500) so a plain "1500" falls through
# to the second alternative and matches in full (not just its first 3 digits).
_AMOUNT_RE = re.compile(r"(?:[₹$€£]\s?)?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)")
_TAG_RE = re.compile(r"#(\w+)")
_PAYER_RE = re.compile(r"@(\w+)")
# '>hdfc' or '>1234' names the source account to debit.
_ACCOUNT_RE = re.compile(r">(\w+)")
_CURRENCY_RE = re.compile(r"[₹$€£]")
_SYMBOL_TO_CODE = {"₹": "INR", "$": "USD", "€": "EUR", "£": "GBP"}

# Messages starting with these are commands, not expenses.
COMMAND_PREFIXES = ("/", "!")

# A plain message starting with one of these words is treated as a refund (money back).
_REFUND_RE = re.compile(r"^\s*(?:/)?refund(?:ed)?\b[:\s]*", re.IGNORECASE)
# A '!personal' / '!mine' / '!solo' marker means this expense is NOT shared (excluded
# from settle-up — only the payer bears it).
_PERSONAL_RE = re.compile(r"(?:^|\s)!(?:personal|mine|solo|own)\b", re.IGNORECASE)


@dataclass
class ParsedExpense:
    amount: float
    currency: str | None
    category: str
    note: str
    payer_hint: str | None    # from @name; None means "the sender"
    account_hint: str | None  # from >account; None means "no account specified"
    shared: bool = True       # False when marked !personal — excluded from settle-up


def is_command(text: str) -> bool:
    return text.strip().startswith(COMMAND_PREFIXES)


def is_refund(text: str) -> bool:
    """True for plain messages like 'refund 500 #food' (not the /refund command)."""
    return bool(_REFUND_RE.match(text or ""))


def parse_refund(text: str, default_currency: str = "INR") -> ParsedExpense | None:
    """Parse a refund message ('refund 500 #food >hdfc shoes' or '/refund 500 …').

    Strips the leading refund word, then reuses expense parsing for
    amount/category/account/note. Returns a ParsedExpense (positive amount) or None.
    """
    if not text:
        return None
    remainder = _REFUND_RE.sub("", text, count=1)
    return parse_expense(remainder, default_currency=default_currency)


def _infer_category(text: str, tag: str | None) -> str:
    if tag:
        # Normalize a known keyword tag, else Title-case the tag itself.
        return CATEGORY_KEYWORDS.get(tag.lower(), tag.capitalize())
    lowered = text.lower()
    for kw, cat in CATEGORY_KEYWORDS.items():
        if re.search(rf"\b{re.escape(kw)}\b", lowered):
            return cat
    return "Uncategorized"


def parse_expense(text: str, default_currency: str = "INR") -> ParsedExpense | None:
    """Return a ParsedExpense, or None if the message has no detectable amount.

    Examples that parse:
        "Lunch 250 food"          -> 250, Food
        "Uber 120 #transport"     -> 120, Transport
        "coffee 80"               -> 80,  Food (keyword inferred)
        "₹1,500 groceries @ravi"  -> 1500, Food, payer=ravi, currency=INR
    """
    if not text or not text.strip():
        return None
    if is_command(text):
        return None

    tag_match = _TAG_RE.search(text)
    payer_match = _PAYER_RE.search(text)
    account_match = _ACCOUNT_RE.search(text)
    tag = tag_match.group(1) if tag_match else None
    payer = payer_match.group(1) if payer_match else None
    account = account_match.group(1) if account_match else None

    shared = not bool(_PERSONAL_RE.search(text))

    # Strip special tokens before hunting for the amount so their digits don't confuse it.
    cleaned = _TAG_RE.sub("", text)
    cleaned = _PAYER_RE.sub("", cleaned)
    cleaned = _ACCOUNT_RE.sub("", cleaned)
    cleaned = _PERSONAL_RE.sub(" ", cleaned)

    amount_match = _AMOUNT_RE.search(cleaned)
    if not amount_match:
        return None
    amount = float(amount_match.group(1).replace(",", ""))
    if amount <= 0:
        return None

    sym_match = _CURRENCY_RE.search(text)
    currency = _SYMBOL_TO_CODE.get(sym_match.group(0)) if sym_match else default_currency

    category = _infer_category(text, tag)

    # Note = the message with amount + tags + payer removed, tidied up.
    note = _AMOUNT_RE.sub("", cleaned, count=1)
    note = _CURRENCY_RE.sub("", note).strip(" -.,")
    note = re.sub(r"\s+", " ", note)

    return ParsedExpense(
        amount=amount,
        currency=currency,
        category=category,
        note=note or category,
        payer_hint=payer,
        account_hint=account,
        shared=shared,
    )
