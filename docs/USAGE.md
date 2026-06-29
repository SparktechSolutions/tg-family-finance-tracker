# Usage Guide

Everything happens in your family's WhatsApp group. Type a message, the bot reads it and
replies with a confirmation. This guide covers onboarding, the message syntax, every
command, the dashboard, and the HTTP API.

---

## 1. Getting started (onboarding)

When the bot is added to the group it posts a welcome and asks everyone to set up.
Each member runs onboarding individually:

```
You:  /start
Bot:  👋 Welcome! Let's set you up. What's your name?
You:  Anita
Bot:  Nice to meet you, Anita! 🏦  Now add your accounts, one per message…
You:  HDFC 1234
Bot:  ➕ Added HDFC ****1234 (account). Add another, or type done.
You:  ICICI credit 5678
Bot:  ➕ Added ICICI ****5678 (credit card). Add another, or type done.
You:  done
Bot:  ✅ All set, Anita! Your accounts: … Now you can log money.
```

- Account format: `<Bank> <last4>` for a bank, `<Bank> credit <last4>` for a card.
- Only the **bank name and last 4 digits** are stored — never full account numbers.
- Type **done** (or **skip**) to finish. You can re-run `/start` anytime.
- Onboarding state is per person, so several family members can set up at once without
  interfering with each other or with normal expense logging.

---

## 2. Logging an expense

Plain messages with a number are treated as expenses:

```
Lunch 250 #food >hdfc
```

| Token | Meaning | Example |
|---|---|---|
| amount | first number; supports `₹ $ € £`, commas, decimals | `250`, `₹1,250.75`, `$12.50` |
| `#category` | explicit category | `#food`, `#transport` |
| (keyword) | category inferred from a known word if no `#tag` | `coffee 80` → Food |
| `@payer` | who paid (defaults to you) | `dinner 600 @ravi` |
| `>account` | source account to **debit** (by bank name or last-4) | `>hdfc`, `>1234` |

Examples:

```
coffee 80                     → 80, Food (inferred), you paid
uber 120 #transport           → 120, Transport
₹1,500 groceries @ravi >hdfc  → 1500 from HDFC, paid by Ravi
```

A message **without** a number is ignored as normal chatter.

---

## 3. Income

```
/income 50000 salary >hdfc
```

- First number is the amount; remaining words are the source (defaults to "Income").
- `>account` **credits** that account.

---

## 4. Accounts

| Command | What it does |
|---|---|
| `/start` | add/refresh your name and accounts (interactive) |
| `/accounts` | list all accounts with their current balances |

**Balance** of an account = opening balance + income credited − expenses debited.
Spending on a **credit card** shows as a negative balance (what you owe the card).

---

## 5. Investments (passive updates)

```
/invest add mf 100000 Axis Bluechip      # add a holding (kind, invested amount, name)
/invest update Axis Bluechip 118000      # later, update its current value
/investments                             # list all holdings with gain/loss
```

- Recognised kinds: `stocks, equity, mf, fd, rd, crypto, gold, bonds, etf, ppf, nps,
  realestate, property, other` (anything else defaults to `other`).
- "Passive" means you update the value whenever you check it; the bot tracks gain
  (current − invested).

---

## 6. Insurance & premiums

```
/insurance add health 24000 2026-09-15 HDFC Ergo Family
/due                                     # list policies + days until each premium is due
```

- Order is flexible: kind, premium amount, a `YYYY-MM-DD` due date, and the policy name
  can appear in any order — the parser picks out the date and number.
- Optional frequency keyword: `monthly`, `quarterly`, `yearly` (default `yearly`).
- `/due` flags overdue policies and ones due soon.

---

## 6b. Refunds

Money back for an earlier purchase — credits the account and reduces net spend:

```
/refund 500 #shopping >hdfc returned shoes
refund 500 #shopping >hdfc                  (keyword form, no slash)
```

It links to your most recent matching expense automatically. Use this (not `/income`)
when a purchase is reversed. See [SYNC.md](SYNC.md) for the full model.

## 7. Reports

| Command | Output |
|---|---|
| `/total` | this month's income, expenses, and net |
| `/total <category>` | this month's spend for one category |
| `/month <name>` | a category breakdown for that month (e.g. `/month june`) |
| `/split` | equal-split "who owes whom" across the group |
| `/networth` | household snapshot: cash + investments = net worth |
| `/undo` | remove your most recently logged expense |
| `/help` | the full command cheat-sheet |

---

## 8. Command quick reference

```
/start                                   set up name + accounts
/accounts                                list accounts & balances
/income <amount> [source] [>account]     log income (credits account)
/invest add <kind> <amount> <name>       add an investment
/invest update <name> <value>            update an investment's value
/investments                             list investments
/insurance add <kind> <premium> <date> <name>   add a policy (date = YYYY-MM-DD)
/due                                     upcoming premiums
/total [category]                        monthly totals
/month <name>                            monthly breakdown
/split                                   settle up
/networth                                household net worth
/undo                                    undo last expense
/help                                    help
```

---

## 9. The dashboard

Open <http://localhost:8000/>. It shows, per group (selectable in the header):

- **KPI cards:** net worth, cash in accounts, investments value, income & expenses this month
- **Charts:** spending by category and by person
- **Accounts** with live balances, **Investments** with gain/loss, **Insurance** with
  colour-coded due dates (overdue / due soon)
- **Settle up** and a **recent expenses** table
- **Export CSV** button (per group)

The dashboard reads everything from the JSON API below and has a Reload button.

---

## 10. HTTP API reference

All endpoints are read-only JSON unless noted. `group_id` is optional and defaults to the
first group.

| Method & path | Description |
|---|---|
| `GET /health` | `{"status":"ok"}` |
| `GET /` | the dashboard (HTML) |
| `GET /webhook` | Meta verification handshake |
| `POST /webhook` | incoming WhatsApp events (messages + lifecycle) |
| `GET /api/groups` | list groups |
| `GET /api/summary?group_id=` | net worth, income/expense totals, by-category, by-member, accounts, investments, insurance, settlements |
| `GET /api/expenses?group_id=&category=&limit=` | recent expenses |
| `GET /api/expenses.csv?group_id=` | CSV export |
| `GET /api/accounts?group_id=` | accounts with balances |
| `GET /api/investments?group_id=` | investments with gain/loss |
| `GET /api/insurance?group_id=` | policies with days-until-due |
| `POST /api/import/chat?wa_group_id=&currency=` | backfill from a WhatsApp chat export (raw .txt body) |

Example:

```bash
curl "http://localhost:8000/api/summary" | python -m json.tool
```

---

## 11. Known limitations

- **Indian digit grouping** (`12,34,567`) isn't parsed; use plain digits (`1234567`) or
  Western grouping (`1,234,567`).
- **Multi-currency** is stored per record but **not converted** — totals assume one
  currency per group (the group's `DEFAULT_CURRENCY`).
- **Settle-up** assumes every member shares every expense equally.
- **Display names** come from onboarding; before a member runs `/start`, they appear by
  their WhatsApp id.
