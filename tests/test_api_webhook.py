"""End-to-end: POST a webhook payload, then read it back through the API."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import webhook as webhook_module
from app.db import get_session
from app.main import app
from app.models import Base


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    # webhook.py calls SessionLocal() directly; API uses the get_session dependency.
    monkeypatch.setattr(webhook_module, "SessionLocal", TestingSession)
    # main.py bound init_db at import, so patch it there to skip the file-DB startup.
    monkeypatch.setattr("app.main.init_db", lambda: None)
    # Make tests independent of .env: pin the verify token and force DRY-RUN so the
    # webhook never makes a real outbound HTTP call (no token => send_text no-ops).
    from app.config import settings
    monkeypatch.setattr(settings, "whatsapp_verify_token", "test-verify-token")
    monkeypatch.setattr(settings, "whatsapp_access_token", "")
    app.dependency_overrides[get_session] = lambda: TestingSession()

    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _msg(text, mid, sender="user-1", group="group-1"):
    import time
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "id": mid, "from": sender, "type": "text",
                        "timestamp": str(int(time.time())), "group_id": group,
                        "text": {"body": text},
                    }]
                }
            }]
        }]
    }


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_webhook_verify(client):
    # Use the token the app is actually configured with (pinned in the fixture),
    # not a hardcoded guess — otherwise this fails whenever .env sets a real token.
    from app.config import settings
    r = client.get("/webhook", params={
        "hub.mode": "subscribe",
        "hub.verify_token": settings.whatsapp_verify_token,
        "hub.challenge": "42",
    })
    assert r.status_code == 200 and r.text == "42"


def test_webhook_verify_rejects_wrong_token(client):
    r = client.get("/webhook", params={
        "hub.mode": "subscribe", "hub.verify_token": "definitely-wrong", "hub.challenge": "42",
    })
    assert r.status_code == 403


def test_full_pipeline(client):
    # Two expenses come in via the group webhook.
    assert client.post("/webhook", json=_msg("Lunch 250 #food", "m1")).status_code == 200
    assert client.post("/webhook", json=_msg("uber 120", "m2")).status_code == 200
    # Re-delivery of m1 must not double-count.
    client.post("/webhook", json=_msg("Lunch 250 #food", "m1"))

    summary = client.get("/api/summary").json()
    assert summary["total_all_time"] == 370
    cats = {c["category"]: c["amount"] for c in summary["by_category"]}
    assert cats["Food"] == 250 and cats["Transport"] == 120

    rows = client.get("/api/expenses").json()
    assert len(rows) == 2

    csv = client.get("/api/expenses.csv")
    assert csv.status_code == 200 and "amount" in csv.text


def test_command_via_webhook(client):
    client.post("/webhook", json=_msg("Lunch 250 #food", "m1"))
    # A command shouldn't create an expense; pipeline should stay at 250.
    client.post("/webhook", json=_msg("/total", "m2"))
    assert client.get("/api/summary").json()["total_all_time"] == 250


def test_onboarding_and_account_debit_via_webhook(client):
    s = "u-anita"
    # Interactive onboarding, one message at a time.
    client.post("/webhook", json=_msg("/start", "o1", sender=s))
    client.post("/webhook", json=_msg("Anita", "o2", sender=s))
    client.post("/webhook", json=_msg("HDFC 1234", "o3", sender=s))
    client.post("/webhook", json=_msg("done", "o4", sender=s))

    accts = client.get("/api/accounts").json()
    assert len(accts) == 1 and accts[0]["bank_name"] == "HDFC"

    # Credit then debit the account via a command + an expense naming the source.
    client.post("/webhook", json=_msg("/income 50000 salary >hdfc", "o5", sender=s))
    client.post("/webhook", json=_msg("Groceries 2000 #food >hdfc", "o6", sender=s))

    bal = client.get("/api/accounts").json()[0]["balance"]
    assert bal == 48000  # 50000 credited - 2000 debited

    nw = client.get("/api/summary").json()["net_worth"]
    assert nw["cash_in_accounts"] == 48000


def _make_group(client):
    """Create a group by sending one webhook message; return its id."""
    client.post("/webhook", json=_msg("/start", "g0", sender="u-1"))
    return client.get("/api/groups").json()[0]["id"]


def test_manage_accounts_via_api(client):
    gid = _make_group(client)
    # Add a bank and a credit card.
    client.post("/api/accounts", json={"group_id": gid, "bank_name": "HDFC", "last4": "1234",
                                        "kind": "bank", "balance": 50000})
    r = client.post("/api/accounts", json={"group_id": gid, "bank_name": "HSBC", "last4": "9999",
                                           "kind": "credit_card", "balance": 12000})
    card_id = r.json()["id"]
    accts = {a["bank_name"]: a for a in client.get(f"/api/accounts?group_id={gid}").json()}
    assert accts["HDFC"]["balance"] == 50000
    assert accts["HSBC"]["balance"] == -12000          # owed stored negative

    # Update the bank balance, then delete the card.
    bank_id = accts["HDFC"]["id"]
    client.patch(f"/api/accounts/{bank_id}", json={"balance": 60000})
    client.delete(f"/api/accounts/{card_id}")
    accts = {a["bank_name"]: a for a in client.get(f"/api/accounts?group_id={gid}").json()}
    assert accts["HDFC"]["balance"] == 60000
    assert "HSBC" not in accts


def test_manage_investments_and_insurance_via_api(client):
    gid = _make_group(client)
    r = client.post("/api/investments", json={"group_id": gid, "name": "Axis Bluechip",
                                              "kind": "mf", "invested": 100000, "current": 118000})
    inv_id = r.json()["id"]
    invs = client.get(f"/api/investments?group_id={gid}").json()
    assert invs[0]["current_value"] == 118000 and invs[0]["gain"] == 18000
    client.patch(f"/api/investments/{inv_id}", json={"current_value": 125000})
    assert client.get(f"/api/investments?group_id={gid}").json()[0]["current_value"] == 125000

    client.post("/api/insurance", json={"group_id": gid, "name": "HDFC Ergo", "kind": "health",
                                        "premium": 24000, "due_date": "2099-09-15"})
    ins = client.get(f"/api/insurance?group_id={gid}").json()
    assert ins[0]["premium"] == 24000 and ins[0]["due_date"] == "2099-09-15"
    client.delete(f"/api/insurance/{ins[0]['id']}")
    assert client.get(f"/api/insurance?group_id={gid}").json() == []


def test_members_endpoint(client):
    gid = _make_group(client)
    client.post("/webhook", json=_msg("Anita", "n1", sender="u-1"))   # sets display name
    members = client.get(f"/api/members?group_id={gid}").json()
    assert any(m["name"] == "Anita" for m in members)


def test_transfers_and_loans_via_api(client):
    gid = _make_group(client)
    a = client.post("/api/accounts", json={"group_id": gid, "bank_name": "HDFC", "last4": "1",
                                           "kind": "bank", "balance": 10000}).json()["id"]
    b = client.post("/api/accounts", json={"group_id": gid, "bank_name": "ICICI", "last4": "2",
                                           "kind": "bank", "balance": 0}).json()["id"]
    client.post("/api/transfers", json={"group_id": gid, "from_account_id": a, "to_account_id": b,
                                        "amount": 4000})
    accts = {x["bank_name"]: x for x in client.get(f"/api/accounts?group_id={gid}").json()}
    assert accts["HDFC"]["balance"] == 6000 and accts["ICICI"]["balance"] == 4000

    ln = client.post("/api/loans", json={"group_id": gid, "direction": "lent",
                                         "counterparty": "Raju", "principal": 3000}).json()["id"]
    nw = client.get(f"/api/summary?group_id={gid}").json()["net_worth"]
    assert nw["lent_outstanding"] == 3000
    r = client.post(f"/api/loans/{ln}/payments", json={"amount": 1000}).json()
    assert r["outstanding"] == 2000
    assert client.get(f"/api/loans?group_id={gid}").json()[0]["outstanding"] == 2000


def test_budgets_and_recurring_via_api(client):
    import time
    gid = _make_group(client)
    client.post("/api/budgets", json={"group_id": gid, "category": "Food", "monthly_limit": 8000})
    # Log an expense dated *now* so it falls within this month's budget window.
    now_msg = _msg("lunch 500", "b1")
    now_msg["entry"][0]["changes"][0]["value"]["messages"][0]["timestamp"] = str(int(time.time()))
    client.post("/webhook", json=now_msg)
    b = client.get(f"/api/budgets?group_id={gid}").json()
    food = next(x for x in b if x["category"] == "Food")
    assert food["limit"] == 8000 and food["spent"] == 500

    r = client.post("/api/recurring", json={"group_id": gid, "flow": "expense", "label": "Rent",
                                            "amount": 15000, "day_of_month": 1}).json()
    recs = client.get(f"/api/recurring?group_id={gid}").json()
    assert recs[0]["label"] == "Rent" and recs[0]["amount"] == 15000
    client.delete(f"/api/recurring/{r['id']}?group_id={gid}")
    assert client.get(f"/api/recurring?group_id={gid}").json() == []
