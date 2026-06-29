# Testing Guide

The project ships with **60 tests** covering parsing, persistence, reporting, commands,
the onboarding flow, account debit/credit, and the full HTTP pipeline. They run in under a
second against in-memory SQLite — no WhatsApp credentials or network needed.

## Running

```bash
pytest -q                       # all tests
pytest tests/test_parser.py     # one file
pytest -k settle                # tests matching a keyword
pytest -q -vv                   # verbose, shows each test
```

Expected: `60 passed`.

> If your environment's temp dir misbehaves, this repo's CI-safe invocation is:
> `pytest -q -o tmp_path_retention_policy=none -p no:cacheprovider`

## Layout

| File | Covers |
|---|---|
| `tests/conftest.py` | shared `db` fixture — a fresh in-memory SQLite session |
| `tests/test_parser.py` | amount/category/payer/account parsing, currencies, edge cases |
| `tests/test_crud_reports.py` | persistence, dedupe, totals, by-category/member, undo, month filter, settle-up |
| `tests/test_commands.py` | `/help`, `/total`, `/split`, `/undo`, unknown commands |
| `tests/test_finance.py` | onboarding flow, account balance debit/credit, income, investments, insurance, net worth |
| `tests/test_edge_cases.py` | multi-hint parsing, 3-way settle, credit-card balance, account scoping, income dedupe, overdue insurance, webhook payload flattening |
| `tests/test_api_webhook.py` | end-to-end via FastAPI `TestClient`: verify handshake, webhook → DB → API, CSV, onboarding + account debit |

## How the test DB works

- **Unit tests** use the `db` fixture (`conftest.py`): a per-test in-memory SQLite session
  with tables created fresh, so tests are isolated and order-independent.
- **API/webhook tests** (`test_api_webhook.py`) spin up the real FastAPI app with a
  `TestClient`, backed by a shared in-memory engine (`StaticPool`). They monkeypatch
  `webhook.SessionLocal` and override the `get_session` dependency so both the webhook
  (which uses `SessionLocal()` directly) and the API (which uses the dependency) hit the
  same in-memory database. Startup `init_db` is patched to a no-op so the file DB is never
  touched.

## What good coverage looks like here

The highest-value, most fragile logic is the **parser** and the **account
debit/credit/balance** math — both are exercised heavily, including the regression test
for the 4-digit-amount bug (`2000` must not parse as `200`). When changing those, add a
test first.

## Adding a test

```python
def test_my_case(db):                 # `db` fixture = in-memory session
    g = crud.get_or_create_group(db, "g1")
    m = crud.get_or_create_member(db, g, "u1", "Ravi")
    # ... arrange, act, assert
```

For an end-to-end behaviour, add to `test_api_webhook.py` and drive it by POSTing webhook
payloads with the `_msg(...)` helper.
