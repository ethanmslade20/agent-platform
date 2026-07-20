"""Daily Tracker data — policies submitted per day/week/month, from submission dates.

This is a submission-activity view (every policy the agent submitted, by day), not
a new-vs-renewal split — the "Submissions by Day" chart and Day-by-Day Breakdown
count all submissions in the selected month.
"""
from __future__ import annotations

import calendar

import pandas as pd


def _prep(roster: pd.DataFrame) -> pd.DataFrame:
    col = "submission_date" if "submission_date" in roster.columns else "effective_date"
    d = roster.copy()
    d["_dt"] = pd.to_datetime(d[col], errors="coerce")
    d["_mem"] = pd.to_numeric(d.get("applicant_count"), errors="coerce").fillna(1).clip(lower=1)
    return d.dropna(subset=["_dt"])


def months_available(roster: pd.DataFrame) -> list:
    d = _prep(roster)
    if d.empty:
        return []
    return sorted(d["_dt"].dt.strftime("%Y-%m").unique(), reverse=True)


def daily_counts(roster: pd.DataFrame, ym: str) -> pd.DataFrame:
    """One row per calendar day of `ym` with policies + members submitted that day."""
    d = _prep(roster)
    year, mnum = int(ym[:4]), int(ym[5:7])
    dim = calendar.monthrange(year, mnum)[1]
    out = pd.DataFrame({"Date": pd.date_range(f"{ym}-01", periods=dim, freq="D")})
    dm = d[d["_dt"].dt.strftime("%Y-%m") == ym]
    g = dm.groupby(dm["_dt"].dt.date)
    pol, mem = g.size(), g["_mem"].sum()
    key = out["Date"].dt.date
    out["Policies"] = key.map(pol).fillna(0).astype(int)
    out["Members"] = key.map(mem).fillna(0).astype(int)
    return out
