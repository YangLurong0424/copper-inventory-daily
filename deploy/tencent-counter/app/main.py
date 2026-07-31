from __future__ import annotations

import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


APP_DIR = Path(os.environ.get("COUNTER_APP_DIR", "/opt/copper-counter"))
DB_PATH = Path(os.environ.get("COUNTER_DB_PATH", str(APP_DIR / "counter.db")))
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "COUNTER_ALLOWED_ORIGINS",
        "https://yanglurong0424.github.io,http://localhost:8000,http://127.0.0.1:8000",
    ).split(",")
    if origin.strip()
]
TZ = ZoneInfo("Asia/Shanghai")


class VisitPayload(BaseModel):
    site: str = Field(default="copper-inventory-daily")
    path: str = Field(default="/")
    date: str | None = None
    visitor_id: str


app = FastAPI(title="Copper Inventory Visit Counter", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["content-type"],
)


def safe_key(value: str, fallback: str = "default", limit: int = 120) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9._/-]+", "-", text)
    text = re.sub(r"-+", "-", text)[:limit].strip("-")
    return text or fallback


def today_key() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS counters (
            scope TEXT PRIMARY KEY,
            value INTEGER NOT NULL DEFAULT 0,
            updated_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS visitors (
            scope TEXT NOT NULL,
            visitor_id TEXT NOT NULL,
            first_seen INTEGER NOT NULL,
            PRIMARY KEY (scope, visitor_id)
        )
        """
    )
    conn.commit()
    return conn


def inc(conn: sqlite3.Connection, scope: str) -> None:
    now = int(time.time())
    conn.execute(
        """
        INSERT INTO counters(scope, value, updated_at)
        VALUES (?, 1, ?)
        ON CONFLICT(scope) DO UPDATE SET value = value + 1, updated_at = excluded.updated_at
        """,
        (scope, now),
    )


def add_visitor(conn: sqlite3.Connection, scope: str, visitor_id: str) -> bool:
    cur = conn.execute(
        "INSERT OR IGNORE INTO visitors(scope, visitor_id, first_seen) VALUES (?, ?, ?)",
        (scope, visitor_id, int(time.time())),
    )
    return cur.rowcount > 0


def get_counter(conn: sqlite3.Connection, scope: str) -> int:
    cur = conn.execute("SELECT value FROM counters WHERE scope = ?", (scope,))
    row = cur.fetchone()
    return int(row[0]) if row else 0


@app.get("/health")
def health() -> dict[str, str]:
    return {"ok": "true", "date": today_key()}


@app.post("/copper-counter")
async def copper_counter(payload: VisitPayload, request: Request) -> dict[str, int | str]:
    visitor_id = safe_key(payload.visitor_id, fallback="", limit=160)
    if len(visitor_id) < 8:
        return {
            "error": "missing_visitor_id",
            "today_pv": 0,
            "today_uv": 0,
            "total_pv": 0,
            "total_uv": 0,
            "date": today_key(),
        }

    site = safe_key(payload.site, "copper-inventory-daily")
    path = safe_key(payload.path, "/")
    date = today_key()

    site_scope = f"site:{site}"
    path_scope = f"{site_scope}:path:{path}"
    today_pv_key = f"{site_scope}:pv:{date}"
    total_pv_key = f"{site_scope}:pv:total"
    today_uv_key = f"{site_scope}:uv:{date}"
    total_uv_key = f"{site_scope}:uv:total"

    with connect() as conn:
        inc(conn, today_pv_key)
        inc(conn, total_pv_key)
        inc(conn, f"{path_scope}:pv:{date}")
        inc(conn, f"{path_scope}:pv:total")

        if add_visitor(conn, f"{site_scope}:visitor:{date}", visitor_id):
            inc(conn, today_uv_key)
        if add_visitor(conn, f"{site_scope}:visitor:total", visitor_id):
            inc(conn, total_uv_key)

        conn.commit()
        return {
            "today_pv": get_counter(conn, today_pv_key),
            "today_uv": get_counter(conn, today_uv_key),
            "total_pv": get_counter(conn, total_pv_key),
            "total_uv": get_counter(conn, total_uv_key),
            "date": date,
        }
