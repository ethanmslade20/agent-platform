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
from tracker.diff import build_all_clients, assign_loss_months
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


def ingest_aor_at_risk(agent_id: str, data: bytes) -> int:
    """Store HealthSherpa's 'AOR at-risk clients' quick export — a bare list of Federal
    Exchange IDs (= ffm_app_id) HealthSherpa itself flagged as agent-of-record at risk.
    The export carries NO changed/disconnected label, so we keep the ID set and, on each
    book build, sub-classify each by the current AOR field (another agent = likely taken;
    blank = disconnected/reconnect; back to you = resolved)."""
    import re as _re
    import pandas as _pd
    df = _pd.read_csv(io.BytesIO(data), dtype=str).fillna("")
    idcol = next((c for c in df.columns
                  if "exchange id" in c.lower() or c.strip().lower() == "ffm_app_id"), None)
    if idcol is None:
        raise ValueError("No 'Federal Exchange ID' column — is this the AOR at-risk export "
                         "from HealthSherpa (Exports → Quick Exports → AOR at-risk clients)?")
    ids = sorted({_re.sub(r"[^0-9]", "", str(x)) for x in df[idcol]} - {""})
    paths.ensure_dirs(agent_id)
    p = paths.tenant_root(agent_id) / "aor_at_risk.json"
    p.write_text(json.dumps({"ids": ids,
                             "uploaded": dt.datetime.now().isoformat(timespec="seconds")}, indent=2))
    if store.using_db():
        store.put_file(agent_id, "aor_at_risk.json", p.read_bytes())
    _record_upload(agent_id, "aor_at_risk")
    return len(ids)


def load_aor_at_risk_ids(agent_id: str) -> set:
    """The set of ffm_app_ids HealthSherpa flagged AOR-at-risk (empty if none uploaded)."""
    p = paths.tenant_root(agent_id) / "aor_at_risk.json"
    if store.using_db() and not p.exists():
        store.hydrate(agent_id, paths.tenant_root(agent_id))
    try:
        return set(json.loads(p.read_text()).get("ids", []))
    except Exception:
        return set()


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
    # AOR'd = gone. Clients on HealthSherpa's OWN at-risk list whose agent-of-record
    # field now shows ANOTHER agent are marked Cancelled ("AOR taken") so they drop out
    # of the active count — a stolen client isn't active. Blank-AOR (disconnected) ones
    # on the list stay active (still yours, just needs a reconnect). They still surface
    # on AOR at Risk, which keys off the at-risk list, not status. Done last so it wins.
    _at = load_aor_at_risk_ids(agent_id)
    if _at and "ffm_app_id" in roster.columns and "policy_aor" in roster.columns:
        import re as _re
        _ids = {_re.sub(r"[^0-9]", "", str(x)) for x in _at} - {""}
        _rid = roster["ffm_app_id"].apply(lambda x: _re.sub(r"[^0-9]", "", str(x)))
        _parts = [p for p in (name or "").lower().split() if p]

        def _foreign_aor(a):
            al = str(a or "").lower()
            if npn and str(npn) in str(a):
                return False
            if not al.strip() or "none" in al:
                return False
            if _parts and all(p in al for p in _parts):
                return False
            return True

        _taken = _rid.isin(_ids) & roster["policy_aor"].apply(_foreign_aor)
        roster.loc[_taken, "status"] = "Cancelled"
        if "cancel_reason" in roster.columns:
            roster.loc[_taken, "cancel_reason"] = rules.REASON_TAKEN
    # Loss dating: every gone client (AOR-taken, verification-expired, left-book,
    # undated cancellation) that carries no cancel date gets one. We date it to the
    # month the agent's COMMISSION on them stopped (money doesn't lie) — falling back
    # to the exchange sync date, then the last month a snapshot showed them active.
    # Without this they'd be counted active-forever in the month-over-month engine and
    # never register as a loss, understating churn and overstating LTV. Runs last.
    roster = assign_loss_months(roster, last_paid=_agent_last_paid(agent_id))
    return roster


def _agent_last_paid(agent_id: str) -> dict:
    """Money-backed 'last month paid' lookups from the agent's uploaded commission
    statements — {"by_policy": {policy: 'YYYY-MM'}, "by_name": {name_key: 'YYYY-MM'},
    "by_carrier_names": {brand: {name_key: 'YYYY-MM'}}} — so loss-dating can match a gone
    client by policy ID (name-independent), then exact name, then fuzzy name within the
    same carrier. Best-effort; empty if there are no commission records."""
    import re
    from core import commissions_ingest
    empty = {"by_policy": {}, "by_name": {}, "by_carrier_names": {}}
    try:
        recs = commissions_ingest.load_records(agent_id)
    except Exception:
        return empty
    if recs is None or recs.empty or "client" not in recs.columns or "period" not in recs.columns:
        return empty

    def _key(m):
        x = re.sub(r"\b(family|household)\b", "", str(m), flags=re.I).strip()
        if "," in x:
            last, rest = x.split(",", 1); p = rest.split()
            return re.sub(r"[^a-z]", "", ((p[0] if p else "") + last).lower())
        p = x.split()
        return re.sub(r"[^a-z]", "", ((p[0] + p[-1]) if len(p) >= 2 else x).lower())

    def _polnorm(x):
        v = re.sub(r"[^0-9a-z]", "", str(x).lower())
        return v if len(v) >= 5 else ""

    def _brand(c):
        c = str(c).lower()
        for kw, b in (("ambetter", "ambetter"), ("oscar", "oscar"), ("wellpoint", "anthem"),
                      ("anthem", "anthem"), ("unitedhealth", "uhc"), ("united health", "uhc"),
                      ("uhc", "uhc"), ("cigna", "cigna"), ("molina", "molina"),
                      ("selecthealth", "selecthealth"), ("select health", "selecthealth"),
                      ("blue", "bcbs"), ("bcbs", "bcbs")):
            if kw in c:
                return b
        return re.sub(r"[^a-z]", "", c)[:10] or "other"

    by_policy, by_name, by_carrier = {}, {}, {}
    has_pol = "policy_id" in recs.columns
    has_car = "carrier" in recs.columns
    for _, row in recs.iterrows():
        m = str(row.get("period", ""))
        if not re.match(r"^\d{4}-\d{2}$", m):
            continue
        nk = _key(row.get("client"))
        if nk:
            by_name[nk] = max(by_name.get(nk, ""), m)
            d = by_carrier.setdefault(_brand(row.get("carrier") if has_car else ""), {})
            d[nk] = max(d.get(nk, ""), m)
        if has_pol:
            pn = _polnorm(row.get("policy_id"))
            if pn:
                by_policy[pn] = max(by_policy.get(pn, ""), m)
    return {"by_policy": by_policy, "by_name": by_name, "by_carrier_names": by_carrier}


def _book_brands(roster) -> dict:
    """{STATE: {brand,...}} actually present in the roster right now."""
    from core import carrier_names
    book = {}
    for st, sub in roster.groupby(roster["state"].astype(str).str.upper().str.strip()):
        st = str(st).strip()
        if not st or st == "NAN":
            continue
        brands = {(carrier_names.brand_of(c) or str(c).strip())
                  for c in sub["carrier"].dropna() if str(c).strip()}
        brands = {b for b in brands if b}
        if brands:
            book[st] = brands
    return book


def _auto_seed_appointments(agent_id: str, roster) -> None:
    """Seed appointments ONCE, on the agent's very first upload: turn on every (state,
    carrier) found in their book so they don't have to click each one by hand. After
    that this NEVER touches appointments again — the agent owns them (turn off what they
    don't want and it stays off).

    Also maintains `appt_seen` — every carrier the agent has acknowledged (turned on or
    dismissed). Carriers in the book but NOT in appt_seen are "new" and drive the
    Settings heads-up (new_carriers), so a carrier that first appears in a later upload
    is surfaced instead of silently dropping its clients."""
    from core import settings
    if roster is None or roster.empty or not {"state", "carrier"}.issubset(roster.columns):
        return
    cfg = settings.get(agent_id)
    book = _book_brands(roster)
    if not cfg.get("appointments_initialized"):
        # first upload: turn every carrier on AND record them all as acknowledged
        appts = {str(k).upper(): list(v or []) for k, v in (cfg.get("appointments") or {}).items()}
        for st, brands in book.items():
            appts[st] = sorted(set(appts.get(st, [])) | brands)
        settings.save(agent_id, {**cfg, "appointments": appts,
                                 "appt_seen": {st: sorted(b) for st, b in book.items()},
                                 "appointments_initialized": True})
        return
    # Already initialized — never auto-change appointments. But if this agent predates
    # carrier tracking, acknowledge their whole CURRENT book once, so the heads-up only
    # ever flags carriers that appear from here on (not everything they already have).
    if "appt_seen" not in cfg:
        settings.save(agent_id, {**cfg, "appt_seen": {st: sorted(b) for st, b in book.items()}})


def new_carriers(agent_id: str, roster) -> dict:
    """{STATE: [brand,...]} present in the book but never acknowledged (turned on OR
    dismissed) — i.e. showed up after the first-upload seed. Drives the Settings heads-up."""
    from core import settings
    if roster is None or roster.empty or not {"state", "carrier"}.issubset(roster.columns):
        return {}
    seen = {str(k).upper(): set(v or []) for k, v in (settings.get(agent_id).get("appt_seen") or {}).items()}
    out = {}
    for st, brands in _book_brands(roster).items():
        fresh = sorted(brands - seen.get(st, set()))
        if fresh:
            out[st] = fresh
    return out


def acknowledge_carrier(agent_id: str, state: str, brand: str, turn_on: bool) -> None:
    """Handle a newly-seen carrier: always add it to appt_seen (so it stops showing as
    new); if turn_on, also add it to appointments so its clients count from now on."""
    from core import settings
    cfg = settings.get(agent_id)
    stt = str(state).upper().strip()
    seen = {str(k).upper(): set(v or []) for k, v in (cfg.get("appt_seen") or {}).items()}
    seen.setdefault(stt, set()).add(brand)
    appts = {str(k).upper(): list(v or []) for k, v in (cfg.get("appointments") or {}).items()}
    if turn_on:
        appts[stt] = sorted(set(appts.get(stt, [])) | {brand})
    settings.save(agent_id, {**cfg,
                             "appt_seen": {k: sorted(v) for k, v in seen.items()},
                             "appointments": appts})


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
