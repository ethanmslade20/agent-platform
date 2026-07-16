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
