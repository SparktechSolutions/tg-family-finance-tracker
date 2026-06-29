# Telegram Setup (free, no Meta, real-time)

A completely free way to run the family finance tracker — official Telegram Bot API, no
business account, no ban risk, and **no public URL/hosting** (it uses long polling, so it
runs right on your machine). The family types in a **Telegram group** instead of WhatsApp;
everything else (parser, commands, onboarding, refunds, dashboard, Cowork connector) works
exactly the same.

---

## 1. Create the bot (2 minutes)

1. In Telegram, open a chat with **[@BotFather](https://t.me/BotFather)**.
2. Send `/newbot`, then follow the prompts to pick a name and a username (must end in
   `bot`, e.g. `our_family_finance_bot`).
3. BotFather replies with a **token** like `123456789:AAH...`. Copy it.

## 2. Let the bot read group messages (important)

By default Telegram bots only see messages that mention them. To read **all** group
messages (so plain `Lunch 250 #food` works), disable privacy mode:

1. In @BotFather, send `/setprivacy`.
2. Choose your bot.
3. Select **Disable**.

## 3. Configure the project

Put the token in `.env`:

```
TELEGRAM_BOT_TOKEN=123456789:AAH...your-token...
```

## 4. Run it

```bash
./run.sh telegram          # macOS/Linux/WSL/Git Bash
# or:  python -m app.telegram_bot
```

You'll see "Telegram bot started (long polling)". Leave it running (it polls continuously).
No ngrok, no webhook, no server needed.

## 5. Use it

1. Create a Telegram **group** for the family and **add your bot** to it. The bot posts a
   welcome message.
2. Each member sends **`/start`** to set up their name + accounts (same onboarding as the
   WhatsApp version).
3. Log money normally:
   ```
   Lunch 250 #food >hdfc
   /income 50000 salary >hdfc
   /refund 500 #shopping >hdfc
   /networth     /total     /due     /help
   ```
4. View everything on the dashboard: run `./run.sh start` (separately) and open
   <http://localhost:8000/>. The dashboard reads the same database the bot writes to.

> Tip: run the bot and the dashboard in two terminals, both pointing at the same
> `DATABASE_URL` (the default `sqlite:///./expenses.db` already does this).

---

## Make it family-only (important)

Telegram bots are **publicly reachable by their @username** — anyone who discovers it could
message it or add it to their own group. Telegram has no built-in "invite-only" for bots,
so the project enforces it **server-side with an allowlist**: the bot only responds in chat
IDs you approve and silently ignores everyone else (their messages never touch your data).

To lock it to your family group:

1. Start the bot once with `TELEGRAM_ALLOWED_CHAT_IDS` empty and add it to your family
   group (or message it). In the bot's console you'll see a line like:
   `Telegram message in chat_id=-1001234567890`. That negative number is your group's
   chat ID. (You can also add **@RawDataBot** to the group briefly to read the id.)
2. Put it in `.env`:
   `TELEGRAM_ALLOWED_CHAT_IDS=-1001234567890`
   (Comma-separate multiple chats, e.g. group + your DM: `-1001234567890, 12345678`.)
3. Restart the bot. On startup it prints `Locked to chat IDs: [...]`. Now only your family
   group works; anyone else is ignored.

Extra hardening (optional):
- In **@BotFather -> /setjoingroups -> Disable** so the bot can't be added to new groups.
- Don't share the bot's @username publicly; keep the bot token secret.

> Until you set `TELEGRAM_ALLOWED_CHAT_IDS`, the bot logs a startup warning that it's open.
> Data from different chats is always kept separate, but set the allowlist so only your
> family can use your running bot at all.

## How it works

- The bot long-polls Telegram's `getUpdates`. Each message maps to the same internal shape
  as a WhatsApp message and is routed through `app.ingest.handle_text` — the shared
  dispatcher (onboarding → command → refund → expense).
- **Group** = Telegram chat id (`tg:<chat_id>`); **member** = Telegram user id, with the
  display name taken from the user's Telegram name.
- Each message gets a unique id (`tg-<chat>-<message_id>`) used for idempotency, so nothing
  is double-counted, and it's recorded in the same durable `inbound_events` log.

## Costs & limits

- **Free.** Telegram's Bot API has no usage charges.
- Runs on any always-on machine (your laptop, a Raspberry Pi, a free-tier VM). If the
  machine sleeps, the bot catches up on the backlog when it resumes (Telegram queues
  updates for ~24h).
- No business verification, no Meta account, no phone-number ban risk.

## Switching from / keeping WhatsApp

The WhatsApp webhook and the Telegram bot share the same core and can even run side by side
against the same database. You don't lose anything by starting with Telegram — you can add
WhatsApp later if you ever get an unrestricted Meta business account.
