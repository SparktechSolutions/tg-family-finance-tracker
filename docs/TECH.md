# Technical Overview

## Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Language | **Python 3.11+** | Type-hinted throughout |
| Web framework | **FastAPI** | Webhook + JSON API + serves the dashboard |
| ASGI server | **Uvicorn** | `uvicorn app.main:app` |
| ORM | **SQLAlchemy 2.0** | Typed `Mapped[...]` models |
| Database | **SQLite** (dev) → **PostgreSQL** (prod) | Switch via `DATABASE_URL` |
| Settings | **pydantic-settings** | Env-based config |
| HTTP client | **httpx** | Async calls to the WhatsApp Cloud API |
| Dashboard | **Vanilla HTML/JS + Chart.js** (CDN) | Single self-contained file |
| Tests | **pytest** + FastAPI `TestClient` | 60 tests, in-memory SQLite |

No frontend build step, no message queue, no external cache — a single FastAPI process.

---

## How it connects to WhatsApp

Messages flow through the **WhatsApp Cloud API**, which gained official **group
messaging** support on **21 May 2026** (send + receive via webhooks). The bot is a
WhatsApp Business number added to the family group:

```
 Family group ──▶ WhatsApp Cloud API ──webhook POST──▶ /webhook (FastAPI)
       ▲                                                    │
       └──────────── Send Message API ◀────────────────────┘  (confirmations, reports)
```

Replies sent inside the 24-hour service window are free, so the bot's confirmations cost
effectively nothing. See `docs/architecture.md` §7 for the cost model.

---

## Module map (`app/`)

| Module | Responsibility |
|---|---|
| `main.py` | FastAPI app; mounts routers + static; serves dashboard at `/` |
| `config.py` | `Settings` from env / `.env` |
| `db.py` | Engine, `SessionLocal`, `get_session` dependency, `init_db()` |
| `models.py` | SQLAlchemy models (see data model below) |
| `parser.py` | `parse_expense(text)` → `ParsedExpense` (amount/category/payer/account) — pure, dependency-free |
| `onboarding.py` | Interactive per-member state machine (name → accounts) |
| `commands.py` | All `/commands` → reply text. Pure functions of `(db, group, member, text)` |
| `crud.py` | Persistence: get-or-create, dedupe, accounts, income, investments, insurance |
| `reports.py` | Aggregations: totals, account balances, net worth, premiums, settle-up |
| `whatsapp.py` | `send_text()`, `extract_messages()`, `extract_events()` |
| `webhook.py` | `GET /webhook` verify + `POST /webhook` receive + dispatcher |
| `api.py` | Read JSON/CSV API under `/api` |
| `static/index.html` | The dashboard |

**Design principle:** business logic (`parser`, `commands`, `crud`, `reports`,
`onboarding`) is decoupled from HTTP and from the WhatsApp client, so it's all unit
testable without a running server or Meta credentials.

---

## Data model

```
Group (1)───(N) Member (1)───(N) Account
   │                │
   │                ├──(N) Expense   ── account_id ─▶ Account   (debit)
   │                ├──(N) Income    ── account_id ─▶ Account   (credit)
   │                ├──(N) Investment
   │                └──(N) Insurance
   │
Member (1)───(1) ConversationState   (onboarding flow)
```

| Entity | Key fields |
|---|---|
| **Group** | `wa_group_id` (unique), `currency` |
| **Member** | `wa_user_id`, `display_name`, `onboarded` |
| **Account** | `kind` (bank/credit_card), `bank_name`, `last4`, `opening_balance` |
| **Expense** | `amount`, `category`, `note`, `spent_at`, `account_id`, `wa_message_id` (unique) |
| **Income** | `amount`, `source`, `received_on`, `account_id`, `wa_message_id` (unique) |
| **Investment** | `name`, `kind`, `invested_amount`, `current_value`, `as_of` |
| **Insurance** | `name`, `kind`, `premium_amount`, `frequency`, `due_date` |
| **ConversationState** | `member_id` (PK), `flow`, `step`, `scratch` (JSON) |

### Key invariants

- **Idempotency:** `Expense.wa_message_id` and `Income.wa_message_id` are unique. Webhooks
  can be re-delivered; inserts dedupe on this key so nothing is double-counted.
- **Account balances are computed, not stored:**
  `balance = opening_balance + Σ income(credits) − Σ expenses(debits)`.
  This avoids drift from a mutable running-total field.
- **Privacy:** accounts hold only bank name + last 4 digits, by design.

---

## Message dispatch (`webhook._process`)

Each incoming message is handled in a fresh DB session, in this order:

1. **Onboarding** — if the member has an active `ConversationState`, the message is routed
   to `onboarding.handle` (so their reply isn't mistaken for an expense).
2. **Command** — if the text starts with `/` or `!`, route to `commands.handle`.
3. **Expense** — otherwise `parse_expense`; if it yields an amount, persist it (debiting a
   `>account` if named) and reply with a confirmation. No amount ⇒ ignored as chatter.

Onboarding is started by `/start` or by the group-join welcome — **not** by
auto-hijacking a member's first message, which would block expense logging. Each message
is processed independently; a failure on one is logged and rolled back without breaking
the webhook batch (which always returns 200 quickly so Meta doesn't retry-storm).

---

## Extending it

- **New command:** add a branch in `commands.handle` and a helper; add a test in
  `tests/test_commands.py`.
- **New category keywords:** edit `CATEGORY_KEYWORDS` in `parser.py`.
- **New entity:** add a model in `models.py`, CRUD in `crud.py`, aggregation in
  `reports.py`, expose it in `api.py`, and surface it in `static/index.html`.
- **Migrations:** replace `init_db()`'s `create_all` with Alembic before production.

---

## Production hardening checklist

- [ ] Verify the live group-message webhook payload; fix `whatsapp._group_id_of` /
      `extract_events` to match real field names (the Groups API is new).
- [ ] PostgreSQL + Alembic migrations.
- [ ] Auth on the dashboard and `/api/*`.
- [ ] Permanent Meta system-user token; business verification if required.
- [ ] Resolve real WhatsApp display names (optionally from the webhook `contacts` block).
- [ ] Rate-limit/batch replies in very chatty groups.
