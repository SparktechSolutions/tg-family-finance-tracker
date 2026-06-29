# CLAUDE.md — TG Family Finance Tracker

> This file orients Claude Code. Read it first, then `docs/architecture.md` for the full design.

## What this project is

A **family finance tracker** driven from a shared WhatsApp group. Family members type
into the group; a bot (on the **WhatsApp Cloud API group webhook**, officially supported
since **21 May 2026**) parses each message, stores structured records, and replies with
confirmations and summaries. It tracks **expenses, income, bank/credit-card accounts,
investments, and insurance**, and shows a combined household net worth.

Stack: **Python 3.11+ · FastAPI · SQLAlchemy 2.0 · SQLite (dev) → Postgres (prod)**.

## Current status

**Implemented and tested (41 passing tests).** Features:
- Expense logging with category/payer/**source-account** hints; deduped on `wa_message_id`.
- **Interactive onboarding**: bot welcomes the group on join; each member sends `/start`
  and is walked through name → accounts (bank name + last 4 only).
- **Income** logging that credits an account; **expenses debit** their source account, so
  each account carries a running balance (opening + credits − debits).
- **Investments** with passive value updates; **insurance** with premium + due date.
- Commands, a web dashboard (net worth, accounts, investments, insurance due dates,
  charts, settle-up), and a JSON/CSV API.
Replies are sent via the Cloud API, or logged in dry-run when no token is set.

## Message syntax (the contract with users)

```
Expense:   <what> <amount> [#category] [@payer] [>account]
           Lunch 250 #food >hdfc          (debits the HDFC account)
Onboard:   /start            -> name? -> "HDFC 1234" / "ICICI credit 5678" -> done
Income:    /income 50000 salary >hdfc     (credits HDFC)
Invest:    /invest add mf 100000 Axis Bluechip
           /invest update Axis Bluechip 125000
           /investments
Insurance: /insurance add health 24000 2026-09-15 HDFC Ergo Family
           /due
Reports:   /total · /total <cat> · /month june · /split · /networth · /undo · /help
```
Account hints (`>token`) match a bank by name or by last-4. Amounts accept `₹ $ € £`,
commas, and decimals.

What's left for production hardening (not yet done):
- Confirm the live webhook **group-id payload shape** and fix `whatsapp._group_id_of`.
- Swap `create_all` for **Alembic** migrations; move to **Postgres**.
- Add **auth** to the dashboard/API (currently open; fine for local, not for deploy).
- Resolve real WhatsApp **display names** (currently stores the wa user id until a
  name is seen). Optionally fetch contact names from the webhook `contacts` block.
- Richer parsing: date overrides ("yesterday", "12 Jun"), explicit split shares.

## How to run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in WhatsApp creds when ready; works without them in dry-run
uvicorn app.main:app --reload # http://localhost:8000  (docs at /docs, health at /health)
pytest -q                     # parser tests
```

Local webhook testing: run `ngrok http 8000`, then set the Meta webhook callback URL to
`https://<ngrok>/webhook` with the verify token from `.env`. Subscribe to the `messages`
field and the group webhook fields.

## Project layout

```
app/
  main.py       FastAPI app + startup; serves dashboard at /
  config.py     env-based settings (pydantic-settings)
  db.py         engine + session + init_db()
  models.py     Group, Member, Account, Expense, Income, Investment, Insurance,
                ConversationState
  parser.py     expense string -> ParsedExpense (amount/category/payer/account)
  onboarding.py interactive per-member state machine (name -> accounts)
  commands.py   /income /invest /insurance /accounts /networth /total /split ... 
  crud.py       persistence helpers (get-or-create, dedupe, accounts, income, ...)
  reports.py    aggregations: totals, account balances, net worth, premiums, settle-up
  whatsapp.py   Cloud API send_text() + extract_messages()/extract_events() flatteners
  webhook.py    GET verify + POST receive; dispatcher: onboarding -> command -> expense
  api.py        read JSON/CSV API (/api/summary, /api/accounts, /api/investments, ...)
  static/index.html   single-file dashboard
tests/
  test_parser.py test_crud_reports.py test_commands.py test_finance.py test_api_webhook.py
docs/
  architecture.md   full design, costs, phased plan
```

## How dispatch works (webhook._process)

For each incoming message, in order: (1) if the member has an active onboarding state,
route to `onboarding.handle`; (2) if it's a `/command`, route to `commands.handle`;
(3) otherwise parse as an expense and persist (debiting a `>account` if named).
Onboarding is started by `/start` or the group-join welcome — it does NOT auto-hijack a
member's first message, so expense logging never gets blocked.

## Roadmap

- **Phase 1 — Ingest** ✅ webhook verify + receive + log.
- **Phase 2 — Persist** ✅ `crud.py` — dedupe on `wa_message_id`, get-or-create
  group/member, insert expense. Wired into `webhook._process`.
- **Phase 3 — Commands** ✅ `commands.py` — `/total`, `/total <category>`,
  `/month <name>`, `/split`, `/undo`, `/help`.
- **Phase 4 — Dashboard** ✅ `api.py` (JSON + CSV) and `static/index.html`
  (cards, category/person charts, recent table, export).
- **Phase 5 — Splitting** ✅ `reports.settle_up` equal-split who-owes-whom; surfaced
  in `/split` and the dashboard.
- **Next (open):** multi-currency normalization, edit/delete handling, monthly
  auto-report (see `schedule`), budget alerts, receipt-image OCR. Plus the production
  hardening list above.

## Conventions

- Keep `parser.py` dependency-free and unit-tested — it's the core and the easiest to break.
- Always store `raw_message` on every expense so messages can be re-parsed as the parser improves.
- `wa_message_id` is the idempotency key: webhooks get re-delivered, so **dedupe on it**.
- The webhook POST must return 200 fast; do heavy work without blocking the response.
- Confirm every logged expense back to the group so users catch mis-parses immediately.

## Known unknowns (verify against live data)

- The **exact group-id field** in the webhook payload is new (May 2026). `whatsapp._group_id_of`
  guesses among a few shapes — confirm with a real payload and fix it.
- Group **send** may require `recipient_type: "group"` + the group id as `to`; confirm in
  the current Meta docs and the Groups API for obtaining the group id.
- Meta may gate group send/receive behind **business verification / app review** in production.

## Out of scope / guardrails

- Do not move money or integrate payments. This only *records* expenses.
- Be explicit with group members that a bot logs messages (privacy).

## Channels

Messages can come from **WhatsApp** (`app/webhook.py`, Cloud API) or **Telegram**
(`app/telegram_bot.py`, free long-polling — no Meta, no hosting). Both resolve a
(group, member) and call the shared dispatcher `app/ingest.py:handle_text`. Telegram is the
recommended free path — see `docs/TELEGRAM.md`. Run with `./run.sh telegram`.

## Full-scale modules

Beyond expenses/income/accounts/investments/insurance, the app now covers: refunds, self-transfers, loans (borrowed/lent), **budgets + alerts**, **recurring items + reminders** (Telegram posts due-soon nudges daily), **personal vs shared** expenses (settle-up uses shared only), cash/asset account types, a Fees category, and a richer category map. The web dashboard is a sidebar app (Overview/Accounts/Cards/Loans/Investments/Insurance/Budgets/Recurring/Expenses) with add/edit/delete and 15s auto-refresh. Schema upgrades are handled by `db._auto_migrate` (adds missing columns; replace with Alembic for production).
