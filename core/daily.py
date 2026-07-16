"""Daily Tracker data — new business per day/week/month from submission dates."""
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


def personal_bests(roster: pd.DataFrame):
    """(best_day, best_week, best_month) all-time — each a dict or None."""
    d = _prep(roster)
    if d.empty:
        return None, None, None

    def rec(grouper, fmt):
        g = d.groupby(grouper).agg(pol=("_mem", "size"), mem=("_mem", "sum"))
        if g.empty:
            return None
        bp, bm = g["pol"].idxmax(), g["mem"].idxmax()
        return dict(pol=int(g.loc[bp, "pol"]), pol_when=fmt(bp),
                    mem=int(g.loc[bm, "mem"]), mem_when=fmt(bm))

    day = rec(d["_dt"].dt.date, lambda k: pd.Timestamp(k).strftime("%b %d, %Y"))
    week = rec(d["_dt"].dt.to_period("W"), lambda k: "week of " + k.start_time.strftime("%b %d, %Y"))
    month = rec(d["_dt"].dt.to_period("M"), lambda k: k.strftime("%B %Y"))
    return day, week, month
