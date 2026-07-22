"""Dashboard KPIs — the headline numbers, computed per tenant.

Reuses the engine's `build_dashboard_data` (month-over-month growth from the export's
submission/term dates) and adds the derived figures Ethan's dashboard shows: household
size, net growth, churn, the commission forecast, and lifetime value.
"""
from __future__ import annotations

import datetime as _dt

from tracker.dashboard import build_dashboard_data
from tracker.ingest import load_all_snapshots

from core import ingest_service, paths

# Per-member-per-month commission — a FORECAST estimate (members x 23) used when the
# agent hasn't uploaded real statements. LTV prefers real commission when available.
PMPM = 23


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _weighted_churn(mom):
    """Trailing-12-completed-month, exposure-weighted monthly churn %: Σ members lost
    ÷ Σ start-of-month members. 12 months spans exactly one OEP renewal cliff (shorter
    windows seesaw seasonally); weighting keeps a big month and a small month
    proportional. Returns None if the MoM table can't support it."""
    if mom is None or mom.empty or "Month" not in mom.columns or "Members Lost" not in mom.columns:
        return None
    cur = f"{_dt.date.today().year}-{_dt.date.today().month:02d}"
    c = mom[mom["Month"].astype(str) < cur].copy()
    if c.empty or "Total Members" not in c.columns:
        return None
    c["_start"] = c["Total Members"].shift(1)
    w = c.tail(12)
    denom = float(w["_start"].sum())
    return (float(w["Members Lost"].sum()) / denom * 100) if denom > 0 else None


def _real_per_policy(agent_id, policies):
    """Real commission per policy from the latest COMPLETE month of uploaded statements,
    or None if there's no commission data. Money-backed input for LTV."""
    if not policies:
        return None
    try:
        from core import commissions_ingest
        s = commissions_ingest.summary(commissions_ingest.load_records(agent_id))
        bm = s.get("by_month")
        if bm is None or bm.empty:
            return None
        cur = f"{_dt.date.today().year}-{_dt.date.today().month:02d}"
        comp = bm[bm["Month"].astype(str) < cur].sort_values("Month")
        if comp.empty:
            return None
        return float(comp.iloc[-1]["Paid"]) / policies
    except Exception:
        return None


def compute(agent_id: str, roster=None) -> dict | None:
    """All dashboard KPIs for one agent, or None if they have no book yet."""
    if roster is None:
        roster = ingest_service.build_book(agent_id)
    if roster is None:
        return None

    months = load_all_snapshots(paths.snapshots_dir(agent_id))
    data = build_dashboard_data(months, roster)
    k = data.get("kpis", {})
    mom = data.get("mom_df")

    policies = int(k.get("Total Active Policies", 0) or 0)
    members = int(k.get("Total Members", 0) or 0)
    added = _num(k.get("Avg Policies Added/Month"))
    lost = _num(k.get("Avg Policies Lost/Month"))
    m_added = _num(k.get("Avg Members Added/Month"))
    m_lost = _num(k.get("Avg Members Lost/Month"))
    monthly = members * PMPM

    # Churn = trailing-12-mo weighted (the validated real rate); fall back to the crude
    # avg-lost / current-book ratio only if the MoM table is unavailable.
    churn = _weighted_churn(mom)
    if churn is None:
        churn = (lost / policies * 100) if (lost is not None and policies) else None

    # LTV = avg tenure (1 / monthly churn) × commission per policy. Prefer REAL
    # commission from uploaded statements; fall back to the PMPM estimate.
    tenure = (1 / (churn / 100)) if churn else None
    real_pp = _real_per_policy(agent_id, policies)
    per_policy_est = (monthly / policies) if policies else 0.0
    ltv_pp = real_pp if real_pp is not None else per_policy_est
    ltv = (ltv_pp * tenure) if (tenure and ltv_pp) else None

    return {
        "policies": policies,
        "members": members,
        "household": (members / policies) if policies else 0.0,
        "added": added,
        "lost": lost,
        "net_growth": (added - lost) if (added is not None and lost is not None) else None,
        "churn": churn,
        "tenure": tenure,
        "real_per_policy": real_pp,
        "ltv": ltv,
        "m_added": m_added,
        "m_lost": m_lost,
        "net_members": (m_added - m_lost) if (m_added is not None and m_lost is not None) else None,
        "comm_monthly": monthly,
        "comm_annual": monthly * 12,
        "per_policy": per_policy_est,
        "history_months": len(months),
        "mom": mom,
        "carrier_df": data.get("carrier_df"),
        "state_df": data.get("state_df"),
    }
