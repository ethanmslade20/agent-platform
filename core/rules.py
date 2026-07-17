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

    # ── AOR-taken → Terminated (foreign agent-of-record) ──────────────────────
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
        # Propagate to the whole person: if ANY of their rows shows a foreign AOR,
        # the client is taken (matches the marketplace-wins rule).
        pk = (df["first_name"].fillna("").astype(str).str.lower().str.strip() + "|"
              + df["last_name"].fillna("").astype(str).str.lower().str.strip())
        taken = pk.isin(set(pk[taken]))

        newly = taken & ~df["status"].isin(CHURNED)
        df.loc[newly, "status"] = "Terminated"
        # Tag the reason (don't overwrite a verification-expired tag).
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
        # Appointments hold exact carrier names per state; match the client's
        # carrier by exact (case-insensitive) name. A short legacy entry with no
        # exact match falls back to substring so older keyword setups still work.
        appt_u = {str(k).upper(): [str(x).lower().strip() for x in v] for k, v in appts.items()}

        def _appointed(r) -> bool:
            st = str(r.get("state", "")).upper().strip()
            c = str(r.get("carrier", "")).lower().strip()
            if not st or not c:
                return True
            names = appt_u.get(st)
            if not names:
                return False  # not appointed in that state at all
            if c in names:
                return True
            # legacy keyword fallback (only for short, non-exact entries)
            return any(k in c for k in names if len(k) <= 12 and k not in {c})

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
