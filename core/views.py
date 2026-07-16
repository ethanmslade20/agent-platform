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


def losses(roster: pd.DataFrame) -> pd.DataFrame:
    """Genuine cancellations/terminations — the re-engage list. Excludes clients
    who churned only because they were taken by another agent or lost a
    verification (those have their own pages), matching Ethan's site."""
    churned = roster[roster["status"].isin(LOST)]
    if "cancel_reason" in churned.columns:
        churned = churned[~churned["cancel_reason"].isin(["AOR taken", "Verification expired"])]
    return churned.copy()


def aor_taken(roster: pd.DataFrame, npn: str = "", name: str = "") -> pd.DataFrame:
    """Clients whose current agent of record is now someone else — from the
    HealthSherpa AOR column alone (no scrape needed)."""
    aor = roster["policy_aor"].fillna("").astype(str)
    parts = [p for p in (name or "").lower().split() if p]

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
    out = roster[mask].copy()
    out["taken_by"] = aor[mask].str.replace(r"\s*\(NPN.*", "", regex=True).str.strip()
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
