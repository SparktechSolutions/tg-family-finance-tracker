"""Family Finance MCP connector for Claude Cowork.

Exposes the finance tracker's actions and reports as MCP tools, reusing the existing core
and the SAME database as the WhatsApp bot. Run it as a local (stdio) MCP server and point
Cowork / Claude Desktop at it — see connector/README.md.

    python -m connector.server      # from the project root

Tools are thin wrappers over connector.core_ops (which is unit-tested).
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from connector import core_ops

mcp = FastMCP("Family Finance")


@mcp.tool()
def log_expense(amount: float, category: str = "Uncategorized", note: str = "",
                account: str = "", payer: str = "") -> dict:
    """Log a household expense.

    Args:
        amount: how much was spent.
        category: e.g. Food, Transport, Bills (free text).
        note: short description, e.g. "lunch with team".
        account: source account to debit, by bank name or last-4 (e.g. "HDFC" or "1234").
        payer: who paid; defaults to you.
    """
    return core_ops.log_expense(amount=amount, category=category, note=note or None,
                                account=account or None, payer=payer or None)


@mcp.tool()
def log_expense_text(text: str) -> dict:
    """Log an expense from a freeform sentence (e.g. "Lunch 250 #food >hdfc").
    Useful when you'd rather paste the same shorthand used in the WhatsApp group."""
    return core_ops.log_expense(text=text)


@mcp.tool()
def log_refund(amount: float, category: str = "", note: str = "", account: str = "") -> dict:
    """Record a refund (money back for a prior expense). Credits the account and reduces
    net spend for the category; links to the latest matching expense when possible."""
    return core_ops.log_refund(amount=amount, category=category or None,
                               note=note or None, account=account or None)


@mcp.tool()
def import_chat(text: str, currency: str = "INR") -> dict:
    """Backfill from a pasted WhatsApp chat export (.txt contents). Used to catch up after
    the connector/server was offline. Re-imports are idempotent (no double-counting)."""
    from app.importer import import_chat_text
    res = import_chat_text(text, wa_group_id=core_ops.GROUP_ID, currency=currency)
    return {"expenses": res.expenses, "refunds": res.refunds,
            "duplicates": res.duplicates, "skipped": res.skipped, "messages": res.lines}


@mcp.tool()
def add_income(amount: float, source: str = "Income", account: str = "") -> dict:
    """Record income such as salary. Credits `account` (bank name or last-4) if given."""
    return core_ops.add_income(amount=amount, source=source, account=account or None)


@mcp.tool()
def add_account(bank_name: str, last4: str, kind: str = "bank", balance: float = 0) -> dict:
    """Add a bank account or credit card. kind = "bank" or "credit_card". Only the bank name
    and last 4 digits are stored. `balance` = current cash (bank) or amount owed (card)."""
    return core_ops.add_account(bank_name=bank_name, last4=last4, kind=kind, balance=balance)


@mcp.tool()
def set_account_balance(account: str, balance: float) -> dict:
    """Set an account's current balance (bank = cash on hand; credit card = amount owed).
    Identify the account by bank name or last-4."""
    return core_ops.set_account_balance(account=account, balance=balance)


@mcp.tool()
def list_accounts() -> dict:
    """List all accounts with their current balances."""
    return core_ops.list_accounts()


@mcp.tool()
def transfer(from_account: str, to_account: str, amount: float) -> dict:
    """Move money between two of your own accounts (by bank name or last-4)."""
    return core_ops.transfer(from_account=from_account, to_account=to_account, amount=amount)


@mcp.tool()
def lend(amount: float, friend: str, account: str = "") -> dict:
    """Record money you lent to a friend (they owe you). Optionally from an account."""
    return core_ops.lend(amount=amount, friend=friend, account=account or None)


@mcp.tool()
def borrow(amount: float, lender: str, account: str = "") -> dict:
    """Record money you borrowed (you owe it). Optionally received into an account."""
    return core_ops.borrow(amount=amount, lender=lender, account=account or None)


@mcp.tool()
def loan_payment(counterparty: str, amount: float, direction: str = "borrowed",
                 account: str = "") -> dict:
    """Record a loan payment. direction='borrowed' = you repay a loan;
    'lent' = a friend repays you."""
    return core_ops.loan_payment(counterparty=counterparty, amount=amount,
                                 direction=direction, account=account or None)


@mcp.tool()
def list_loans() -> dict:
    """List loans — money you owe and money owed to you — with outstanding balances."""
    return core_ops.list_loans()


@mcp.tool()
def set_budget(category: str, monthly_limit: float) -> dict:
    """Set a monthly spending limit for a category."""
    return core_ops.set_budget(category=category, monthly_limit=monthly_limit)


@mcp.tool()
def budget_status() -> dict:
    """This month's spend vs limit for each budgeted category."""
    return core_ops.budget_status()


@mcp.tool()
def add_recurring(flow: str, label: str, amount: float, day_of_month: int,
                  category: str = "", account: str = "") -> dict:
    """Add a recurring item (flow='expense'|'income') due on a given day each month —
    rent, EMI, subscription, salary, etc."""
    return core_ops.add_recurring(flow=flow, label=label, amount=amount,
                                  day_of_month=day_of_month, category=category or None,
                                  account=account or None)


@mcp.tool()
def list_recurring() -> dict:
    """List recurring items with their next due dates."""
    return core_ops.list_recurring()


@mcp.tool()
def reminders() -> dict:
    """What's due in the next 7 days (recurring items + insurance premiums)."""
    return core_ops.reminders()


@mcp.tool()
def add_investment(name: str, kind: str = "other", invested: float = 0,
                   current: float = 0) -> dict:
    """Add an investment holding (kind: stocks, mf, fd, crypto, gold, etc.).
    If `current` is 0 it defaults to `invested`."""
    return core_ops.add_investment(name=name, kind=kind, invested=invested,
                                   current=current or None)


@mcp.tool()
def update_investment(name: str, value: float) -> dict:
    """Update a holding's current market value (passive update)."""
    return core_ops.update_investment(name=name, value=value)


@mcp.tool()
def list_investments() -> dict:
    """List investments with current value and gain/loss."""
    return core_ops.list_investments()


@mcp.tool()
def add_insurance(name: str, kind: str = "other", premium: float = 0,
                  due_date: str = "", frequency: str = "yearly") -> dict:
    """Add an insurance policy. due_date is YYYY-MM-DD; frequency monthly|quarterly|yearly."""
    return core_ops.add_insurance(name=name, kind=kind, premium=premium,
                                  due_date=due_date or None, frequency=frequency)


@mcp.tool()
def upcoming_premiums() -> dict:
    """List insurance policies with days until each premium is due."""
    return core_ops.upcoming_premiums()


@mcp.tool()
def net_worth() -> dict:
    """Household net worth: cash across accounts + total investment value."""
    return core_ops.net_worth()


@mcp.tool()
def monthly_summary() -> dict:
    """This month's income, expenses, net, and a spend-by-category breakdown."""
    return core_ops.monthly_summary()


@mcp.tool()
def settle_up() -> dict:
    """Equal-split 'who owes whom' across the household."""
    return core_ops.settle_up()


@mcp.tool()
def recent_expenses(limit: int = 20) -> dict:
    """Most recent expenses."""
    return core_ops.recent_expenses(limit=limit)


def main() -> None:
    # Ensure tables exist before serving (dev convenience; use Alembic in production).
    import os
    from app.db import init_db
    init_db()

    # Transport is chosen by env so the SAME server works two ways:
    #   • stdio (default) — for clients that launch a local command.
    #   • sse / streamable-http — exposes a URL for clients that only accept a
    #     "Remote MCP server URL" (e.g. Cowork's Add-custom-connector dialog).
    transport = os.environ.get("FINANCE_MCP_TRANSPORT", "stdio").lower()
    if transport in ("sse", "http", "streamable-http", "streamable_http"):
        mcp.settings.host = os.environ.get("FINANCE_MCP_HOST", "127.0.0.1")
        mcp.settings.port = int(os.environ.get("FINANCE_MCP_PORT", "8765"))
        kind = "streamable-http" if transport.startswith("stream") or transport == "http" else "sse"
        # Optional secret token, embedded in the URL path so an unguessable prefix gates
        # every route (works even when the client only accepts a bare URL — no header field
        # needed). Without the token in the path the server simply 404s.
        token = (os.environ.get("FINANCE_MCP_TOKEN") or "").strip().strip("/")
        prefix = f"/{token}" if token else ""
        if kind == "streamable-http":
            mcp.settings.streamable_http_path = f"{prefix}/mcp"
            path = mcp.settings.streamable_http_path
        else:
            mcp.settings.sse_path = f"{prefix}/sse"
            mcp.settings.message_path = f"{prefix}/messages/"
            path = mcp.settings.sse_path
        print(f"Family Finance MCP serving over {kind} at "
              f"http://{mcp.settings.host}:{mcp.settings.port}{path}"
              + ("  (secret token required in path)" if token else ""))
        mcp.run(transport=kind)
    else:
        mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
