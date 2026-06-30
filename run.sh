#!/usr/bin/env bash
#
# run.sh — one script to set up, install, test, and run the TG Family Finance Tracker
# on any local machine (macOS / Linux / WSL / Git Bash).
#
# Usage:
#   ./run.sh                 full flow: setup -> test -> start the app
#   ./run.sh setup           create venv, install deps, create .env
#   ./run.sh start           run the web app + dashboard (sets up first if needed)
#   ./run.sh test            run the test suite
#   ./run.sh connector       set up the Cowork MCP connector (separate venv) + print config
#   ./run.sh telegram        run the Telegram bot (free, real-time; needs TELEGRAM_BOT_TOKEN)
#   ./run.sh import <file>   backfill from a WhatsApp chat export (.txt)
#   ./run.sh doctor          check your environment (python, ports)
#   ./run.sh clean           remove the virtualenvs
#   ./run.sh help            show this help
#
set -euo pipefail

# ----- pretty output ----------------------------------------------------------
if [ -t 1 ]; then
  B="\033[1m"; G="\033[32m"; Y="\033[33m"; R="\033[31m"; C="\033[36m"; N="\033[0m"
else B=""; G=""; Y=""; R=""; C=""; N=""; fi
info()  { printf "${C}▸${N} %s\n" "$*"; }
ok()    { printf "${G}✓${N} %s\n" "$*"; }
warn()  { printf "${Y}!${N} %s\n" "$*"; }
err()   { printf "${R}✗${N} %s\n" "$*" >&2; }
die()   { err "$*"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV=".venv"
VENV_CONNECTOR=".venv-connector"
PORT="${PORT:-8000}"

# ----- python detection -------------------------------------------------------
find_python() {
  for c in python3.12 python3.11 python3.10 python3 python; do
    if command -v "$c" >/dev/null 2>&1; then
      if "$c" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,10) else 1)' 2>/dev/null; then
        echo "$c"; return 0
      fi
    fi
  done
  return 1
}

ensure_python() {
  PY="$(find_python)" || die "Python 3.10+ not found. Install it from https://www.python.org/downloads/ and re-run."
  ok "Using $("$PY" --version 2>&1) ($PY)"
}

venv_py() { echo "$SCRIPT_DIR/$VENV/bin/python"; }

# ----- commands ---------------------------------------------------------------
cmd_doctor() {
  ensure_python
  if command -v lsof >/dev/null 2>&1 && lsof -i ":$PORT" >/dev/null 2>&1; then
    warn "Port $PORT is already in use — set PORT=8001 ./run.sh start to change it."
  else ok "Port $PORT is free"; fi
  [ -f .env ] && ok ".env present" || warn ".env not yet created (run ./run.sh setup)"
}

cmd_setup() {
  ensure_python
  if [ ! -d "$VENV" ]; then
    info "Creating virtualenv ($VENV)…"
    "$PY" -m venv "$VENV"
  fi
  info "Installing dependencies…"
  "$(venv_py)" -m pip install --quiet --upgrade pip
  "$(venv_py)" -m pip install --quiet -r requirements.txt
  if [ ! -f .env ]; then
    cp .env.example .env
    ok "Created .env (dry-run mode — no WhatsApp credentials needed to start)"
  else
    ok ".env already exists (left untouched)"
  fi
  ok "Setup complete."
}

need_setup() { [ -x "$(venv_py)" ] || cmd_setup; }

cmd_test() {
  need_setup
  info "Running test suite…"
  "$(venv_py)" -m pip install --quiet pytest
  "$(venv_py)" -m pytest -q
  ok "Tests passed."
}

cmd_start() {
  need_setup
  info "Starting the app on http://localhost:$PORT  (Ctrl-C to stop)"
  info "Dashboard: http://localhost:$PORT/   ·   API docs: http://localhost:$PORT/docs"
  exec "$(venv_py)" -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --reload
}

cmd_import() {
  need_setup
  [ $# -ge 1 ] || die "Usage: ./run.sh import <chat-export.txt> [wa_group_id]"
  local file="$1"; local group="${2:-cowork-household}"
  [ -f "$file" ] || die "File not found: $file"
  info "Importing $file into group '$group'…"
  "$(venv_py)" -m app.importer "$file" --group "$group"
}

cmd_telegram() {
  need_setup
  info "Starting the Telegram bot (long polling — no public URL needed)."
  info "Needs TELEGRAM_BOT_TOKEN in .env. See docs/TELEGRAM.md to create one."
  exec "$(venv_py)" -m app.telegram_bot
}

cmd_connector() {
  ensure_python
  if [ ! -d "$VENV_CONNECTOR" ]; then
    info "Creating connector virtualenv ($VENV_CONNECTOR)…"
    "$PY" -m venv "$VENV_CONNECTOR"
  fi
  info "Installing connector dependencies…"
  "$SCRIPT_DIR/$VENV_CONNECTOR/bin/python" -m pip install --quiet --upgrade pip
  "$SCRIPT_DIR/$VENV_CONNECTOR/bin/python" -m pip install --quiet -r connector/requirements.txt
  ok "Connector ready. Add this to your Claude/Cowork MCP config:"
  cat <<JSON

  {
    "mcpServers": {
      "family-finance": {
        "command": "$SCRIPT_DIR/$VENV_CONNECTOR/bin/python",
        "args": ["-m", "connector.server"],
        "cwd": "$SCRIPT_DIR",
        "env": {
          "DATABASE_URL": "sqlite:///$SCRIPT_DIR/expenses.db",
          "FINANCE_GROUP_ID": "cowork-household",
          "FINANCE_MEMBER": "You"
        }
      }
    }
  }

JSON
  info "Point DATABASE_URL at the same DB as the web app to share one ledger."
}

cmd_connector_serve() {
  # Run the connector as a local HTTP (SSE) MCP server so clients that only accept a
  # "Remote MCP server URL" (e.g. Cowork's Add-custom-connector dialog) can use it.
  ensure_python
  if [ ! -d "$VENV_CONNECTOR" ]; then
    info "Creating connector virtualenv ($VENV_CONNECTOR)…"
    "$PY" -m venv "$VENV_CONNECTOR"
    "$SCRIPT_DIR/$VENV_CONNECTOR/bin/python" -m pip install --quiet --upgrade pip
    "$SCRIPT_DIR/$VENV_CONNECTOR/bin/python" -m pip install --quiet -r connector/requirements.txt
  fi
  export DATABASE_URL="${DATABASE_URL:-sqlite:///$SCRIPT_DIR/expenses.db}"
  export FINANCE_GROUP_ID="${FINANCE_GROUP_ID:-cowork-household}"
  export FINANCE_MEMBER="${FINANCE_MEMBER:-You}"
  export FINANCE_MCP_TRANSPORT="${FINANCE_MCP_TRANSPORT:-sse}"
  export FINANCE_MCP_HOST="${FINANCE_MCP_HOST:-127.0.0.1}"
  export FINANCE_MCP_PORT="${FINANCE_MCP_PORT:-8765}"
  ok "Serving the Family Finance connector over HTTP."
  info "In Cowork → Add custom connector, paste this Remote MCP server URL:"
  printf "\n    http://localhost:%s/sse\n\n" "$FINANCE_MCP_PORT"
  info "Sharing DB: $DATABASE_URL  ·  household: $FINANCE_GROUP_ID"
  info "Keep this terminal open while you use the connector. Ctrl-C to stop."
  exec "$SCRIPT_DIR/$VENV_CONNECTOR/bin/python" -m connector.server
}

cmd_clean() {
  rm -rf "$VENV" "$VENV_CONNECTOR"
  ok "Removed virtualenvs."
}

cmd_help() { sed -n '3,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

# ----- dispatch ---------------------------------------------------------------
case "${1:-all}" in
  all)        cmd_setup; cmd_test; cmd_start ;;
  setup)      cmd_setup ;;
  start|run)  cmd_start ;;
  test)       cmd_test ;;
  connector)  cmd_connector ;;
  connector-serve|serve-connector) cmd_connector_serve ;;
  telegram)   cmd_telegram ;;
  import)     shift; cmd_import "$@" ;;
  doctor)     cmd_doctor ;;
  clean)      cmd_clean ;;
  help|-h|--help) cmd_help ;;
  *) die "Unknown command: $1  (try ./run.sh help)" ;;
esac
