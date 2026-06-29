# Contributing

Thanks for your interest in improving the TG Family Finance Tracker! 🎉 Contributions of all
kinds are welcome — bug reports, fixes, new features, documentation, and translations.

## Ways to contribute

- **🐛 Found a bug?** Open an issue using the bug-report template.
- **💡 Have an idea?** Open a feature-request issue to discuss it first.
- **📝 Docs** — even fixing a typo helps. The non-technical guides
  (`docs/GETTING_STARTED.md`, `docs/USER_MANUAL.md`) especially benefit from a fresh pair of
  eyes.
- **🌍 Translations** — the category keywords and bot messages can be localised.

## Development setup

```bash
git clone https://github.com/YOUR_USERNAME/tg-family-finance-tracker.git
cd tg-family-finance-tracker
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest -q                                            # should be: 135 passed, 1 skipped
```

`./run.sh` is a convenience wrapper (`setup`, `test`, `start`, `telegram`, `connector`,
`import`). You don't need a Telegram bot to develop — the app runs in dry-run and the tests
use an in-memory database.

## Project layout

```
app/         FastAPI app + bot + core logic (parser, crud, reports, commands, ingest…)
connector/   Optional Claude/Cowork MCP connector (separate venv; uses the app core)
docs/        User and developer documentation
tests/       pytest suite (135 tests)
run.sh       one-command CLI
```

See [docs/architecture.md](docs/architecture.md) for how it all fits together, and
[docs/TESTING.md](docs/TESTING.md) for the test layout.

## Guidelines

- **Keep `app/parser.py` dependency-free and unit-tested** — it's the core and the easiest
  to break.
- **Add a test** for any behaviour you change. We aim to keep the suite green.
- **Run `pytest -q` before opening a PR.** CI runs it on Python 3.10–3.12.
- **Schema changes:** add new columns/tables to `app/models.py`; the lightweight
  `db._auto_migrate` adds missing columns on startup so existing databases keep working. For
  anything beyond simple column adds, discuss in an issue first.
- **Style:** clear, readable Python; type hints where helpful; small, focused functions.
  No formatter is enforced, but match the surrounding style.
- **Privacy first:** never log or expose full account numbers or secrets. Accounts store
  only a bank name + last 4 digits by design.

## Pull request process

1. Fork the repo and create a branch: `git checkout -b feature/short-description`.
2. Make your change **with tests**.
3. Run `./run.sh test` (or `pytest -q`) — all green.
4. Open a PR using the template; describe **what** and **why**, and link any issue.
5. A maintainer will review. Be patient and kind — this is a community project. 💚

## Code of Conduct

By participating you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## License

By contributing, you agree that your contributions will be licensed under the project's
[MIT License](LICENSE).
