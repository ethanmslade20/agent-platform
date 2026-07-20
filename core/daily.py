"""Daily Tracker data — NEW BUSINESS per day/week/month, counted from the day the
agent started using Agent Book.

"New business" = a client who first shows up in an upload AFTER the agent's very
first upload — i.e. someone they signed while using the tool. Anyone present in
that first upload is treated as pre-existing: we can't tell a brand-new client
from an Open-Enrollment renewal before we started watching (HealthSherpa archives
the prior application on re-enroll, so a renewal looks identical to a new sale in
a single export). Counting only NET-NEW clients from the baseline forward needs no
carrier books and stays accurate through future OEPs — renewals are already in the
book, so they never count.

Trade-off: it shows nothing until the agent has uploaded past their first month and
signed someone new. That empty start is honest; the numbers that appear are real.
"""
from __future__ import annotations

import calendar
import re

import pandas as pd

_YM = re.compile(r"^\d{4}-\d{2}$")


def _prep(roster: pd.DataFrame) -> pd.DataFrame:
    """Rows for genuinely-new clients (first seen after the baseline upload month),
    with `_dt` = sale date and `_mem` = member count."""
    col = "submission_date" if "submission_date" in roster.columns else "effective_date"
    d = roster.copy()
    d["_dt"] = pd.to_datetime(d[col], errors="coerce")
    d["_mem"] = pd.to_numeric(d.get("applicant_count"), errors="coerce").fillna(1).clip(lower=1)

    if "first_seen" not in d.columns:
        return d.iloc[0:0]
    fs = d["first_seen"].astype(str)
    valid = d["first_seen"].notna() & fs.str.match(_YM)
    if not valid.any():
        return d.iloc[0:0]
    baseline = fs[valid].min()                       # earliest snapshot month = first upload
    d = d[valid & (fs > baseline)]                   # kept only if first seen AFTER baseline
    return d.dropna(subset=["_dt"])


def months_available(roster: pd.DataFrame) -> list:
    d = _prep(roster)
    if d.empty:
        return []
    return sorted(d["_dt"].dt.strftime("%Y-%m").unique(), reverse=True)


def daily_counts(roster: pd.DataFrame, ym: str) -> pd.DataFrame:
    """One row per calendar day of `ym` with NEW-business policies + members that day."""
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
    """(best_day, best_week, best_month) of NEW business since the agent started —
    each a dict or None (None until there's net-new business past the first upload)."""
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
