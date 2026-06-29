"""Unit tests for the expense parser. Run: pytest -q"""
from app.parser import is_command, parse_expense


def test_simple_positional():
    p = parse_expense("Lunch 250 food")
    assert p is not None
    assert p.amount == 250
    assert p.category == "Food"


def test_keyword_inferred_category():
    p = parse_expense("coffee 80")
    assert p.amount == 80
    assert p.category == "Food"


def test_hashtag_category():
    p = parse_expense("Uber 120 #transport")
    assert p.amount == 120
    assert p.category == "Transport"


def test_currency_symbol_and_thousands():
    p = parse_expense("₹1,500 groceries")
    assert p.amount == 1500
    assert p.currency == "INR"
    assert p.category == "Groceries"


def test_payer_hint():
    p = parse_expense("250 dinner @ravi")
    assert p.payer_hint == "ravi"
    assert p.amount == 250


def test_account_hint():
    p = parse_expense("Lunch 250 #food >hdfc")
    assert p.account_hint == "hdfc"
    assert p.amount == 250
    assert p.category == "Food"


def test_account_hint_by_last4():
    p = parse_expense("groceries 1500 >1234")
    assert p.account_hint == "1234"
    assert p.amount == 1500


def test_decimal_and_dollar():
    p = parse_expense("$12.50 coffee")
    assert p.amount == 12.5
    assert p.currency == "USD"


def test_default_currency_applied():
    p = parse_expense("rent 9000", default_currency="INR")
    assert p.currency == "INR"
    assert p.category == "Housing"
    assert p.amount == 9000  # 4-digit, no comma -> must not parse as 900


def test_large_amount_no_comma():
    assert parse_expense("salary 125000").amount == 125000
    assert parse_expense("car 1234567").amount == 1234567


def test_no_amount_returns_none():
    assert parse_expense("hey are we still meeting tonight?") is None


def test_empty_returns_none():
    assert parse_expense("") is None
    assert parse_expense("   ") is None


def test_unknown_tag_titlecased():
    p = parse_expense("500 gift #birthday")
    assert p.category == "Birthday"


def test_commands_are_not_expenses():
    assert is_command("/total")
    assert parse_expense("/total food") is None


def test_zero_amount_rejected():
    assert parse_expense("free 0 food") is None
