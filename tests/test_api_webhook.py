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
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "id": mid, "from": sender, "type": "text",
                        "timestamp": "1750000000", "group_id": group,
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
