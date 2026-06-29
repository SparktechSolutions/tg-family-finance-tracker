# User Manual

A complete, friendly guide to using the **TG Family Finance Tracker** — for the
person running it and for the family members typing in the group. For deeper API/command
detail see [USAGE.md](USAGE.md); for setup see [INSTALLATION.md](INSTALLATION.md).

---

## 1. What it does for your family

Your family already has a WhatsApp group. Add the bot to it and you get a shared money
tracker that needs no app to install on anyone's phone:

- **Expenses** — "Lunch 250 #food" and it's logged.
- **Income** — record salary and other money coming in.
- **Accounts** — each person's banks and credit cards (only bank name + last 4 stored).
- **Investments** — track holdings and update their value over time.
- **Insurance** — premiums and due dates, with reminders of what's coming up.
- **Net worth** — a combined household picture, on demand and on a dashboard.
- **Refunds** — money back nets against spending and returns to your account.

There are three ways to use it: the **WhatsApp group** (everyone), a **web dashboard**
(viewing), and **Claude Cowork** (chat-driven, optional).

---

## 2. First-time setup (the person hosting it)

1. Install and start it with one command (see [INSTALLATION.md](INSTALLATION.md)):
   ```bash
   ./run.sh
   ```
2. Connect a WhatsApp Business number and add it to your family group (Meta setup steps in
   INSTALLATION.md). Until then it runs in **dry-run** mode for testing — it logs what it
   *would* reply instead of sending.
3. Open the dashboard at **http://localhost:8000/**.

---

## 3. Joining (each family member)

When the bot is added, it welcomes the group. Each person sets themselves up once:

```
You:  /start
Bot:  👋 What's your name?
You:  Anita
Bot:  Now add your accounts, one per message…
You:  HDFC 1234
You:  ICICI credit 5678
You:  done
```

- Bank: `<Bank> <last4>` → `HDFC 1234`
- Credit card: `<Bank> credit <last4>` → `ICICI credit 5678`
- Type **done** when finished (or **skip**). Re-run `/start` anytime to add more.
- Privacy: only the bank name and last 4 digits are ever stored.

---

## 4. Everyday use — quick recipes

**Log an expense**
```
Lunch 250 #food                  → ₹250, Food
uber 120                         → ₹120, Transport (guessed from the word)
₹1,500 groceries @ravi >hdfc     → ₹1500, paid by Ravi, from HDFC
```
- `#category` sets the category; otherwise it's guessed from keywords.
- `@name` records who paid (defaults to you).
- `>bank` (name or last-4) debits that account.

**Record income**
```
/income 50000 salary >hdfc       → ₹50,000 salary into HDFC
```

**Record a refund (money back)**
```
/refund 500 #shopping >hdfc returned shoes
refund 500 #shopping >hdfc       → same thing, no slash
```
It credits the account and reduces your Shopping spend.

**Track investments**
```
/invest add mf 100000 Axis Bluechip   → add a holding
/invest update Axis Bluechip 118000   → update its value later
/investments                          → see all with gain/loss
```

**Track insurance**
```
/insurance add health 24000 2026-09-15 HDFC Ergo Family
/due                                   → what's due and when
```

**See where you stand**
```
/total            this month's income, expenses, net
/total food       this month's spend on Food
/month june       June's category breakdown
/accounts         balances of every account
/networth         cash + investments = household net worth
/split            who owes whom (equal split)
/undo             remove your last expense
/help             the full cheat-sheet
```

---

## 5. The dashboard

Open **http://localhost:8000/**. It shows, per group:

- Net worth, cash in accounts, investments value, income & expenses this month
- Charts: spending by category and by person
- Accounts with live balances; investments with gain/loss
- Insurance with colour-coded due dates (overdue / due soon)
- Settle-up and a recent-expenses table
- An **Export CSV** button

Press **Reload** to refresh. Everything updates as the family types in the group.

---

## 6. Using it from Claude Cowork (optional)

If you set up the connector ([connector/README.md](../connector/README.md)), you can just
chat with Claude:

> "Log 250 for lunch from HDFC." · "Record my 90,000 salary into HDFC." ·
> "What's our net worth?" · "What premiums are due?" · "Refund 500 for shopping."

There's also a live dashboard you can open inside Cowork. It uses the **same data** as the
WhatsApp group — one shared ledger.

---

## 7. If the bot was offline

Short outages are handled automatically (nothing is double-counted). For a longer outage,
back-fill from a WhatsApp chat export:

1. In WhatsApp: group → **Export chat → Without media**.
2. Import it: `./run.sh import chat.txt <your-group-id>` (or `POST /api/import/chat`).

Re-importing is safe — already-recorded items are skipped. Details in [SYNC.md](SYNC.md).

---

## 8. FAQ

**Do family members need to install anything?** No — they just use WhatsApp.

**Is my account number safe?** Only the bank name and last 4 digits are stored. No full
numbers, no passwords, no payment credentials.

**What if I make a typo?** Send `/undo` to remove your last expense, or just log a
correcting entry. Every original message is stored, so nothing is lost.

**Can two people have the same bank?** Yes. Accounts are per person; the bot disambiguates
by owner and last-4.

**Does it move money or pay bills?** No. It only *records* your finances — it never makes
payments or transfers.

**Refund vs income?** Use a **refund** when money comes back for a past purchase (it
reduces that spending). Use **income** for new money like salary (it doesn't reduce any
expense).

**Why didn't my message get logged?** A message with no amount is treated as normal chat
and ignored. Make sure there's a number, e.g. `coffee 80`.

---

## 9. Getting help

- Full command + API reference: [USAGE.md](USAGE.md)
- Install & WhatsApp connection: [INSTALLATION.md](INSTALLATION.md)
- How it works under the hood: [ARCHITECTURE.md](ARCHITECTURE.md)
- Offline sync & refunds: [SYNC.md](SYNC.md)
