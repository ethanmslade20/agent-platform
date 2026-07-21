"""Per-tenant analytics views — Phase 3.

Each function derives one page's data from what the agent has uploaded, reusing the
same engine logic Ethan's system runs on. Everything is computed from the tenant's
own roster / carrier_books, so an agent only ever sees their own numbers.

Deferred (need data agents don't have yet): commissions/disputes (a per-agent
payment source) and renewals (prior plan-year snapshots a brand-new agent lacks).
"""
from __future__ import annotations

import re

import pandas as pd

from tracker.pastdue import load_health_pastdue

from core import paths

ACTIVE = ("Effectuated", "PendingEffectuation", "PendingFollowups")
LOST = ("Cancelled", "Terminated")


def active(roster: pd.DataFrame) -> pd.DataFrame:
    return roster[roster["status"].isin(ACTIVE)].copy()


def _as_bool(v) -> bool:
    """Parse a flag that may be a real bool (local parquet) or text ('TRUE'/'FALSE'
    from the DB / Google Sheets). A plain .astype(bool) treats 'FALSE' as True."""
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes", "t")


def losses(roster: pd.DataFrame) -> pd.DataFrame:
    """Genuine cancellations/terminations — the re-engage list. Excludes clients
    who churned only because they were taken by another agent or lost a
    verification (those have their own pages), matching Ethan's site.

    Also excludes UNCONFIRMED cancellations (term_estimated=True). A client who is
    still active in HealthSherpa but merely absent from an uploaded carrier-portal
    export gets flagged Cancelled with a *guessed* date — those are frequently still
    active, so they must not land on an outreach list. Re-Engage = confirmed losses
    only (a real cancel date), never a portal-absence guess."""
    churned = roster[roster["status"].isin(LOST)]
    if "cancel_reason" in churned.columns:
        # Plan switches are retained clients (moved to a newer plan), not losses.
        churned = churned[~churned["cancel_reason"].isin(
            ["AOR taken", "Verification expired", "Plan switch"])]
    if "term_estimated" in churned.columns:
        churned = churned[~churned["term_estimated"].apply(_as_bool)]
    return churned.copy()


def aor_taken(roster: pd.DataFrame, npn: str = "", name: str = "") -> pd.DataFrame:
    """Clients whose current agent of record is now someone else — from the
    HealthSherpa AOR column alone (no scrape needed)."""
    aor = roster["policy_aor"].fillna("").astype(str)
    parts = [p for p in (name or "").lower().split() if p]

    # Without an NPN or name to match on, we can't tell "someone else" from "me" —
    # every populated AOR would look foreign and the whole book would read as taken.
    # Return nothing rather than falsely flag everyone.
    if not str(npn).strip() and not parts:
        out = roster.iloc[0:0].copy()
        out["taken_by"] = pd.Series(dtype=str)
        return out

    def is_foreign(a: str) -> bool:
        al = a.lower()
        if not a.strip() or "none" in al:
            return False
        if npn and npn in a:            # still me
            return False
        if parts and all(p in al for p in parts):
            return False
        return True

    mask = aor.apply(is_foreign)
    # Still active in a carrier's member portal = still yours — the HealthSherpa AOR
    # field just disconnected. Don't flag those as taken (they're a Reconnect, not a
    # steal). Clients with NO portal record stay flagged for the agent to verify.
    if "portal_confirmed" in roster.columns:
        mask = mask & ~roster["portal_confirmed"].apply(_as_bool)
    out = roster[mask].copy()
    out["taken_by"] = aor[mask].str.replace(r"\s*\(NPN.*", "", regex=True).str.strip()
    return out


def aor_at_risk_view(roster: pd.DataFrame, at_risk_ids: set, npn: str = "", name: str = "") -> pd.DataFrame:
    """The clients HealthSherpa itself flagged AOR-at-risk (matched by ffm_app_id), each
    tagged with a sub-status read from the CURRENT agent-of-record field:
      taken       — another agent shows  → win-back
      reconnect   — AOR field is blank    → dropped Marketplace link, reconnect/verify
      reconnected — back to the agent     → resolved (auto-drops off next upload)
    HealthSherpa's at-risk export carries no changed/disconnected label, so the AOR field
    is how we split them, and each new upload re-resolves the list automatically."""
    empty = roster.iloc[0:0].copy()
    empty["_sub"] = pd.Series(dtype=str)
    empty["taken_by"] = pd.Series(dtype=str)
    if not at_risk_ids or "ffm_app_id" not in roster.columns:
        return empty
    ids = {re.sub(r"[^0-9]", "", str(x)) for x in at_risk_ids} - {""}
    rid = roster["ffm_app_id"].apply(lambda x: re.sub(r"[^0-9]", "", str(x)))
    out = roster[rid.isin(ids)].copy()
    if out.empty:
        return empty
    parts = [p for p in (name or "").lower().split() if p]

    def _sub(a):
        al = str(a or "").lower()
        if npn and str(npn) in str(a):
            return "reconnected"
        if not al.strip() or "none" in al:
            return "reconnect"
        if parts and all(p in al for p in parts):
            return "reconnected"
        return "taken"

    out["_sub"] = out["policy_aor"].apply(_sub)
    out["taken_by"] = (out["policy_aor"].fillna("").astype(str)
                       .str.replace(r"\s*\(NPN.*", "", regex=True).str.strip())
    return out


def verifications(roster: pd.DataFrame) -> pd.DataFrame:
    """Active clients with an expired DMI/SVI verification — coverage at risk
    unless docs go in."""
    def num(col: str) -> pd.Series:
        return (pd.to_numeric(roster[col], errors="coerce").fillna(0)
                if col in roster.columns else pd.Series(0.0, index=roster.index))
    mask = (num("dmi_expired") > 0) | (num("svi_expired") > 0)
    return roster[mask].copy()


def past_due(agent_id: str):
    """Past-due clients parsed from the agent's Ambetter/Oscar carrier books.
    Returns None if they haven't uploaded those yet."""
    cb = paths.carrier_books_dir(agent_id)
    try:
        df = load_health_pastdue(str(cb))
    except Exception:
        return None
    return df if df is not None and not df.empty else None
