"""Natural-language source-account matching.

A message can name its source account in plain English ("... hsbc card", "... from sbi
8656") without the `>account` syntax. The named account must be debited (bank balance
down) or charged (credit-card owed up), exactly as `>account` would.
"""
from datetime import date

from app import crud, ingest, reports


def _group(db):
    g = crud.get_or_create_group(db, "g1")
    m = crud.get_or_create_member(db, g, "u1", "Anita")
    return g, m


def test_last4_in_plain_text_resolves(db):
    g, m = _group(db)
    crud.add_account(db, g, m, bank_name="HDFC", last4="0611", opening_balance=1000)
    sbi = crud.add_account(db, g, m, bank_name="SBI", last4="8656", opening_balance=5000)
    acc = crud.find_account_in_text(db, g, "lunch 250 from sbi 8656", member=m, skip_amount=250)
    assert acc is not None and acc.id == sbi.id


def test_card_hint_prefers_credit_card(db):
    g, m = _group(db)
    bank = crud.add_account(db, g, m, bank_name="HDFC", last4="0611", kind="bank")
    card = crud.add_account(db, g, m, bank_name="HDFC", last4="6511", kind="credit_card")
    # Bare name -> the deposit account (sensible default).
    assert crud.find_account_in_text(db, g, "groceries 500 hdfc", member=m).id == bank.id
    # "card" hint -> the credit card.
    assert crud.find_account_in_text(db, g, "groceries 500 hdfc card", member=m).id == card.id


def test_amount_is_not_mistaken_for_last4(db):
    g, m = _group(db)
    # The amount (2002) must not be read as this account's last-4.
    acc = crud.add_account(db, g, m, bank_name="HSBC", last4="2002", kind="bank")
    # No other cue names it, so nothing should match on the amount alone... but the name
    # "hsbc" IS present, so it should match by name, not by the amount-as-last4 path.
    got = crud.find_account_in_text(db, g, "food swiggy 2002 hsbc", member=m, skip_amount=2002)
    assert got is not None and got.id == acc.id


def test_no_account_named_returns_none(db):
    g, m = _group(db)
    crud.add_account(db, g, m, bank_name="HDFC", last4="0611")
    assert crud.find_account_in_text(db, g, "coffee 80", member=m, skip_amount=80) is None


def test_expense_debits_named_card_owed_goes_up(db):
    g, m = _group(db)
    card = crud.add_account(db, g, m, bank_name="HSBC", last4="7893", kind="credit_card")
    reply = ingest.handle_text(db, g, m, "food swiggy 250 hsbc card", message_id="nl-1")
    assert "HSBC" in reply
    # Credit card: a charge makes the (negative) owed balance more negative.
    assert reports.account_balance(db, card) == -250


def test_expense_debits_named_bank_balance_goes_down(db):
    g, m = _group(db)
    bank = crud.add_account(db, g, m, bank_name="SBI", last4="8656", kind="bank",
                            opening_balance=5000)
    ingest.handle_text(db, g, m, "lunch 300 from sbi 8656", message_id="nl-2")
    assert reports.account_balance(db, bank) == 4700


def test_explicit_arrow_still_wins(db):
    g, m = _group(db)
    bank = crud.add_account(db, g, m, bank_name="HDFC", last4="0611", kind="bank",
                            opening_balance=1000)
    ingest.handle_text(db, g, m, "lunch 200 >hdfc", message_id="nl-3")
    assert reports.account_balance(db, bank) == 800


def test_by_source_separates_card_and_account_no_double_count(db):
    from datetime import date as _date
    from app import reports
    g, m = _group(db)
    bank = crud.add_account(db, g, m, bank_name="DCB", last4="2289", kind="bank",
                            opening_balance=10000)
    card = crud.add_account(db, g, m, bank_name="HSBC", last4="7893", kind="credit_card")

    # Two purchases: one on the card, one on the bank.
    ingest.handle_text(db, g, m, "groceries 1000 hsbc card", message_id="s1")
    ingest.handle_text(db, g, m, "fuel 500 dcb 2289", message_id="s2")

    # Pay part of the card bill — a settlement transfer, NOT new spending.
    crud.create_transfer(db, group=g, member=m, from_account=bank, to_account=card,
                         amount=800, currency="INR", on=_date.today(),
                         note="card payment")

    # Spending is counted once (purchases only) — the payment is not double-counted.
    assert reports.total(db, g) == 1500

    src = {r["source"]: r for r in reports.by_source(db, g)}
    assert src["HSBC ****7893"]["kind"] == "credit_card" and src["HSBC ****7893"]["amount"] == 1000
    assert src["DCB ****2289"]["amount"] == 500

    # Balances still tally: card owed 1000 − 800 paid = 200; bank 10000 − 500 − 800 = 8700.
    assert reports.account_balance(db, card) == -200
    assert reports.account_balance(db, bank) == 8700


def test_paycard_reduces_owed_and_source(db):
    g, m = _group(db)
    bank = crud.add_account(db, g, m, bank_name="DCB", last4="2289", kind="bank",
                            opening_balance=10000)
    card = crud.add_account(db, g, m, bank_name="HSBC", last4="7893", kind="credit_card")
    ingest.handle_text(db, g, m, "shopping 3000 hsbc card", message_id="pc-0")
    assert reports.account_balance(db, card) == -3000          # owed 3000

    reply = ingest.handle_text(db, g, m, "/paycard hsbc 1000 from dcb", message_id="pc-1")
    assert "Paid" in reply
    assert reports.account_balance(db, card) == -2000          # owed down to 2000
    assert reports.account_balance(db, bank) == 9000           # source down by 1000


def test_card_spend_raises_owed_not_assets(db):
    from datetime import date as _date
    from app.reports import net_worth, period_summary, month_bounds
    g, m = _group(db)
    crud.add_account(db, g, m, bank_name="DCB", last4="2289", kind="bank",
                     opening_balance=600000)
    crud.add_account(db, g, m, bank_name="HSBC", last4="7893", kind="credit_card")

    nw0 = net_worth(db, g)
    assert nw0["assets_in_accounts"] == 600000 and nw0["credit_card_owed"] == 0

    # Spend on the card: assets unchanged, owed up, net worth down.
    ingest.handle_text(db, g, m, "tv 2002 hsbc card", message_id="cs-1")
    nw1 = net_worth(db, g)
    assert nw1["assets_in_accounts"] == 600000          # assets did NOT move
    assert nw1["credit_card_owed"] == 2002              # liability rose
    assert nw1["total_owed"] == 2002
    assert nw1["net_worth"] == 600000 - 2002            # net worth fell

    # Period opening/closing balance (assets) is also unaffected by the card spend.
    today = _date.today()
    start, end = month_bounds(today.year, today.month)
    ps = period_summary(db, g, start, end)
    assert ps["opening_balance"] == 600000 and ps["closing_balance"] == 600000
    # Net change (assets) is flat, but NET WORTH change reflects the new card liability.
    assert ps["net_change"] == 0
    assert ps["net_worth_change"] == -2002


def test_paycard_resolves_shared_name_by_last4(db):
    g, m = _group(db)
    crud.add_account(db, g, m, bank_name="HDFC", last4="0611", kind="bank",
                     opening_balance=8000)
    hdfc_card = crud.add_account(db, g, m, bank_name="HDFC", last4="6511", kind="credit_card")
    ingest.handle_text(db, g, m, "groceries 2000 hdfc card", message_id="pc-2")
    # Both the bank and card are "HDFC"; the card's last-4 picks the right target.
    reply = ingest.handle_text(db, g, m, "/paycard 6511 500 from hdfc 0611", message_id="pc-3")
    assert "Paid" in reply
    assert reports.account_balance(db, hdfc_card) == -1500
