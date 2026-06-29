"""FastAPI entrypoint.  Run:  uvicorn app.main:app --reload

Routes:
  GET  /            -> dashboard (static HTML)
  GET  /health      -> health check
  GET  /webhook     -> Meta verification
  POST /webhook     -> incoming WhatsApp messages
  /api/*            -> read API (summary, expenses, CSV export)
"""
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router as api_router
from .config import settings
from .db import init_db
from .webhook import router as webhook_router

logging.basicConfig(level=settings.log_level)

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="TG Family Finance Tracker")
app.include_router(webhook_router)
app.include_router(api_router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
def _startup() -> None:
    init_db()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/")
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
