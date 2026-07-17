"""Book rules — ported from Ethan's report so an agent's numbers compute the same way.

General rules that apply to every agent's book:
  • verification-expired (DMI/SVI) → Cancelled (coverage effectively lost)
  • AOR-taken (another agent is now the agent of record) → Terminated (pulled out of active)
  • carrier-name normalization
A `cancel_reason` marks WHY each churned client left, so the pages can bucket them
(genuine loss vs taken vs verification-expired) exactly like Ethan's site.

Per-agent rules (licensing states + manual exclusions) are applied elsewhere from
each tenant's own settings — these here are the universal ones.
"""
from __future__ import annotations

import re

import pandas as pd

from tracker.carriers import normalize_carrier_series

ACTIVE = ("Effectuated", "PendingEffectuation", "PendingFollowups")
CHURNED = ("Cancelled", "Terminated")
REASON_TAKEN = "AOR taken"
REASON_VEXP = "Verification expired"
REASON_SWITCH = "Plan switch"


def collapse_plan_switches(roster: pd.DataFrame) -> pd.DataFrame:
    """One client, one active policy. If a person shows more than one active
    policy (a plan switch — e.g. Ambetter → UnitedHealthcare), keep the newest by
    effective date active and mark the older ones Terminated ('Plan switch').
    They're flagged term_estimated so a switch is NOT miscounted as a real loss in
    the churn/loss averages, and they're excluded from the Re-Engage list."""
    if roster is None or roster.empty or "status" not in roster.columns:
        return roster
    df = roster.copy()
    if "cancel_reason" not in df.columns:
        df["cancel_reason"] = ""
    if "term_estimated" not in df.columns:
        df["term_estimated"] = False

    def _pk(f, l):
        s = f"{f} {l}".lower()
        return re.sub(r"[^a-z]", "", s)

    df["_pk"] = [_pk(f, l) for f, l in zip(df.get("first_name", ""), df.get("last_name", ""))]
    df["_eff"] = pd.to_datetime(df.get("effective_date"), errors="coerce")
    active = df["status"].isin(ACTIVE)
    counts = df.loc[active, "_pk"].value_counts()
    for k in counts[counts > 1].index:
        if not k:
            continue
        grp = df[active & (df["_pk"] == k)].sort_values("_eff", ascending=False, na_position="last")
        newest_eff = grp.iloc[0]["_eff"]
        for idx in grp.index[1:]:  # everyone except the newest policy
            df.at[idx, "status"] = "Terminated"
            df.at[idx, "cancel_reason"] = REASON_SWITCH
            df.at[idx, "term_estimated"] = True
            if "term_date" in df.columns and pd.isna(pd.to_datetime(df.at[idx, "term_date"], errors="coerce")):
                df.at[idx, "term_date"] = newest_eff
    return df.drop(columns=["_pk", "_eff"])


def apply_book_rules(roster: pd.DataFrame, npn: str = "", name: str = "") -> pd.DataFrame:
    df = roster.copy()
    if "cancel_reason" not in df.columns:
        df["cancel_reason"] = ""

    if "carrier" in df.columns:
        df["carrier"] = normalize_carrier_series(df["carrier"])

    def _num(col: str) -> pd.Series:
        return (pd.to_numeric(df[col], errors="coerce").fillna(0)
                if col in df.columns else pd.Series(0.0, index=df.index))

    # ── Verification expired → Cancelled ──────────────────────────────────────
    vexp = (_num("dmi_expired") > 0) | (_num("svi_expired") > 0)
    df.loc[vexp, "status"] = "Cancelled"
    df.loc[vexp, "cancel_reason"] = REASON_VEXP

    # ── AOR-taken (foreign agent-of-record) ───────────────────────────────────
    # HealthSherpa's policy_aor field LAGS the exchange (Ethan's site proved this),
    # so we do NOT drop an active client from the book on the raw field alone — that
    # over-removes real clients. The carrier portals (carrier-truth) are the truth
    # for who's really in force; the AOR field only *flags* at-risk clients on the
    # AOR Defense page (views.aor_taken reads policy_aor directly). We just tag the
    # reason for anyone ALREADY churned so Re-Engage/Book Updates can bucket them.
    if "policy_aor" in df.columns:
        aor = df["policy_aor"].fillna("").astype(str)
        parts = [p for p in (name or "").lower().split() if p]

        def _foreign(a: str) -> bool:
            al = a.lower()
            if not a.strip() or "none" in al:
                return False
            if npn and npn in a:
                return False
            if parts and all(p in al for p in parts):
                return False
            return True

        taken = aor.apply(_foreign)
        pk = (df["first_name"].fillna("").astype(str).str.lower().str.strip() + "|"
              + df["last_name"].fillna("").astype(str).str.lower().str.strip())
        taken = pk.isin(set(pk[taken]))
        # Only label already-churned clients (don't change any active client's status).
        tag = taken & df["status"].isin(CHURNED) & (df["cancel_reason"] == "")
        df.loc[tag, "cancel_reason"] = REASON_TAKEN

    return df


def apply_agent_settings(roster: pd.DataFrame, settings: dict) -> pd.DataFrame:
    """Per-agent filters. Precision order:
      1. appointments {state: [carrier keywords]} — keep only clients whose carrier
         the agent is appointed with in that state (matches Ethan's exact filter);
      2. else licensed_states — simple state-level keep;
      3. always: drop manually-excluded clients (by name + state).
    Empty settings = no filtering (a new agent includes everything)."""
    df = roster
    appts = settings.get("appointments") or {}
    states = [s.strip().upper() for s in (settings.get("licensed_states") or []) if s.strip()]

    if appts and {"state", "carrier"}.issubset(df.columns):
        # Appointments hold carrier BRANDS per state ("Ambetter", "Anthem", …).
        # A client counts if the brand of its specific carrier is one the agent is
        # appointed with in that state. Exact-name entries still match (a name's
        # brand is itself when unknown), so older setups keep working.
        from core.carrier_names import brand_of
        appt_b = {str(k).upper(): {brand_of(x) for x in v} | {str(x).strip() for x in v}
                  for k, v in appts.items()}

        def _appointed(r) -> bool:
            st = str(r.get("state", "")).upper().strip()
            c = str(r.get("carrier", "")).strip()
            if not st or not c:
                return True
            appointed = appt_b.get(st)
            if not appointed:
                return False  # not appointed in that state at all
            return brand_of(c) in appointed or c in appointed

        df = df[df.apply(_appointed, axis=1)]
    elif states and "state" in df.columns:
        df = df[df["state"].astype(str).str.upper().isin(states)]

    excl = settings.get("exclusions") or []
    if excl and {"first_name", "last_name"}.issubset(df.columns):
        keys = {(str(e.get("first", "")).lower().strip(),
                 str(e.get("last", "")).lower().strip(),
                 str(e.get("state", "")).upper().strip()) for e in excl}

        def _is_excluded(r) -> bool:
            return (str(r.get("first_name", "")).lower().strip(),
                    str(r.get("last_name", "")).lower().strip(),
                    str(r.get("state", "")).upper().strip()) in keys

        df = df[~df.apply(_is_excluded, axis=1)]
    return df.copy()
