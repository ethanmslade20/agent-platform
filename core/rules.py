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
    """One client, one active policy. Within a single name+STATE, a person showing
    more than one active policy is collapsed to their current plan (latest effective)
    and the rest are Terminated ('Plan switch'; term_estimated so a switch isn't
    miscounted as a real loss and is left off Re-Engage). Two active rows are the SAME
    person if they share an id (app / subscriber / email / phone), are on DIFFERENT
    carriers (a person holds one active marketplace plan), or are the SAME carrier with
    an identical effective date (a duplicate enrollment). Two same-carrier rows with
    different effective dates and no shared id are LEFT ALONE — that's the genuine
    same-name-in-the-same-state stranger case, so two different people are never merged.
    Scoping to name+STATE also protects same-name people in different states."""
    if roster is None or roster.empty or "status" not in roster.columns:
        return roster
    df = roster.copy()
    if "cancel_reason" not in df.columns:
        df["cancel_reason"] = ""
    if "term_estimated" not in df.columns:
        df["term_estimated"] = False

    def _col(c):
        return df[c] if c in df.columns else pd.Series("", index=df.index)

    nm = (_col("first_name").fillna("").astype(str) + _col("last_name").fillna("").astype(str)
          ).str.lower().str.replace(r"[^a-z]", "", regex=True)
    st = _col("state").fillna("").astype(str).str.lower().str.strip()
    key = nm + "@" + st
    active = df["status"].isin(ACTIVE)
    eff = pd.to_datetime(df.get("effective_date"), errors="coerce")
    cur = pd.to_datetime(df.get("current_effective"), errors="coerce")
    cur = cur.where(cur.notna(), eff)
    car = _col("carrier").astype(str).str.lower()
    sid = _col("ffm_subscriber_id").astype(str).str.replace(r"[^0-9]", "", regex=True)
    app = _col("ffm_app_id").astype(str).str.replace(r"[^0-9]", "", regex=True)
    em = _col("email").fillna("").astype(str).str.lower().str.strip()
    ph = _col("phone").astype(str).str.replace(r"[^0-9]", "", regex=True).str[-10:]

    def _same(i, j):
        if app[i] and app[i] == app[j]:
            return True                       # same FFM application
        if sid[i] and sid[i] == sid[j]:
            return True                       # same subscriber id
        if em[i] and em[i] == em[j]:
            return True
        if ph[i] and ph[i] == ph[j]:
            return True
        if car[i] != car[j]:
            return True                       # cross-carrier switch
        return bool(eff[i] == eff[j])         # same carrier: a dup only if identical eff

    for k, cnt in key[active].value_counts().items():
        if cnt < 2 or k.startswith("@"):
            continue
        idxs = list(df.index[active & (key == k)])
        clusters: list = []
        for i in idxs:
            for cl in clusters:
                if any(_same(i, j) for j in cl):
                    cl.append(i)
                    break
            else:
                clusters.append([i])
        for cl in clusters:
            if len(cl) < 2:
                continue
            newest = max(cl, key=lambda x: (pd.notna(cur[x]),
                                            cur[x] if pd.notna(cur[x]) else pd.Timestamp.min))
            for i in cl:
                if i == newest:
                    continue
                df.at[i, "status"] = "Terminated"
                df.at[i, "cancel_reason"] = REASON_SWITCH
                df.at[i, "term_estimated"] = True
                if "term_date" in df.columns and pd.isna(
                        pd.to_datetime(df.at[i, "term_date"], errors="coerce")):
                    df.at[i, "term_date"] = cur[newest]
    return df


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
    # ...but NOT for brand-new business whose coverage hasn't started yet (future
    # effective date). A pre-effective new enrollment with an expired DMI/SVI just
    # owes a document — it belongs on Documents Due, not marked as a lost client.
    _eff = (pd.to_datetime(df["effective_date"], errors="coerce")
            if "effective_date" in df.columns else pd.Series(pd.NaT, index=df.index))
    _today = pd.Timestamp.today().normalize()
    vexp = ((_num("dmi_expired") > 0) | (_num("svi_expired") > 0)) & ~(_eff > _today)
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

    # Carriers the agent never counts as their book (e.g. Florida Blue / BCBS-FL).
    # Matched on the RAW carrier name (before brand-collapse) as a case-insensitive
    # substring, so "florida blue" drops the FL Blue entities without touching other
    # Blue Cross plans.
    excl_carriers = [str(x).strip().lower() for x in (settings.get("excluded_carriers") or [])
                     if str(x).strip()]
    if excl_carriers and "carrier" in df.columns:
        cl = df["carrier"].astype(str).str.lower()
        df = df[~cl.apply(lambda c: any(x in c for x in excl_carriers))]

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
