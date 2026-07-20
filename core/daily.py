"""Daily Tracker data — NEW BUSINESS per day/week/month from submission dates.

"New business" = a client's FIRST-EVER sign-up, not an OEP renewal or plan
re-submission. HealthSherpa archives the prior application when a client re-enrolls,
so in a single export a 2025 client renewing for 2026 looks brand-new (one row,
submitted during Open Enrollment, effective next year). We exclude renewals using
every piece of prior-existence evidence we have:

  1. Snapshot history — anyone seen in an upload from an earlier month than their
     sale already existed (grows more complete as the agent uploads each month).
  2. Carrier books — Ambetter "Broker Effective Date" / Anthem "Original Effective
     Date" carry the client's true first coverage date, independent of HealthSherpa.
  3. HealthSherpa effective dates — an effective date before the sale month means an
     older policy row survived the archive.

Caveat: on a first upload with no carrier books and no history, a pure year-over-year
HealthSherpa renewal is indistinguishable from a new client — those can still slip in
until the agent adds carrier books or uploads across a few months.
"""
from __future__ import annotations

import calendar
import re

import pandas as pd

from core import paths


def _norm(s) -> str:
    return re.sub(r"[^a-z]", "", str(s).lower())


def _carrier_evidence(agent_id: str) -> dict:
    """{normalized name: earliest coverage date} from the tenant's carrier books.

    These dates predate HealthSherpa's archive, so they reveal clients who were
    already covered before an OEP renewal. Best-effort — unknown carrier formats
    and missing files are skipped."""
    evid: dict = {}

    def note(k, ts):
        if k and pd.notna(ts) and (k not in evid or ts < evid[k]):
            evid[k] = ts

    books = paths.carrier_books_dir(agent_id)
    # Ambetter — "Insured First/Last Name" + Broker/Policy Effective Date
    try:
        amb = books / "ambetter.csv"
        if amb.exists():
            a = pd.read_csv(amb, dtype=str)
            for col in ("Broker Effective Date", "Policy Effective Date", "Original Effective Date"):
                if col in a.columns:
                    e = pd.to_datetime(a[col], errors="coerce")
                    for f, l, x in zip(a.get("Insured First Name", pd.Series(dtype=str)).fillna(""),
                                       a.get("Insured Last Name", pd.Series(dtype=str)).fillna(""), e):
                        note(_norm(f"{f}{l}"), x)
    except Exception:
        pass
    # Anthem — "Client Name" as "Last, First" + Original Effective Date (header row 2)
    try:
        ant = books / "anthem.csv"
        if ant.exists():
            n = pd.read_csv(ant, dtype=str, skiprows=1)
            e = pd.to_datetime(n.get("Original Effective Date"), errors="coerce")
            for nm, x in zip(n.get("Client Name", pd.Series(dtype=str)).fillna(""), e):
                if "," in str(nm):
                    last, first = [p.strip() for p in str(nm).split(",", 1)]
                    note(_norm(f"{first}{last}"), x)
    except Exception:
        pass
    return evid


def _new_business_mask(agent_id: str, d: pd.DataFrame) -> pd.Series:
    """Boolean, index-aligned with d: True where the row is a first-time sign-up."""
    sale_month = d["_dt"].dt.strftime("%Y-%m")
    month_start = pd.to_datetime(sale_month + "-01")

    # (1) Snapshot history: first upload-month we ever saw this person. If that
    #     predates the sale month, they already existed → renewal / re-submission.
    fseen = d.get("first_seen")
    hist_prior = (fseen.notna() & (fseen.astype(str) < sale_month)
                  if fseen is not None else pd.Series(False, index=d.index))

    # (2) HealthSherpa: an effective date before the sale month = surviving old policy.
    eff = pd.to_datetime(d.get("effective_date"), errors="coerce")
    hs_prior = eff.notna() & (eff < month_start)

    # (3) Carrier books: true first coverage date before the sale month.
    evid = _carrier_evidence(agent_id)
    ev = d["name_key"].map(lambda k: evid.get(_norm(k))) if "name_key" in d.columns else pd.Series(pd.NaT, index=d.index)
    ev = pd.to_datetime(ev, errors="coerce")
    cb_prior = ev.notna() & (ev < month_start)

    return ~(hist_prior | hs_prior | cb_prior)


def _prep(roster: pd.DataFrame, agent_id: str | None = None) -> pd.DataFrame:
    col = "submission_date" if "submission_date" in roster.columns else "effective_date"
    d = roster.copy()
    d["_dt"] = pd.to_datetime(d[col], errors="coerce")
    d["_mem"] = pd.to_numeric(d.get("applicant_count"), errors="coerce").fillna(1).clip(lower=1)
    d = d.dropna(subset=["_dt"])
    if agent_id and not d.empty:
        d = d[_new_business_mask(agent_id, d)]
    return d


def months_available(roster: pd.DataFrame, agent_id: str | None = None) -> list:
    d = _prep(roster, agent_id)
    if d.empty:
        return []
    return sorted(d["_dt"].dt.strftime("%Y-%m").unique(), reverse=True)


def daily_counts(roster: pd.DataFrame, ym: str, agent_id: str | None = None) -> pd.DataFrame:
    """One row per calendar day of `ym` with NEW-business policies + members that day."""
    d = _prep(roster, agent_id)
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


def personal_bests(roster: pd.DataFrame, agent_id: str | None = None):
    """(best_day, best_week, best_month) all-time for NEW business — each a dict or None."""
    d = _prep(roster, agent_id)
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
