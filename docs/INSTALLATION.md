# Installation Guide

Get the TG Family Finance Tracker running on any local machine. The fastest path is
the bundled CLI script; manual steps and the WhatsApp connection follow.

---

## Quick start (one command)

From the project root:

```bash
# macOS / Linux / WSL / Git Bash
./run.sh
```
```powershell
# Windows (PowerShell)
.\run.ps1
```

That single command: checks your Python, creates a virtualenv, installs dependencies,
creates `.env`, runs the test suite, and starts the app. Then open:

- Dashboard → <http://localhost:8000/>
- API docs (Swagger) → <http://localhost:8000/docs>
- Health → <http://localhost:8000/health>

It runs in **dry-run mode** with no WhatsApp credentials — replies are logged, not sent —
so you can explore immediately and connect WhatsApp later.

### Script subcommands

```bash
./run.sh setup        # create venv, install deps, create .env
./run.sh start        # run the web app + dashboard
./run.sh test         # run the test suite
./run.sh connector    # set up the Cowork MCP connector (separate venv) + print config
./run.sh import FILE  # backfill from a WhatsApp chat export (.txt)
./run.sh doctor       # check environment (Python, port)
./run.sh clean        # remove the virtualenvs
./run.sh help         # usage
PORT=8001 ./run.sh start   # use a different port
```

---

## Prerequisites

- **Python 3.10+** (3.11+ recommended). `./run.sh doctor` verifies this.
- For live WhatsApp use: a **Meta for Developers** account + WhatsApp Business app.
- For local webhook testing: **ngrok** (or any HTTPS tunnel).

---

## Manual install (if you prefer)

```bash
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
pytest -q                           # 77 passing tests
```

> **SQLite + network drives:** SQLite needs a filesystem that supports file locking. If you
> run from a synced/virtual folder and see `disk I/O error`, set
> `DATABASE_URL=sqlite:////tmp/expenses.db` (or use PostgreSQL).

---

## Environment variables (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `WHATSAPP_VERIFY_TOKEN` | `change-me` | echoed back during webhook verification |
| `WHATSAPP_ACCESS_TOKEN` | _(empty)_ | Cloud API token. Empty ⇒ **dry-run** |
| `WHATSAPP_PHONE_NUMBER_ID` | _(empty)_ | bot number's phone-number id |
| `WHATSAPP_API_VERSION` | `v21.0` | Graph API version |
| `DATABASE_URL` | `sqlite:///./expenses.db` | SQLAlchemy URL; use Postgres in prod |
| `DEFAULT_CURRENCY` | `INR` | default currency for new groups |
| `LOG_LEVEL` | `INFO` | logging level |

---

## Connect to WhatsApp (go live)

1. **Create the app** at [developers.facebook.com](https://developers.facebook.com) →
   Business app → add the **WhatsApp** product.
2. **Credentials** → copy the access token + Phone Number ID into `.env`. For production,
   use a permanent system-user token.
3. **Expose your server**: `ngrok http 8000` → copy the `https://…ngrok…` URL.
4. **Webhook** (Meta → WhatsApp → Configuration):
   - Callback URL: `https://<ngrok>/webhook`
   - Verify token: matches `WHATSAPP_VERIFY_TOKEN`
   - **Verify and save**, then subscribe to `messages` + the group fields
     (`group_lifecycle_update`, `group_participants_update`, …).
5. **Add the bot** to your family group and obtain the group id via the Groups API.
6. **Test**: send `Lunch 250 #food` in the group — it should appear on the dashboard.

> ⚠️ Group messaging is new (May 2026). Verify the live webhook payload shape and adjust
> `app/whatsapp._group_id_of` / `extract_events` if field names differ. Meta may require
> business verification before group send/receive is enabled.

---

## Set up the Cowork connector (optional)

```bash
./run.sh connector
```
This creates a separate virtualenv (the `mcp` SDK and FastAPI need different `starlette`
versions) and prints the MCP config block to paste into Claude/Cowork. Full guide:
[../connector/README.md](../connector/README.md).

---

## Production deployment (outline)

- **Database:** PostgreSQL via `DATABASE_URL`; replace `init_db()` `create_all` with Alembic.
- **Host:** Render / Railway / Fly.io / container with a stable HTTPS URL:
  `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2`.
- **Secrets:** use the platform's secret store, not a committed `.env`.
- **Auth & TLS:** put the dashboard and `/api/*` behind auth before exposing real data.
- **Token:** permanent Meta system-user token; verify webhook signatures.

See [ARCHITECTURE.md](ARCHITECTURE.md) §10–11 for the full deployment and security notes.
