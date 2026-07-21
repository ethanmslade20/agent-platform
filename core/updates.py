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


def _is_foreign_aor(aor: str, npn: str, name_parts: list) -> bool:
    """True if the agent-of-record is someone else — same logic as views.aor_taken."""
    al = str(aor or "").lower()
    if not al.strip() or "none" in al:
        return False
    if npn and str(npn) in str(aor):          # still me (my NPN)
        return False
    if name_parts and all(p in al for p in name_parts):
        return False
    return True


def _book_state(roster: pd.DataFrame, npn: str = "", name: str = "") -> dict:
    """name_key -> {cat, name, mem}. cat = mine / lost / taken / vexp.

    "taken" is decided from policy_aor (a foreign agent of record) — the same field
    the AOR at Risk page uses — so an active-but-taken client reads as taken and a
    win-back (taken -> mine) is detectable. cancel_reason==AOR taken is also honored."""
    name_parts = [p for p in (name or "").lower().split() if p]
    # We can only call an AOR "someone else's" if we know who THIS agent is. With no
    # NPN and no name to match on, every populated policy_aor looks foreign and the
    # WHOLE book reads as "taken" (blank-NPN tenants got wrecked this way). When we
    # can't judge identity, fall back to status-only and trust only an explicit
    # cancel_reason of "AOR taken".
    can_judge_aor = bool(str(npn).strip()) or bool(name_parts)
    out = {}
    for _, r in roster.iterrows():
        k = _key(r.get("first_name", ""), r.get("last_name", ""))
        if not k:
            continue
        status = str(r.get("status") or "")
        reason = str(r.get("cancel_reason") or "")
        # Still active in a carrier's member portal = still yours (the HealthSherpa AOR
        # field just disconnected) — don't count those as taken.
        confirmed = str(r.get("portal_confirmed", "")).strip().lower() in ("true", "1", "yes")
        foreign = can_judge_aor and _is_foreign_aor(r.get("policy_aor", ""), npn, name_parts)
        if (foreign and not confirmed) or reason == REASON_TAKEN:
            cat = "taken"
        elif status in ACTIVE:
            cat = "mine"
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


def compute_and_log(agent_id: str, roster: pd.DataFrame, when: str | None = None,
                    npn: str = "", name: str = "") -> dict:
    """Diff the new book vs the last upload, append a summary entry, reset baseline."""
    paths.ensure_dirs(agent_id)
    base_p, log_p = _paths(agent_id)
    _ensure(agent_id, base_p)
    new = _book_state(roster, npn, name)
    baseline = _read(base_p, None)
    stamp = when or dt.datetime.now().strftime("%b %d, %Y · %-I:%M %p")

    if not baseline:
        entry = {"date": stamp, "first": True}
    else:
        def names(pred):
            return [v["name"] for k, v in new.items() if pred(k, v)]
        # Per-name member counts for the newly-signed, so day-grouping can re-total
        # members for only the clients whose FINAL status stays Signed (a client
        # signed then moved to Taken the same day must drop out of BOTH count and
        # members — otherwise you get the nonsensical "0 policies / 83 members").
        _signed = {v["name"]: (1 if pd.isna(v["mem"]) else int(v["mem"]))
                   for k, v in new.items() if v["cat"] == "mine" and k not in baseline}
        signed = list(_signed.keys())
        won = names(lambda k, v: v["cat"] == "mine" and baseline.get(k, {}).get("cat") in ("lost", "taken"))
        lost = names(lambda k, v: v["cat"] == "lost" and baseline.get(k, {}).get("cat") == "mine")
        taken = names(lambda k, v: v["cat"] == "taken" and baseline.get(k, {}).get("cat") == "mine")
        vexp = names(lambda k, v: v["cat"] == "vexp" and baseline.get(k, {}).get("cat") == "mine")
        members = sum(_signed.values())
        entry = {"date": stamp, "first": False, "signed": len(signed), "members": members,
                 "signed_names": signed, "signed_mem": _signed,
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
