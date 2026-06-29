# 🟢 Getting Started — the easy, no-jargon guide

This guide assumes **no coding experience**. If you can copy-and-paste and follow steps,
you can set this up. It takes about **15 minutes**. Take it one step at a time. ☕

By the end you'll have:
- the app running on your computer,
- a private Telegram bot in your family group,
- a dashboard you can open in your browser.

> **What is this?** A money tracker for your family. Everyone types what they spend into a
> Telegram group (like `Lunch 250`), and the app keeps track and shows it on a dashboard.
> It runs on *your* computer — your data stays with you.

---

## Step 1 — Install Python (one-time)

Python is the free engine this app runs on. You only do this once.

- **Windows:** download from [python.org/downloads](https://www.python.org/downloads/),
  run the installer, and **tick the box that says "Add Python to PATH"** before clicking
  Install. ✅
- **Mac:** download from [python.org/downloads](https://www.python.org/downloads/) and run
  the installer. (That's the simplest way.)
- **Linux:** it's usually already installed.

> Not sure if you have it? That's fine — Step 4 will tell you clearly if something's missing.

## Step 2 — Download this project

If you don't use "git", the easiest way:

1. Go to the project's GitHub page.
2. Click the green **Code** button → **Download ZIP**.
3. **Unzip** it somewhere easy to find, like your **Documents** folder.

You'll now have a folder named `tg-family-finance-tracker`.

## Step 3 — Open a terminal in that folder

A "terminal" is just a text window where you type commands. Don't worry — you'll only paste
a couple.

- **Windows:** open the folder, then in the address bar type `cmd` and press Enter.
  (Or right-click the folder → "Open in Terminal".)
- **Mac:** open the **Terminal** app (press `Cmd+Space`, type "Terminal"), then type `cd `
  (with a space), **drag the folder into the window**, and press Enter.

## Step 4 — Start the app (one command)

Paste this and press Enter:

- **Mac / Linux:**
  ```bash
  ./run.sh
  ```
- **Windows:**
  ```powershell
  .\run.ps1
  ```

The first time, it sets everything up automatically (a minute or two). When it's ready
you'll see a line about **http://localhost:8000**.

> If it says **"Python not found,"** go back to Step 1 and reinstall Python (Windows: make
> sure you ticked "Add Python to PATH").

## Step 5 — Open the dashboard

Open your web browser and go to:

👉 **http://localhost:8000**

🎉 That's your dashboard! It's empty for now. Keep the terminal window **open** — closing it
stops the app.

---

## Step 6 — Create your family's Telegram bot (free)

A "bot" is an automated member of your group chat. You'll make your **own**, so it's private
to your family.

1. Open **Telegram** and search for **@BotFather** (the official bot for making bots).
   [Open it here](https://t.me/BotFather).
2. Send it the message: **`/newbot`**
3. It asks for a **name** (anything, e.g. "Our Family Money") and a **username** (must end
   in `bot`, e.g. `our_family_money_bot`).
4. BotFather replies with a long **token** that looks like
   `123456789:AAH...`. **Copy it** — this is your bot's password, keep it private.
5. Now send BotFather **`/setprivacy`**, choose your bot, and tap **Disable**. (This lets the
   bot read messages in your group.)

## Step 7 — Give the app your token

1. In the project folder, find the file named **`.env`** (it was created in Step 4).
   - Can't see it? It may be hidden. On Mac press `Cmd+Shift+.` in Finder to show hidden
     files; on Windows enable "Hidden items" in the View menu.
2. Open `.env` with any text editor (Notepad, TextEdit).
3. Find the line `TELEGRAM_BOT_TOKEN=` and paste your token right after the `=`, like:
   ```
   TELEGRAM_BOT_TOKEN=123456789:AAH...your token...
   ```
4. **Save** the file.

## Step 8 — Start the bot

Open a **second** terminal in the same folder (Step 3 again) and run:

- **Mac / Linux:** `./run.sh telegram`
- **Windows:** `.\run.ps1 telegram`

Leave this window open too. (So you have two windows running: the dashboard from Step 4, and
the bot now.)

## Step 9 — Add the bot to your family group

1. In Telegram, create a **group** with your family (or use an existing one).
2. Add your bot to the group (group settings → Add members → search your bot's username).
3. The bot will post a welcome message. 👋

## Step 10 — Lock it to your family (recommended)

So only your group can use your bot:

1. Look at the bot's terminal window — when someone sends a message it prints a line like
   `Telegram message in chat_id=-1001234567890`.
2. Copy that number (with the minus sign).
3. In `.env`, set: `TELEGRAM_ALLOWED_CHAT_IDS=-1001234567890`
4. Stop the bot (click its terminal and press `Ctrl+C`) and start it again
   (`./run.sh telegram`). Now it ignores everyone else.

---

## 🎉 You're done! Try it

In the group, each person sends **`/start`** once to set up their name and accounts. Then
just type expenses:

```
Lunch 250
coffee 80
groceries 1500 #groceries
uber 120
```

The bot replies confirming each one, and your **dashboard** (http://localhost:8000) updates
automatically. From here, the **[User Manual](USER_MANUAL.md)** shows everything you can do
(budgets, income, loans, reminders, and more).

---

## ❓ Common questions

**Do I have to keep the terminal windows open?**
Yes — they're the app running. Close them and it stops. (Tip: run it on a computer that's
usually on, like a home desktop.) When you reopen, just run `./run.sh` and `./run.sh telegram`
again.

**Is my money data sent anywhere?**
No. It stays in a file on your computer (`expenses.db`). The only thing that talks to the
internet is your own Telegram bot.

**Do all my family members need to install anything?**
No. Only the person hosting it does these steps. Everyone else just uses Telegram.

**Something went wrong / I see a red error.**
Copy the message and ask for help on the project's GitHub "Issues" page, or check
[INSTALLATION.md](INSTALLATION.md) for troubleshooting (e.g. the `DATABASE_URL` tip if you
see "disk I/O error").

**Can I use WhatsApp instead?**
Telegram is the recommended free path. WhatsApp is possible but needs a paid/approved
business account — see [INSTALLATION.md](INSTALLATION.md).
