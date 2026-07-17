"""Tenant accounts — the multi-tenant foundation.

Each agent is one tenant with a login and an isolated `agent_id` that names their
private data folder. Credentials live in `tenants/tenants.json` (gitignored, never
committed). Passwords are stored only as a salted PBKDF2 hash — never in plaintext.

Deliberately dependency-free (stdlib only) so the shell stays lightweight.
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_TENANTS_FILE = _ROOT / "tenants" / "tenants.json"
_ITERATIONS = 200_000


def _load() -> dict:
    from core import store
    if store.using_db():
        return store.load_tenants()
    if _TENANTS_FILE.exists():
        try:
            return json.loads(_TENANTS_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save(d: dict) -> None:
    from core import store
    if store.using_db():
        store.save_tenants(d)
        return
    _TENANTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _TENANTS_FILE.write_text(json.dumps(d, indent=2))


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS
    ).hex()


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return base or "agent"


def _unique_agent_id(name: str, existing: set[str]) -> str:
    aid = _slug(name)
    if aid not in existing:
        return aid
    i = 2
    while f"{aid}-{i}" in existing:
        i += 1
    return f"{aid}-{i}"


def create_tenant(username: str, password: str, name: str, npn: str = "") -> dict:
    """Register a new agent. Raises ValueError if the username is taken."""
    if not username.strip() or not password:
        raise ValueError("username and password are required")
    d = _load()
    u = username.lower().strip()
    if u in d:
        raise ValueError(f"username '{u}' already exists")
    salt = secrets.token_hex(16)
    agent_id = _unique_agent_id(name, {v["agent_id"] for v in d.values()})
    d[u] = {
        "agent_id": agent_id,
        "name": name.strip(),
        "npn": npn.strip(),
        "salt": salt,
        "hash": _hash(password, salt),
    }
    _save(d)
    return _public(u, d[u])


def update_npn(username: str, npn: str) -> None:
    """Let an agent set/change their own NPN from Settings (self-service)."""
    d = _load()
    u = username.lower().strip()
    if u in d:
        d[u]["npn"] = str(npn).strip()
        _save(d)


def rename(old_username: str, new_username: str) -> dict:
    """Change an agent's login username, keeping their agent_id (and all data).
    Raises ValueError if the new name is empty, taken, or the account is missing."""
    old = (old_username or "").lower().strip()
    new = (new_username or "").lower().strip()
    if not new:
        raise ValueError("Username can't be empty.")
    if " " in new:
        raise ValueError("Username can't contain spaces.")
    d = _load()
    if old not in d:
        raise ValueError("Account not found.")
    if new == old:
        return _public(old, d[old])
    if new in d:
        raise ValueError(f"Username '{new}' is already taken.")
    d[new] = d.pop(old)
    _save(d)
    from core import store
    if store.using_db():
        store.delete_tenant(old)  # _save upserts the new row; drop the stale old one
    return _public(new, d[new])


def verify(username: str, password: str) -> dict | None:
    """Return the tenant's public record on a correct login, else None."""
    d = _load()
    u = (username or "").lower().strip()
    rec = d.get(u)
    if not rec:
        return None
    if secrets.compare_digest(_hash(password, rec["salt"]), rec["hash"]):
        return _public(u, rec)
    return None


def _public(username: str, rec: dict) -> dict:
    """Strip secrets before handing a record to the app / session."""
    return {
        "username": username,
        "agent_id": rec["agent_id"],
        "name": rec.get("name", ""),
        "npn": rec.get("npn", ""),
    }


def list_tenants() -> list[dict]:
    return [_public(u, rec) for u, rec in _load().items()]
