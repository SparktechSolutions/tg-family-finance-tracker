# Security Policy

This project handles personal financial data, so we take security seriously — even though it
is **self-hosted** (each user runs their own copy and holds their own data).

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Instead, email **emmanuelbiju4@gmail.com** with:

- a description of the issue and its impact,
- steps to reproduce (proof-of-concept if possible),
- any suggested fix.

You'll get an acknowledgement as soon as possible, and we'll work with you on a fix and
coordinated disclosure. Thank you for helping keep families' data safe. 🙏

## Scope & good-to-know

This is a self-hosted app. A few things to keep in mind when running it:

- **Your `.env` holds your Telegram bot token.** Keep it private; it's gitignored by default.
- **The dashboard and `/api/*` are unauthenticated on `localhost`.** That's fine for home
  use, but **do not expose port 8000 to the public internet** without adding authentication
  and HTTPS in front of it.
- **Lock the bot to your family** by setting `TELEGRAM_ALLOWED_CHAT_IDS` (see
  [docs/TELEGRAM.md](docs/TELEGRAM.md)). Telegram bots are reachable by anyone who knows the
  username, so the allowlist is what makes yours private.
- **The app only records data — it never moves money.**

## Supported versions

This is an evolving community project; security fixes target the latest `main`. Please run a
recent version.
