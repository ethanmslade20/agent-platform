"""Dashboard KPIs — the headline numbers, computed per tenant.

Reuses the engine's `build_dashboard_data` (which reconstructs month-over-month
growth from the export's own submission/term dates) and adds the derived figures
Ethan's dashboard shows: household size, net growth, churn, and the commission
forecast (members x PMPM).
"""
from __future__ import annotations

from tracker.dashboard import build_dashboard_data
from tracker.ingest import load_all_snapshots

from core import ingest_service, paths

# Per-member-per-month commission (matches Ethan's dashboard: members x 23).
PMPM = 23


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
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

    return {
        "policies": policies,
        "members": members,
        "household": (members / policies) if policies else 0.0,
        "added": added,
        "lost": lost,
        "net_growth": (added - lost) if (added is not None and lost is not None) else None,
        "churn": (lost / policies * 100) if (lost is not None and policies) else None,
        "m_added": m_added,
        "m_lost": m_lost,
        "net_members": (m_added - m_lost) if (m_added is not None and m_lost is not None) else None,
        "comm_monthly": monthly,
        "comm_annual": monthly * 12,
        "per_policy": (monthly / policies) if policies else 0.0,
        "history_months": len(months),
        "mom": mom,
        "carrier_df": data.get("carrier_df"),
        "state_df": data.get("state_df"),
    }
