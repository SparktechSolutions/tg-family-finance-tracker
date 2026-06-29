# Offline Sync, Reliability & Refunds

## What happens if the server is off?

WhatsApp's Cloud API **pushes** messages to your webhook; there is **no API to fetch past
group messages**. So you can't simply "pull what you missed." Here's how the system stays
correct anyway, in order of how much they cover:

| Mechanism | Covers | How |
|---|---|---|
| **Idempotency** | Duplicate/retried deliveries | Every expense/income/refund is unique on `wa_message_id`; re-delivery is recognised and skipped — never double-counted. |
| **Durable inbound-event log** | Crash *during* processing (server up, logic fails) | Each raw webhook is written to `inbound_events` **before** processing. If processing throws, the event is preserved and can be reprocessed. Re-deliveries are deduped on the same key. |
| **Meta webhook retries** | Short outages (minutes–hours) | If your endpoint is unreachable/returns non-200, Meta retries with backoff for a window. Because of idempotency, those retries are safe when you come back up. |
| **Chat-export import** | Long outages (server fully OFF past Meta's retry window) | Export the WhatsApp chat and replay it (below). This is the reliable backfill. |

> **The honest limitation:** if the server is off long enough that Meta stops retrying,
> the only way to recover those expenses is the chat export — because WhatsApp will not
> give them to you via API later.

## Backfilling from a WhatsApp chat export

1. In WhatsApp: open the group → **⋮ / group name → Export chat → Without media**.
2. You get a `.txt` like:
   ```
   12/06/2026, 21:34 - Anita: Lunch 250 #food
   12/06/2026, 21:40 - Ravi: refund 50 #transport
   ```
3. Import it:
   - **CLI:** `python -m app.importer chat.txt --group <wa_group_id>`
   - **API:** `POST /api/import/chat?wa_group_id=<id>` with the raw `.txt` as the body
   - **Cowork:** the connector's `import_chat` tool — paste the export text

Each line gets a **deterministic id** (`import-<sha1(timestamp|sender|text)>`), so:
- importing the **same** file twice changes nothing,
- an export that **overlaps** with messages already captured live won't double-count
  (the overlap is recognised as duplicates),
- only lines that parse to an amount become expenses/refunds; chatter and commands are skipped.

The importer returns counts: `{expenses, refunds, duplicates, skipped, messages}`.

## Reprocessing the event log (advanced)

`crud.unprocessed_events()` returns events that failed processing. A small reprocessing
job can iterate them and re-run the dispatcher — left as an extension (`webhook._process`
is already idempotent, so re-running is safe).

---

## Refunds

A refund is money coming back for an earlier purchase. It is stored as an **expense with
`is_refund=True` and a negative amount**, which makes everything net out automatically:

- the **source account is credited** (a negative debit increases its balance),
- **category spend and monthly totals go down** by the refund amount,
- the refund is **linked to the most recent matching expense** when one exists.

Ways to record one:

```
WhatsApp:  /refund 500 #shopping >hdfc returned shoes
           refund 500 #shopping >hdfc          (keyword form, no slash)
Cowork:    "refund 500 for shopping to HDFC"   (calls the log_refund tool)
Import:    a "refund …" line in the chat export
```

Example: you spent ₹2,000 on Shopping from HDFC, then refund ₹500 →
HDFC balance rises by ₹500 and Shopping spend shows a **net ₹1,500**.

### Refunds vs. income

Use a **refund** when money comes back for a *prior expense* (it nets against spend). Use
**income** (`/income`) for new money in (salary, etc.) — that adds to the account but does
**not** reduce any expense category.
