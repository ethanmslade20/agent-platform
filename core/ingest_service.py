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

import io
import zipfile
from pathlib import Path

from tracker.config import load_carrier_configs
from tracker.diff import build_all_clients
from tracker.ingest import ingest_file, load_all_snapshots

from core import paths, store

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
    return snap, df


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
    return dest


def build_book(agent_id: str):
    """The agent's person-level roster from everything they've uploaded, or None."""
    snap_dir = paths.snapshots_dir(agent_id)
    # On the host, the local cache may be empty (fresh container) — pull the
    # tenant's files back from the database before building.
    if store.using_db() and not any(snap_dir.glob("*.parquet")):
        store.hydrate(agent_id, paths.tenant_root(agent_id))
    months = load_all_snapshots(snap_dir)
    if not months:
        return None
    roster = build_all_clients(months)
    return roster if roster is not None and not roster.empty else None
