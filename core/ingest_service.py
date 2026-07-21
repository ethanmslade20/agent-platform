"""Turns an agent's uploaded files into their book — the Phase 2 bridge.

HealthSherpa is the backbone: its CSV runs through the reused `tracker/` engine
into a per-tenant snapshot, and the book builds from there. The four carrier
exports (Ambetter/Oscar/Anthem/UHC) are stashed in the tenant's carrier_books/
for the payment & dispute reconciliation that gets wired up in Phase 3.

Note: the engine's unlicensed-state matrix filter is Ethan's personal licensing,
so it is deliberately NOT applied here (full_config=None) — every agent keeps all
of their own clients.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import zipfile
from pathlib import Path

from tracker.config import load_carrier_configs
from tracker.diff import build_all_clients
from tracker.ingest import ingest_file, load_all_snapshots

from core import paths, store


def _uploads_file(agent_id: str) -> Path:
    return paths.tenant_root(agent_id) / "uploads.json"


def _record_upload(agent_id: str, source: str) -> None:
    """Stamp the time a given source (healthsherpa / a carrier key) was uploaded."""
    p = _uploads_file(agent_id)
    if store.using_db() and not p.exists():
        store.hydrate(agent_id, paths.tenant_root(agent_id))
    data = {}
    if p.exists():
        try:
            data = json.loads(p.read_text())
        except Exception:
            data = {}
    data[source] = dt.datetime.now().isoformat(timespec="seconds")
    paths.ensure_dirs(agent_id)
    p.write_text(json.dumps(data, indent=2))
    if store.using_db():
        store.put_file(agent_id, "uploads.json", p.read_bytes())


def last_uploads(agent_id: str) -> dict:
    """{source: ISO timestamp} of the last upload of each file, or {}."""
    p = _uploads_file(agent_id)
    if store.using_db() and not p.exists():
        store.hydrate(agent_id, paths.tenant_root(agent_id))
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}

_ROOT = Path(__file__).resolve().parent.parent
_CARRIER_CFG = str(_ROOT / "config" / "carrier_configs.yaml")

# Where each carrier upload lands in the tenant's carrier_books/ (canonical names
# the engine's reconciliation expects). Ambetter arrives zipped; UHC as .xlsx.
_CARRIERS = {
    "ambetter": {"label": "Ambetter", "types": ["zip"], "dest": "ambetter.csv", "zipped": True},
    "oscar": {"label": "Oscar", "types": ["csv"], "dest": "oscar.csv", "zipped": False},
    "anthem": {"label": "Anthem", "types": ["csv"], "dest": "anthem.csv", "zipped": False},
    "uhc": {"label": "UnitedHealthcare", "types": ["xlsx"], "dest": "uhc_source.xlsx", "zipped": False},
}


def carriers() -> dict:
    return _CARRIERS


def _scope_ownership(source_configs: dict, npn: str, name: str) -> dict:
    """Point the 'keep only my clients' filter at THIS agent's identity, not the
    template's. Without an NPN we drop the filter (keep everything) rather than
    silently wipe the book against a blank identity."""
    hs = dict(source_configs.get("healthsherpa") or {})
    if not hs:
        return source_configs
    if str(npn).strip():
        rem = dict(hs.get("require_ever_mine") or {})
        rem["npn"] = str(npn).strip()
        rem["name"] = str(name or "").strip()
        hs["require_ever_mine"] = rem
    else:
        hs.pop("require_ever_mine", None)
    return {**source_configs, "healthsherpa": hs}


def ingest_healthsherpa(agent_id: str, data: bytes, npn: str = "", name: str = "", month=None) -> tuple:
    """Save the agent's HealthSherpa export and ingest it into their snapshots,
    keeping only the clients THIS agent (npn/name) was ever the agent for.
    Returns (snapshot_path, dataframe). Raises with a human message on a bad file."""
    paths.ensure_dirs(agent_id)
    dest = paths.input_dir(agent_id) / "healthsherpa.csv"
    dest.write_bytes(data)
    source_configs = _scope_ownership(load_carrier_configs(_CARRIER_CFG), npn, name)
    # full_config omitted → skip the per-agent licensing matrix (that's Ethan's; a
    # future per-tenant setting). Keep all of the agent's own clients.
    snap, df = ingest_file(dest, source_configs, paths.snapshots_dir(agent_id), month=month)
    if store.using_db() and snap:
        store.put_file(agent_id, f"snapshots/{Path(snap).name}", Path(snap).read_bytes())
    _record_upload(agent_id, "healthsherpa")
    return snap, df


# State-based marketplaces (agents in these states enroll off their own exchange, not
# HealthSherpa). Same "book_of_business" export format for all three; the state is read
# from each row's address, so the key here just names the file so states don't collide.
_STATE_SOURCES = {
    "il": {"label": "Illinois — Get Covered IL"},
    "ga": {"label": "Georgia — Georgia Access"},
    "va": {"label": "Virginia — Virginia's Insurance Marketplace"},
}


def state_sources() -> dict:
    return _STATE_SOURCES


def ingest_state_exchange(agent_id: str, data: bytes, state_key: str, month=None) -> tuple:
    """Ingest a state-based-marketplace export (Get Covered IL / GA Access / Virginia).
    All use the same book_of_business format; enrolled clients are kept (shopping
    leads dropped), deduped against HealthSherpa. Turns on any brand-new state the
    file brings in so its clients aren't hidden by the appointment filter."""
    if state_key not in _STATE_SOURCES:
        raise ValueError(f"unknown state source '{state_key}'")
    paths.ensure_dirs(agent_id)
    dest = paths.input_dir(agent_id) / f"book_of_business_{state_key}.csv"
    dest.write_bytes(data)
    source_configs = load_carrier_configs(_CARRIER_CFG)
    # full_config omitted → no licensing-matrix drop; keep all of the agent's clients.
    snap, df = ingest_file(dest, source_configs, paths.snapshots_dir(agent_id), month=month)
    if store.using_db() and snap:
        store.put_file(agent_id, f"snapshots/{Path(snap).name}", Path(snap).read_bytes())
    _seed_new_states(agent_id, df)
    _record_upload(agent_id, f"state_{state_key}")
    return snap, df


def _seed_new_states(agent_id: str, df) -> None:
    """Turn on the states + carriers this state-exchange file brings in, so its
    clients aren't hidden by the appointment filter. Only ADDS (unions in the file's
    states/brands) — it never removes, so anything the agent deliberately toggled off
    elsewhere is untouched. Uploading a state's file implies you write there."""
    from core import settings, carrier_names
    if df is None or df.empty or not {"state", "carrier"}.issubset(df.columns):
        return
    cfg = settings.get(agent_id)
    appts = dict(cfg.get("appointments") or {})
    changed = False
    for st, sub in df.groupby(df["state"].astype(str).str.upper().str.strip()):
        st = str(st).strip()
        if not st or st == "NAN":
            continue
        brands = {carrier_names.brand_of(c) for c in sub["carrier"].dropna() if carrier_names.brand_of(c)}
        merged = sorted(set(appts.get(st) or []) | brands)
        if merged != sorted(appts.get(st) or []):
            appts[st] = merged
            changed = True
    if changed:
        settings.save(agent_id, {**cfg, "appointments": appts, "appointments_initialized": True})


def save_carrier(agent_id: str, carrier: str, data: bytes) -> Path:
    """Store a carrier export in the tenant's carrier_books/ under its canonical name.
    Ambetter is unzipped to its inner CSV. Returns the saved path."""
    if carrier not in _CARRIERS:
        raise ValueError(f"unknown carrier '{carrier}'")
    cb = paths.carrier_books_dir(agent_id)
    cb.mkdir(parents=True, exist_ok=True)
    spec = _CARRIERS[carrier]
    dest = cb / spec["dest"]
    if spec["zipped"]:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            inner = next((n for n in z.namelist() if n.lower().endswith(".csv")), None)
            if not inner:
                raise ValueError("No CSV found inside the Ambetter .zip — re-download the policies export.")
            dest.write_bytes(z.read(inner))
    else:
        dest.write_bytes(data)
    if store.using_db():
        store.put_file(agent_id, f"carrier_books/{dest.name}", dest.read_bytes())
    _record_upload(agent_id, carrier)
    return dest


def build_book(agent_id: str, npn: str = "", name: str = ""):
    """The agent's person-level roster from everything they've uploaded, with the
    same active-book rules Ethan's site applies (AOR-taken + verification-expired
    pulled out of active). None if they have no book yet."""
    from core import rules, settings
    snap_dir = paths.snapshots_dir(agent_id)
    # On the host, the local cache may be empty (fresh container) — pull the
    # tenant's files back from the database before building.
    if store.using_db() and not any(snap_dir.glob("*.parquet")):
        store.hydrate(agent_id, paths.tenant_root(agent_id))
    months = load_all_snapshots(snap_dir)
    if not months:
        return None
    roster = build_all_clients(months)
    if roster is None or roster.empty:
        return None
    roster = rules.apply_book_rules(roster, npn, name)
    # Clients who vanished from the latest export left the book — mark Cancelled
    # (matches Ethan's site: anyone who dropped off is treated as cancelled).
    if "last_seen" in roster.columns and months:
        latest = max(months.keys())
        gone = (roster["last_seen"].astype(str) < latest) & roster["status"].isin(rules.ACTIVE)
        roster.loc[gone, "status"] = "Cancelled"
        if "cancel_reason" in roster.columns:
            roster.loc[gone & (roster["cancel_reason"] == ""), "cancel_reason"] = "Left book"
    # First upload: auto-detect the agent's states + carriers and turn them all on,
    # so they don't have to set appointments by hand. After that we never touch it —
    # anything they toggle off in Settings stays off.
    _auto_seed_appointments(agent_id, roster)
    roster = rules.apply_agent_settings(roster, settings.get(agent_id))
    # Carrier-portal truth: reconcile the active book against the carrier exports
    # (Ambetter/Oscar/UHC/Anthem) the agent uploaded — the carrier's own system is
    # the source of truth for who's really in force. No-op for any carrier not
    # uploaded. This is what brings the numbers in line with Ethan's site.
    # portal_confirmed starts False and each carrier-truth pass flips it True for a
    # client it positively matches as active in that portal — used by AOR-taken to
    # spare "the HealthSherpa AOR field disconnected but the carrier still has them"
    # cases (still active in the portal = still yours, not stolen).
    roster["portal_confirmed"] = False
    roster = _apply_carrier_truth(agent_id, roster)
    # One client, one active policy — collapse plan switches (keep newest active,
    # term the older one) so a person never shows twice in the book.
    roster = rules.collapse_plan_switches(roster)
    # Collapse per-state carrier entities to their brand (e.g. "Ambetter from Peach
    # State Health Plan", "Ambetter of Tennessee" → "Ambetter") so charts/tables
    # group by carrier the way Ethan's site does — done last, after carrier-truth.
    from core import carrier_names
    if "carrier" in roster.columns:
        roster["carrier"] = roster["carrier"].apply(carrier_names.brand_of)
    return roster


def _auto_seed_appointments(agent_id: str, roster) -> None:
    """On the very first upload (no appointments configured yet), turn on every
    state + carrier found in the agent's book, so they start with their real book
    instead of a blank filter. Runs ONCE — the `appointments_initialized` flag then
    keeps it from re-adding anything the agent later toggles off in Settings."""
    from core import settings, carrier_names
    cfg = settings.get(agent_id)
    if cfg.get("appointments") or cfg.get("appointments_initialized"):
        return  # already set up (auto or by hand) — respect the agent's choices
    if roster is None or roster.empty or not {"state", "carrier"}.issubset(roster.columns):
        return
    derived = {}
    for st, sub in roster.groupby(roster["state"].astype(str).str.upper().str.strip()):
        st = str(st).strip()
        if not st or st == "NAN":
            continue
        brands = sorted({carrier_names.brand_of(c) for c in sub["carrier"].dropna()
                         if carrier_names.brand_of(c)})
        if brands:
            derived[st] = brands
    settings.save(agent_id, {**cfg, "appointments": derived, "appointments_initialized": True})


def _apply_carrier_truth(agent_id: str, roster):
    """Apply each uploaded carrier book as truth over the roster. Each function is
    a no-op if that carrier's book isn't present; a malformed book is skipped
    loudly rather than killing the whole build."""
    from tracker.carrier_truth import (apply_ambetter_truth, apply_oscar_truth,
                                        apply_uhc_truth, apply_anthem_truth)
    cb = str(paths.carrier_books_dir(agent_id))
    for fn, label in ((apply_ambetter_truth, "Ambetter"), (apply_oscar_truth, "Oscar"),
                      (apply_uhc_truth, "UHC"), (apply_anthem_truth, "Anthem")):
        try:
            roster, _ = fn(roster, carrier_books_dir=cb)
        except Exception as e:  # bad/changed export must not break the book
            print(f"  !! {label} carrier truth skipped — {type(e).__name__}: {e}")
    return roster
