"""Per-agent settings — licensed states + manual client exclusions.

Each agent has their own (seeded empty). Stored as settings.json in their tenant
folder and persisted to the database like any other file, so it survives restarts.
"""
from __future__ import annotations

import json

from core import paths, store

_DEFAULT = {"licensed_states": [], "exclusions": [], "appointments": {},
            "goals": {}, "aep": {}}


def _file(agent_id: str):
    return paths.tenant_root(agent_id) / "settings.json"


def get(agent_id: str) -> dict:
    p = _file(agent_id)
    if store.using_db() and not p.exists():
        store.hydrate(agent_id, paths.tenant_root(agent_id))
    if p.exists():
        try:
            return {**_DEFAULT, **json.loads(p.read_text())}
        except Exception:
            pass
    return dict(_DEFAULT)


def save(agent_id: str, settings: dict) -> None:
    paths.ensure_dirs(agent_id)
    p = _file(agent_id)
    p.write_text(json.dumps(settings, indent=2))
    if store.using_db():
        store.put_file(agent_id, "settings.json", p.read_bytes())
