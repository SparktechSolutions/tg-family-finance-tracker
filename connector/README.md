# Family Finance — Claude Cowork connector

Use the finance tracker straight from **Claude Cowork**: a local **MCP connector** for
actions ("log 250 for lunch from HDFC", "what's our net worth?") plus a **live dashboard
artifact** for viewing.

It reuses the existing core (`app.crud`, `app.reports`, `app.parser`) and reads/writes the
**same database** as the WhatsApp bot — so the family can log via WhatsApp *and* via
Cowork against one shared ledger. The base project is unchanged; this lives in `connector/`.

```
                shared core + database
               /                        \
   WhatsApp bot (FastAPI)        Cowork connector (MCP)  ──▶ live dashboard artifact
```

---

## 1. Install (use a separate virtualenv)

The connector is its own process and does **not** use FastAPI. Because the `mcp` package
and `fastapi` want different `starlette` versions, install the connector in its **own
virtualenv** — it only needs the app's core (parser/crud/reports/models), not the web app.

From the project root:

```bash
python -m venv .venv-connector
source .venv-connector/bin/activate        # Windows: .venv-connector\Scripts\activate
pip install -r connector/requirements.txt
```

## 2. Run / test locally

```bash
# smoke-test the tools without Cowork (stdio MCP server; Ctrl-C to stop)
python -m connector.server

# the connector's logic tests (run from the project root)
pytest tests/test_connector.py -q
```

> The base app's tests (`pytest -q` in the main venv) also include the connector's
> *logic* tests — they don't need `mcp`. Only the server-import test requires `mcp` and is
> skipped automatically when it isn't installed.

## 3. Connect it to Cowork / Claude Desktop

Add it as a local MCP server in your Claude config (e.g. `claude_desktop_config.json`, or
Cowork's connector settings). Use absolute paths.

```json
{
  "mcpServers": {
    "family-finance": {
      "command": "python",
      "args": ["-m", "connector.server"],
      "cwd": "/ABSOLUTE/PATH/TO/tg-family-finance-tracker",
      "env": {
        "DATABASE_URL": "sqlite:////ABSOLUTE/PATH/TO/expenses.db",
        "FINANCE_GROUP_ID": "cowork-household",
        "FINANCE_MEMBER": "You"
      }
    }
  }
}
```

- Point `DATABASE_URL` at the **same** database the WhatsApp bot uses to share one ledger.
- Set `FINANCE_GROUP_ID` to the WhatsApp group's `wa_group_id` if you want Cowork and the
  group to be the *same* household; otherwise the connector uses its own household bucket.
- Use a virtualenv's Python in `command` if you installed into one.

Restart Cowork; you should see the **family-finance** tools available. Try:

> "Add my HDFC account ending 1234." · "Log 250 for lunch from HDFC." ·
> "Record my 90000 salary into HDFC." · "What's our net worth?" · "What premiums are due?"

## 4. The live dashboard artifact

`dashboard_artifact.html` is a Cowork **live artifact**: it calls the connector's tools on
open and renders net worth, accounts, investments, insurance due dates, settle-up, and
recent expenses. To publish it, ask Cowork (with this connector connected):

> "Create a live artifact from connector/dashboard_artifact.html wired to the
>  family-finance connector tools."

Cowork will register it with the finance tools so it refreshes live each time you open it.
If the connector isn't connected, the artifact shows a friendly prompt instead of breaking.

---

## Tools exposed

| Tool | Purpose |
|---|---|
| `log_expense` / `log_expense_text` | log an expense (structured, or freeform shorthand) |
| `add_income` | record income; credits an account |
| `add_account` / `list_accounts` | manage accounts (bank name + last4 only) |
| `add_investment` / `update_investment` / `list_investments` | holdings + passive value updates |
| `add_insurance` / `upcoming_premiums` | policies + due-date reminders |
| `net_worth` / `monthly_summary` / `settle_up` / `recent_expenses` | reports |

## Notes & limits

- This is a **local / self-hosted** connector for your own use — not a listing in
  Anthropic's public connector directory (that's a separate submission process).
- Actions you take in Cowork are attributed to the single `FINANCE_MEMBER` identity; the
  per-person attribution from WhatsApp (each sender) still applies to messages logged there.
- Same production caveats as the base app: use Postgres + Alembic, add auth, verify the
  live WhatsApp group webhook payloads.
