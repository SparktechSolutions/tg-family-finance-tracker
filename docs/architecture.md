# Architecture & Technical Reference

The complete technical document for the TG Family Finance Tracker: stack, components,
data model, request flows, reliability model, refunds, deployment, and security. For the
original design rationale and cost model see [architecture.md](architecture.md); for the
module-level quick map see [TECH.md](TECH.md).

---

## 1. What it is

A family logs money in a shared **WhatsApp group**; a bot reads the messages, structures
them, and replies. The same data is also reachable from **Claude Cowork** through an MCP
connector and a live dashboard. It tracks **expenses, income, bank/credit-card accounts,
investments, and insurance**, computes a combined **household net worth**, and supports
**refunds** and **offline backfill**.

---

## 2. Tech stack

| Concern | Technology | Notes |
|---|---|---|
| Language | Python 3.10+ (3.11+ recommended) | fully type-hinted |
| Web/API | FastAPI + Uvicorn (ASGI) | webhook, JSON/CSV API, serves dashboard |
| ORM | SQLAlchemy 2.0 (typed `Mapped[...]`) | |
| Database | SQLite (dev) → PostgreSQL (prod) | via `DATABASE_URL` |
| Config | pydantic-settings | env / `.env` |
| HTTP client | httpx (async) | WhatsApp Cloud API calls |
| Messaging | WhatsApp **Cloud API** (group messaging, GA May 2026) | |
| Cowork | MCP server (`mcp` SDK, stdio) | separate process & venv |
| Dashboard | HTML + vanilla JS + Chart.js (CDN) | single file; web + Cowork variants |
| Tests | pytest + FastAPI TestClient | 77 base, 11 connector |
| Tooling | `run.sh` / `run.ps1` one-command CLI | setup/test/start/connector/import |

---

## 3. System architecture

```
        ┌──────────────────────── shared core (app/) ─────────────────────────┐
        │  parser · crud · reports · commands · onboarding · importer · models │
        └───────────▲───────────────────────────────────────────▲─────────────┘
                    │                                             │
   WhatsApp group   │                                             │   Claude Cowork
        │           │                                             │        │
        ▼           │                                             │        ▼
 WhatsApp Cloud API │                                             │   MCP connector
        │           │                                             │   (connector/)
   webhook POST ─▶ FastAPI (app/) ─┐                              └─▶ tools + live
        ▲                          │                                   dashboard artifact
        └── Send API ◀─ replies    ├─▶ SQLite / PostgreSQL  ◀──────────────┘
                                   └─▶ web dashboard + JSON/CSV API
```

Two independent front-ends (FastAPI webhook, MCP connector) sit over **one core and one
database**, so a family can log via WhatsApp and via Cowork against the same ledger.

---

## 4. Components (`app/`)

| Module | Responsibility |
|---|---|
| `main.py` | FastAPI app; mounts routers + static; serves dashboard at `/` |
| `config.py` | env-based `Settings` |
| `db.py` | engine, `SessionLocal`, `get_session`, `init_db()` |
| `models.py` | ORM models (§6) |
| `parser.py` | `parse_expense` / `parse_refund` — text → structured fields (pure, no I/O) |
| `onboarding.py` | interactive per-member state machine (name → accounts) |
| `commands.py` | `/`-commands → reply text |
| `crud.py` | persistence + dedupe + inbound-event log helpers |
| `reports.py` | aggregations: totals, balances, net worth, premiums, settle-up |
| `importer.py` | WhatsApp chat-export backfill |
| `whatsapp.py` | Cloud API `send_text`; `extract_messages` / `extract_events` |
| `webhook.py` | `GET/POST /webhook`; the dispatcher |
| `api.py` | read JSON/CSV API + `/api/import/chat` |
| `static/index.html` | web dashboard |

`connector/` adds `core_ops.py` (session-managed operations over the core) and `server.py`
(MCP tools), plus `dashboard_artifact.html` (the Cowork live dashboard).

---

## 5. Request flow (dispatcher)

`webhook.POST /webhook` → for each message:

1. **Record** the raw event to `inbound_events` (durability); if the `wa_message_id` was
   already seen, **skip** (Meta re-delivery — idempotent).
2. **Onboarding** — if the member has an active `ConversationState`, route to onboarding.
3. **Command** — if it starts with `/` or `!`, route to `commands.handle`.
4. **Refund** — if it starts with the `refund` keyword, record a refund.
5. **Expense** — else parse; if it has an amount, persist (debit a `>account` if named).
   No amount → ignored as chatter.

Each message uses its own DB session; one failure is logged and rolled back without
breaking the batch. The endpoint returns `200` quickly so Meta doesn't retry-storm.

---

## 6. Data model

```
Group 1─*  Member 1─*  Account
  │            │  *expenses (incl. refunds: is_refund + negative amount)
  │            │  *incomes        ── account_id ─▶ Account (credit)
  │            │  *investments
  │            │  *insurances
  │
  ├─*  Expense  ── account_id ─▶ Account (debit) ; original_expense_id ─▶ Expense
  └─*  InboundEvent (raw webhook log)
Member 1─1 ConversationState (onboarding)
```

| Entity | Notable fields |
|---|---|
| Group | `wa_group_id` (unique), `currency` |
| Member | `wa_user_id`, `display_name`, `onboarded` |
| Account | `kind` (bank/credit_card), `bank_name`, `last4`, `opening_balance` |
| Expense | `amount` (negative for refunds), `category`, `account_id`, `is_refund`, `original_expense_id`, `wa_message_id` (unique) |
| Income | `amount`, `source`, `account_id`, `wa_message_id` (unique) |
| Investment | `name`, `kind`, `invested_amount`, `current_value`, `as_of` |
| Insurance | `name`, `kind`, `premium_amount`, `frequency`, `due_date` |
| InboundEvent | `dedupe_key` (unique), `payload`, `processed`, `error` |
| ConversationState | `member_id` (PK), `flow`, `step`, `scratch` (JSON) |

### Invariants
- **Idempotency** — expense/income/refund unique on `wa_message_id`; re-deliveries dedupe.
- **Balances are computed**: `opening + Σincome − Σexpenses` (refunds are negative
  expenses, so they credit the account and reduce spend automatically). No drift.
- **Privacy** — accounts store only bank name + last 4 digits.

---

## 7. Reliability & offline behaviour

WhatsApp has **no history API**, so missed messages can't be pulled later. Coverage layers:

1. **Idempotency** → safe under Meta's webhook retries (short outages).
2. **Durable inbound-event log** → survives a crash *during* processing; reprocessable.
3. **Meta retries** → cover minutes–hours of downtime.
4. **Chat-export importer** → the reliable backfill for long outages; deterministic
   per-line ids make re-imports idempotent.

Full detail and the refund model in [SYNC.md](SYNC.md).

---

## 8. Refunds

A refund is an `Expense` with `is_refund=True` and a **negative amount**, linked to the
original where possible. This nets category spend down and credits the source account with
zero special-casing in the SUM-based reports. Recordable from WhatsApp (`/refund` or the
`refund` keyword), Cowork (`log_refund`), and chat imports.

---

## 9. External interface (HTTP)

| Endpoint | Purpose |
|---|---|
| `GET /` · `GET /health` | dashboard · health |
| `GET/POST /webhook` | Meta verify · receive messages/events |
| `GET /api/summary` | net worth, totals, by-category/member, accounts, investments, insurance, settlements |
| `GET /api/expenses[.csv]` | recent expenses · CSV export |
| `GET /api/accounts \| /investments \| /insurance` | entity lists |
| `POST /api/import/chat` | chat-export backfill |

MCP connector tools: `log_expense(_text)`, `log_refund`, `add_income`, `add_account`,
`list_accounts`, `add_investment`, `update_investment`, `list_investments`,
`add_insurance`, `upcoming_premiums`, `net_worth`, `monthly_summary`, `settle_up`,
`recent_expenses`, `import_chat`.

---

## 10. Deployment

- **DB:** set `DATABASE_URL` to PostgreSQL; replace `init_db()`'s `create_all` with
  **Alembic** migrations.
- **Host:** any platform with a stable public HTTPS URL (Render/Railway/Fly.io/container):
  `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2`.
- **WhatsApp:** point the Meta webhook at `https://<host>/webhook`; subscribe to `messages`
  + group fields; use a permanent system-user token.
- **Connector:** runs locally next to Cowork in its own venv (`run.sh connector`).

---

## 11. Security & privacy

- Store only **bank name + last 4** — never full account numbers; no payment credentials.
- `.gitignore` excludes `.env`, `*.db`, and the venvs.
- The dashboard and `/api/*` are **unauthenticated** — fine for local/private use; add auth
  and TLS before exposing real data.
- Verify Meta webhook signatures in production (planned hardening).
- The connector is **local/self-hosted**, not a public Anthropic directory listing.

---

## 12. Known limitations

- No WhatsApp message-history API (hence the chat-export importer).
- Indian digit grouping (`12,34,567`) not parsed — use plain digits or Western grouping.
- Multi-currency is stored but **not converted**; one currency per group is assumed.
- Settle-up assumes equal sharing across members.
- The live group webhook payload shape is new (May 2026) — verify and adjust
  `whatsapp._group_id_of` / `extract_events` against real deliveries.

---

## 13. Costs (WhatsApp Cloud API)

WhatsApp uses **per-message** pricing (per delivered template) since 1 Jul 2025. The bot
almost always replies inside the **24-hour service window** opened by a user's message —
those service messages are **free worldwide**. Business-initiated template messages
outside the window cost fractions of a cent and vary by country. For a single family the
effective messaging cost is **~zero**; hosting (a small VM or free tier) is the real cost.
