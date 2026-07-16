"""Per-tenant data paths — the isolation boundary.

Every read/write for an agent resolves under `tenants/<agent_id>/`, so one agent's
book can never see or touch another's. The subfolders mirror the single-tenant
engine's layout (`input/`, `snapshots/`, `data/`) so `tracker/` code can be pointed
at a tenant folder with no changes.
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_TENANTS = _ROOT / "tenants"

_SUBDIRS = ("input", "snapshots", "data", "carrier_books")


def tenant_root(agent_id: str) -> Path:
    return _TENANTS / agent_id


def ensure_dirs(agent_id: str) -> Path:
    """Create the tenant's folder tree if it doesn't exist yet. Returns the root."""
    root = tenant_root(agent_id)
    for sub in _SUBDIRS:
        (root / sub).mkdir(parents=True, exist_ok=True)
    return root


def input_dir(agent_id: str) -> Path:
    return tenant_root(agent_id) / "input"


def snapshots_dir(agent_id: str) -> Path:
    return tenant_root(agent_id) / "snapshots"


def data_dir(agent_id: str) -> Path:
    return tenant_root(agent_id) / "data"


def carrier_books_dir(agent_id: str) -> Path:
    return tenant_root(agent_id) / "carrier_books"


def snapshot_count(agent_id: str) -> int:
    d = snapshots_dir(agent_id)
    return len(list(d.glob("*.parquet"))) if d.exists() else 0
