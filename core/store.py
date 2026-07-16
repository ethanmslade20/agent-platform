"""Persistence backend.

Local files by default (unchanged dev experience). When DATABASE_URL is set
(Neon Postgres on the host), accounts and every uploaded book blob live in the
database instead — so they survive the host wiping its ephemeral disk.

The engine still reads/writes local files; on the host we just persist those
files to Postgres on write and hydrate them back to a local cache on read.
"""
from __future__ import annotations

import os
from pathlib import Path


def _database_url() -> str:
    try:
        import streamlit as st
        u = st.secrets.get("DATABASE_URL")
    except Exception:
        u = None
    return str(u or os.environ.get("DATABASE_URL") or "").strip()


def using_db() -> bool:
    return bool(_database_url())


# ── Postgres (lazy — psycopg2 only imported when a DB is configured) ──────────
_conn = None


def _connection():
    global _conn
    import psycopg2
    if _conn is None or getattr(_conn, "closed", 1):
        _conn = psycopg2.connect(_database_url())
        _conn.autocommit = True
        with _conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS tenants (
                username TEXT PRIMARY KEY, agent_id TEXT, name TEXT,
                npn TEXT, salt TEXT, hash TEXT)""")
            cur.execute("""CREATE TABLE IF NOT EXISTS tenant_files (
                agent_id TEXT, path TEXT, data BYTEA, updated_at TIMESTAMPTZ DEFAULT now(),
                PRIMARY KEY (agent_id, path))""")
    return _conn


# ── Accounts ─────────────────────────────────────────────────────────────────
def load_tenants() -> dict:
    with _connection().cursor() as cur:
        cur.execute("SELECT username, agent_id, name, npn, salt, hash FROM tenants")
        return {r[0]: {"agent_id": r[1], "name": r[2], "npn": r[3], "salt": r[4], "hash": r[5]}
                for r in cur.fetchall()}


def save_tenants(d: dict) -> None:
    with _connection().cursor() as cur:
        for u, rec in d.items():
            cur.execute(
                """INSERT INTO tenants (username, agent_id, name, npn, salt, hash)
                   VALUES (%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (username) DO UPDATE SET
                     agent_id=EXCLUDED.agent_id, name=EXCLUDED.name, npn=EXCLUDED.npn,
                     salt=EXCLUDED.salt, hash=EXCLUDED.hash""",
                (u, rec.get("agent_id"), rec.get("name"), rec.get("npn"),
                 rec.get("salt"), rec.get("hash")))


# ── Uploaded book blobs ──────────────────────────────────────────────────────
def put_file(agent_id: str, relpath: str, data: bytes) -> None:
    import psycopg2
    with _connection().cursor() as cur:
        cur.execute(
            """INSERT INTO tenant_files (agent_id, path, data, updated_at)
               VALUES (%s,%s,%s, now())
               ON CONFLICT (agent_id, path) DO UPDATE SET data=EXCLUDED.data, updated_at=now()""",
            (agent_id, relpath, psycopg2.Binary(data)))


def hydrate(agent_id: str, root: Path) -> None:
    """Write all of a tenant's stored files into their local cache dir."""
    with _connection().cursor() as cur:
        cur.execute("SELECT path, data FROM tenant_files WHERE agent_id=%s", (agent_id,))
        rows = cur.fetchall()
    for relpath, data in rows:
        dest = root / relpath
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(bytes(data))
