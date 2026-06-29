# TG Family Finance Tracker

Track your family's money from a WhatsApp group. A bot reads the messages via the
WhatsApp Cloud API and structures everything: **expenses, income, bank & credit-card
accounts, investments, and insurance** — with a combined household net worth and a web
dashboard.

```
You (in group):  Lunch 250 #food >hdfc
Bot:             ✅ Logged INR 250.00 · Food · Lunch · from HDFC ****1234
```

When the bot joins the group it welcomes everyone; each member sends `/start` and is
walked through their name and accounts (only the bank name + last 4 digits are stored).

## Documentation

| Doc | What's in it |
|---|---|
| [docs/TELEGRAM.md](docs/TELEGRAM.md) | **Free** Telegram setup (no Meta, real-time, no hosting) |
| [docs/USER_MANUAL.md](docs/USER_MANUAL.md) | Complete end-user manual (onboarding, recipes, FAQ) |
| [docs/INSTALLATION.md](docs/INSTALLATION.md) | Install, env config, running, ngrok + Meta webhook setup, deployment |
| [docs/USAGE.md](docs/USAGE.md) | Onboarding walkthrough, full message + command reference, dashboard, API reference |
| [docs/TECH.md](docs/TECH.md) | Tech stack, module map, data model, dispatch flow, design decisions |
| [docs/SYNC.md](docs/SYNC.md) | Offline behaviour, idempotency, chat-export backfill, and refunds |
| [docs/TESTING.md](docs/TESTING.md) | Test suite layout and how to run/extend it |
| [docs/architecture.md](docs/architecture.md) | Complete architecture & technical reference |
| [CLAUDE.md](CLAUDE.md) | Orientation for working in the codebase |

## Tech stack

Python 3.11+ · FastAPI · SQLAlchemy 2.0 · SQLite → PostgreSQL · httpx · Chart.js dashboard
· pytest (60 tests). WhatsApp **Cloud API** with group messaging (official since May 2026).

## Quick start

One command does everything (setup + tests + run):

```bash
./run.sh          # macOS/Linux/WSL/Git Bash
.\run.ps1         # Windows PowerShell
```

Or manually:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
pytest -q
```

App runs at http://localhost:8000 (`/docs`, `/health`). It works in **dry-run** without
WhatsApp credentials — outgoing replies are logged instead of sent — so you can develop
the parser and persistence offline.

## Message format

```
Expense:   <what> <amount> [#category] [@payer] [>account]
           Lunch 250 #food >hdfc
Onboard:   /start          (then: name, then "HDFC 1234" / "ICICI credit 5678", then done)
Income:    /income 50000 salary >hdfc
Invest:    /invest add mf 100000 Axis Bluechip
           /invest update Axis Bluechip 125000   ·   /investments
Insurance: /insurance add health 24000 2026-09-15 HDFC Ergo   ·   /due
Reports:   /total · /total <category> · /month <name> · /split · /networth · /undo · /help
```

`>account` debits the named account on an expense and credits it on income, so each
account shows a running balance. Accounts are matched by bank name or last-4 digits.

## Connecting to WhatsApp

1. Create a Meta for Developers app, add the WhatsApp product, get an access token + phone number id.
2. Fill `.env`.
3. Expose your local server: `ngrok http 8000`.
4. In Meta, set the webhook callback to `https://<ngrok>/webhook` with your verify token;
   subscribe to `messages` + the group webhook fields.
5. Add the bot number to your group and obtain the group id via the Groups API.

For full setup details (permanent tokens, deployment) see
[docs/INSTALLATION.md](docs/INSTALLATION.md).

## Status

The full application — expenses, income, accounts, investments, insurance, interactive
onboarding, dashboard, and JSON/CSV API — is implemented and covered by **60 passing
tests**. Remaining production-hardening items (live group-payload verification, Postgres +
Alembic, dashboard auth) are listed in [docs/TECH.md](docs/TECH.md) and **CLAUDE.md**.
