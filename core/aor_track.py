"""Track when each AOR-taken client was first detected, per tenant.

HealthSherpa's export says a client's agent-of-record changed, but not WHEN. So the
first time we see a client flipped to another agent we stamp today's date; "days
gone" counts from there. Stored per tenant (survives restarts) like other files.
A client who returns to the agent is dropped, so a later re-take restarts the clock.
"""
from __future__ import annotations

import datetime as dt
import json

from core import paths, store


def _file(agent_id: str):
    return paths.tenant_root(agent_id) / "aor_seen.json"


def _load(agent_id: str) -> dict:
    p = _file(agent_id)
    if store.using_db() and not p.exists():
        store.hydrate(agent_id, paths.tenant_root(agent_id))
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}


def days_gone(agent_id: str, keys, today=None) -> dict:
    """Record first-seen dates for the currently-taken client keys and return
    {key: days_gone}. Prunes clients no longer taken."""
    today = today or dt.date.today()
    seen = _load(agent_id)
    live = set(k for k in keys if k)
    changed = False
    for k in live:
        if k not in seen:
            seen[k] = today.isoformat()
            changed = True
    for k in list(seen):
        if k not in live:
            del seen[k]
            changed = True
    out = {}
    for k in live:
        try:
            out[k] = max((today - dt.date.fromisoformat(seen[k])).days, 0)
        except Exception:
            out[k] = 0
    if changed:
        paths.ensure_dirs(agent_id)
        _file(agent_id).write_text(json.dumps(seen, indent=2))
        if store.using_db():
            store.put_file(agent_id, "aor_seen.json", _file(agent_id).read_bytes())
    return out
