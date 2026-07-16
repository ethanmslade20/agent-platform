"""Book Updates — the on-screen version of Ethan's post-upload text.

Each time an agent uploads, we diff the new book against the previous upload and
log a summary: newly signed, lost (cancelled), taken by another agent, verification
expired, and won back. The Book Updates page shows that history.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import unicodedata

import pandas as pd

from core import paths, store
from core.rules import ACTIVE, CHURNED, REASON_TAKEN, REASON_VEXP

_MAX_LOG = 60


def _key(first, last) -> str:
    s = unicodedata.normalize("NFKD", f"{first} {last}").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]", "", s)


def _book_state(roster: pd.DataFrame) -> dict:
    """name_key -> {cat, name, mem}. cat = mine / lost / taken / vexp."""
    out = {}
    for _, r in roster.iterrows():
        k = _key(r.get("first_name", ""), r.get("last_name", ""))
        if not k:
            continue
        status = str(r.get("status") or "")
        reason = str(r.get("cancel_reason") or "")
        if status in ACTIVE:
            cat = "mine"
        elif reason == REASON_TAKEN:
            cat = "taken"
        elif reason == REASON_VEXP:
            cat = "vexp"
        elif status in CHURNED:
            cat = "lost"
        else:
            cat = "other"
        m = pd.to_numeric(r.get("applicant_count"), errors="coerce")
        out[k] = {"cat": cat,
                  "name": f"{r.get('first_name', '')} {r.get('last_name', '')}".strip().title(),
                  "mem": 1 if pd.isna(m) else max(int(m), 1)}
    return out


def _paths(agent_id: str):
    root = paths.tenant_root(agent_id)
    return root / "baseline.json", root / "updates.json"


def _read(p, default):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _ensure(agent_id: str, p) -> None:
    """Pull the tenant's files back from the DB if this one isn't in the local cache."""
    if store.using_db() and not p.exists():
        store.hydrate(agent_id, paths.tenant_root(agent_id))


def compute_and_log(agent_id: str, roster: pd.DataFrame, when: str | None = None) -> dict:
    """Diff the new book vs the last upload, append a summary entry, reset baseline."""
    paths.ensure_dirs(agent_id)
    base_p, log_p = _paths(agent_id)
    _ensure(agent_id, base_p)
    new = _book_state(roster)
    baseline = _read(base_p, None)
    stamp = when or dt.datetime.now().strftime("%b %d, %Y · %-I:%M %p")

    if not baseline:
        entry = {"date": stamp, "first": True}
    else:
        def names(pred):
            return [v["name"] for k, v in new.items() if pred(k, v)]
        signed = names(lambda k, v: v["cat"] == "mine" and k not in baseline)
        won = names(lambda k, v: v["cat"] == "mine" and baseline.get(k, {}).get("cat") in ("lost", "taken"))
        lost = names(lambda k, v: v["cat"] == "lost" and baseline.get(k, {}).get("cat") == "mine")
        taken = names(lambda k, v: v["cat"] == "taken" and baseline.get(k, {}).get("cat") == "mine")
        vexp = names(lambda k, v: v["cat"] == "vexp" and baseline.get(k, {}).get("cat") == "mine")
        members = sum(v["mem"] for k, v in new.items() if v["cat"] == "mine" and k not in baseline)
        entry = {"date": stamp, "first": False, "signed": len(signed), "members": members,
                 "lost": lost, "taken": taken, "vexp": vexp, "won": won}

    base_p.write_text(json.dumps(new))
    log = _read(log_p, [])
    log.insert(0, entry)
    log = log[:_MAX_LOG]
    log_p.write_text(json.dumps(log, indent=2))
    if store.using_db():
        store.put_file(agent_id, "baseline.json", base_p.read_bytes())
        store.put_file(agent_id, "updates.json", log_p.read_bytes())
    return entry


def history(agent_id: str) -> list:
    _, log_p = _paths(agent_id)
    _ensure(agent_id, log_p)
    return _read(log_p, [])
