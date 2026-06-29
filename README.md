# 💰 TG Family Finance Tracker

**A free, private family finance tracker you run yourself — log money by chatting in a Telegram group, and see it all on a beautiful dashboard.**

[![CI](https://github.com/YOUR_USERNAME/tg-family-finance-tracker/actions/workflows/ci.yml/badge.svg)](https://github.com/YOUR_USERNAME/tg-family-finance-tracker/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-10b981.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-135%20passing-brightgreen.svg)](docs/TESTING.md)

> Your family already has a group chat. Add a friendly bot to it, type things like
> `Lunch 250 #food`, and the bot keeps the books — expenses, income, accounts, loans,
> budgets, investments and more — with a polished web dashboard for the whole household.

```
You (in the Telegram group):   Lunch 250 #food >hdfc
Bot:                           ✅ Logged INR 250.00 · Food · Lunch · from HDFC ****1234
```

---

## ✨ Why you'll like it

- **🆓 Free & private** — you run it on your own computer. Your money data never leaves your machine. No subscriptions, no ads, no third party.
- **💬 Dead simple to use** — the family just types in a normal Telegram group. No app to install on anyone's phone.
- **🔒 Family-only** — the bot only listens to your group and ignores everyone else.
- **📊 A real dashboard** — net worth, balances, budgets, charts, due-date reminders — filterable by week / month / quarter / year / custom range, with opening & closing balances.
- **🧰 Tracks everything** — expenses, income, bank & credit-card accounts, cash & assets, investments, insurance, loans (borrowed & lent), refunds, transfers, budgets, recurring bills.

## 👨‍👩‍👧‍👦 Who is this for?

Families (or roommates, or anyone) who want a **shared money tracker** without paying for an app or handing their finances to a company. Each household runs **its own copy** with **its own Telegram bot** — so your setup and your data are completely yours.

---

## 🚀 Get started

**Not technical?** Follow the friendly step-by-step guide — it assumes no coding knowledge:
👉 **[docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)** (about 15 minutes).

**Comfortable with a terminal?** One command sets everything up:

```bash
git clone https://github.com/YOUR_USERNAME/tg-family-finance-tracker.git
cd tg-family-finance-tracker
./run.sh                 # macOS / Linux / WSL / Git Bash   (Windows: .\run.ps1)
```

That installs everything, runs the tests, and starts the app at **http://localhost:8000**.
It works fully in **dry-run mode with no Telegram setup** — so you can explore the dashboard
immediately and connect the bot whenever you're ready.

### Connect your own Telegram bot (free, ~5 min)

Each family makes its **own** bot, so the token is private to you:

1. In Telegram, message **[@BotFather](https://t.me/BotFather)** → `/newbot` → copy the token.
2. In BotFather: `/setprivacy` → your bot → **Disable** (lets it read group messages).
3. Put the token in your `.env`: `TELEGRAM_BOT_TOKEN=...`
4. `./run.sh telegram`, add the bot to your family group, everyone sends `/start`.

Full walkthrough with the family-only lockdown: **[docs/TELEGRAM.md](docs/TELEGRAM.md)**.

---

## 📚 Documentation

| Guide | For | What's in it |
|---|---|---|
| [GETTING_STARTED.md](docs/GETTING_STARTED.md) | 🟢 Everyone | Plain-language setup from zero — install, bot, first expense |
| [USER_MANUAL.md](docs/USER_MANUAL.md) | 🟢 Everyone | How to use it day to day (with examples and an FAQ) |
| [TELEGRAM.md](docs/TELEGRAM.md) | 🟢 Everyone | Create the bot + make it family-only |
| [INSTALLATION.md](docs/INSTALLATION.md) | 🟡 Setup | Detailed install, env vars, deployment |
| [USAGE.md](docs/USAGE.md) | 🟡 Reference | Every command + the full HTTP API |
| [architecture.md](docs/architecture.md) | 🔵 Developers | How it's built |
| [SYNC.md](docs/SYNC.md) | 🔵 Developers | Offline behaviour & refunds |
| [TESTING.md](docs/TESTING.md) | 🔵 Developers | The test suite |
| [CONTRIBUTING.md](CONTRIBUTING.md) | 🔵 Developers | How to contribute |

## 🧱 Tech stack

Python 3.10+ · FastAPI · SQLAlchemy 2.0 · SQLite → PostgreSQL · Telegram Bot API (free,
long-polling — no hosting needed) · vanilla-JS dashboard. **135 passing tests.** Also ships
an optional WhatsApp Cloud API path and an MCP connector to drive it from Claude.

## 🤝 Contributing

Contributions are very welcome — bug fixes, new features, docs, translations. Start with
**[CONTRIBUTING.md](CONTRIBUTING.md)** and the
[good first issues](https://github.com/YOUR_USERNAME/tg-family-finance-tracker/issues).
Please also read our [Code of Conduct](CODE_OF_CONDUCT.md).

```bash
./run.sh test     # run the full test suite before opening a PR
```

## 🔐 Privacy & disclaimer

- It's **self-hosted**: nothing is sent anywhere except between your machine and your own
  Telegram bot. Keep your `.env` (which holds your bot token) private — it's gitignored.
- The dashboard is **unauthenticated on localhost** — fine for home use; don't expose port
  8000 to the open internet without adding authentication.
- This tool **only records** your finances. It never moves money. It is **not** financial
  advice. To report a security issue, see [SECURITY.md](SECURITY.md).

## 📄 License

[MIT](LICENSE) © 2026 Emmanuel Biju and contributors.

> 🔧 **After you create the GitHub repo:** replace `YOUR_USERNAME` in this README (badges
> and links) with your GitHub username or organisation.
