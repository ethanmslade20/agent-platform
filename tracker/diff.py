"""
Computes client-level diffs between two monthly snapshots.

Identity is person-based (name_key = normalized first+last name), not
policy-based. This means plan switches and AEP rollovers are treated as
retention, not churn+new.
"""

from typing import Optional

import pandas as pd


# Active statuses — used to prefer active rows when a person has multiple plans
_ACTIVE_STS = {"Effectuated", "PendingEffectuation", "PendingFollowups"}
_STATUS_RANK = {s: 1 for s in _ACTIVE_STS}   # active → rank 1 (sorts last = "last")


def _person_key(df: pd.DataFrame, month_col: Optional[str] = None) -> pd.Series:
    """
    Stable person-level key.

    Normally: name_key (normalized first+last name).

    Name-collision fallback: if the same name appears as two or more ACTIVE rows
    within the same month snapshot (genuine different people with the same name),
    append ffm_subscriber_id to disambiguate: "john smith|0012345678".

    Plan switches are NOT collisions — a switcher produces one terminated row and one
    active row in the same month; only the active row survives dedup, so only one
    active row per name exists and the collision guard never fires.

    month_col: name of the column holding the month key in a multi-month DataFrame.
               When None the entire df is treated as one snapshot.
    """
    from tracker.ingest import match_client_id
    df = match_client_id(df)

    nk  = df.get("name_key",          pd.Series("", index=df.index)).fillna("").astype(str).str.strip()
    sid = df.get("ffm_subscriber_id", pd.Series("", index=df.index)).fillna("").astype(str).str.strip()
    ck  = df.get("client_key",        pd.Series("", index=df.index)).fillna("").astype(str)

    # Detect within-snapshot name collisions among active rows
    active_mask = df["status"].isin(_ACTIVE_STS) if "status" in df.columns else pd.Series(True, index=df.index)

    tmp = pd.DataFrame({"nk": nk, "sid": sid, "active": active_mask}, index=df.index)
    if month_col and month_col in df.columns:
        tmp["month"] = df[month_col]
        group_cols = ["month", "nk"]
    else:
        tmp["month"] = "_"
        group_cols = ["month", "nk"]

    # Names with ≥2 distinct non-empty sub_ids among active rows in the same snapshot
    active_tmp = tmp[tmp["active"] & (tmp["sid"] != "")]
    counts = active_tmp.groupby(group_cols)["sid"].nunique()
    collision_pairs = set(counts[counts > 1].index)   # set of (month, nk) tuples

    # Build key: collision rows get name|sub_id, everyone else gets name
    key = nk.copy()
    if collision_pairs:
        mo_series = tmp["month"]
        for idx in df.index:
            pair = (mo_series.at[idx], nk.at[idx])
            if pair in collision_pairs and sid.at[idx]:
                key.at[idx] = f"{nk.at[idx]}|{sid.at[idx]}"

    return key.where(key != "", ck)


def _dedup_month(df: pd.DataFrame) -> pd.DataFrame:
    """
    Within a single month's snapshot, reduce to one row per person.
    Prefers active-status rows; among ties takes latest effective_date.
    """
    from tracker.ingest import match_client_id, normalize_name
    df = match_client_id(df).copy()
    df["_pkey"] = _person_key(df)
    df["_srank"] = df["status"].map(_STATUS_RANK).fillna(0)
    df["effective_date"] = pd.to_datetime(df.get("effective_date"), errors="coerce")

    df = df.sort_values(["_pkey", "_srank", "effective_date"])
    deduped = df.groupby("_pkey", sort=False).last().reset_index()
    deduped = deduped.rename(columns={"_pkey": "name_key"})
    deduped = deduped.drop(columns=["_srank"], errors="ignore")
    return deduped


def compute_diff(df_a: pd.DataFrame, df_b: pd.DataFrame) -> dict:
    """
    Compare month A (older) to month B (newer) at the PERSON level.
    A plan switch (same name, different policy_id) counts as 'stayed', not lost+new.
    Returns dict with keys: new, missing, stayed.
    """
    a = _dedup_month(df_a).set_index("name_key")
    b = _dedup_month(df_b).set_index("name_key")

    keys_a = set(a.index)
    keys_b = set(b.index)

    new_keys     = keys_b - keys_a
    missing_keys = keys_a - keys_b
    stayed_keys  = keys_a & keys_b

    new_df     = b.loc[list(new_keys)].reset_index()
    missing_df = a.loc[list(missing_keys)].reset_index()
    stayed_df  = b.loc[list(stayed_keys)].reset_index()

    return {"new": new_df, "missing": missing_df, "stayed": stayed_df}


def build_all_clients(months: dict, npn: str = "", name: str = "") -> pd.DataFrame:
    """
    Build a cumulative person-level roster across all months.

    One row per person (matched by name_key).
    - effective_date  = earliest plan start across all plans (true book entry date)
    - carrier/status/net_premium/applicant_count = most recent active plan, or
      most recent plan if no active plan exists
    - term_date       = NaT if the person has any currently active plan;
                        else max(term_date) across all their plans — or, for a gone
                        person whose newest HealthSherpa plan is Terminated, that
                        plan's coverage end (coverage_end, see below)
    - months_on_book  = calendar months from effective_date to latest snapshot month

    npn / name = the logged-in agent (core.ingest_service.build_book passes the
    tenant's), used only to tell the agent's own plan from another agent's when
    dating a loss by coverage end. Without them, only blank-AOR rows qualify.
    """
    from tracker.ingest import match_client_id

    rows = []
    for month_key in sorted(months.keys()):
        df = match_client_id(months[month_key]).copy()
        df["month"] = month_key
        rows.append(df)

    if not rows:
        return pd.DataFrame()

    all_df = pd.concat(rows, ignore_index=True)

    # Ensure person key exists on every row (pass month_col so collision detection
    # is scoped per-month, not across all months — prevents plan switches from
    # being misidentified as name collisions)
    all_df["_pkey"] = _person_key(all_df, month_col="month")

    # Status rank: active rows sort last so "last" aggregation picks them
    all_df["_srank"] = all_df["status"].map(_STATUS_RANK).fillna(0)
    # Month this row was ACTIVE (blank otherwise) → the max per person is the last
    # month a snapshot showed them active. That's the anchor for dating a loss when
    # a client is gone but carries no cancel date (see assign_loss_months).
    all_df["_active_month"] = all_df["month"].where(all_df["_srank"] == 1, "")
    # Was this person ever seen in a HealthSherpa (FFM) export? If so they're an
    # FFM client and carrier-truth should reconcile them; if they only ever came
    # from a state-based-marketplace (access) export, carrier-truth must leave
    # them alone (they're legitimately absent from the FFM carrier-portal files).
    # Missing source (legacy snapshots) defaults to HS to preserve old behavior.
    all_df["_is_hs"] = (
        all_df["source"].astype(str).str.lower() != "access"
        if "source" in all_df.columns else True
    )
    all_df["effective_date"] = pd.to_datetime(all_df.get("effective_date"), errors="coerce")
    all_df["term_date"]      = pd.to_datetime(all_df.get("term_date"),      errors="coerce")
    all_df["submission_date"] = pd.to_datetime(all_df.get("submission_date"), errors="coerce")

    # COVERAGE-END loss date. HealthSherpa's date_cancelled (term_date) is the day HS
    # PROCESSED a termination, not the day coverage ended — its Oct 7-9 2026 re-sync
    # stamped 10/08-10/09 on plans that ended months earlier, so Re-Engage showed the
    # whole wave as lost "<30 days" and churn landed in the wrong month.
    # expiration_date (coverage_end) is the real last day in force. Trust it ONLY:
    #   - in the NEWEST snapshot (snapshots ingested before this change don't carry
    #     the column → NaT → old behavior until the agent's next upload);
    #   - on the person's NEWEST plan there (an older plan's mid-year end must not
    #     stand in for it);
    #   - on Terminated rows (active and Cancelled rows carry a 12/31 default);
    #   - when it's not another agent's policy (a stolen client's row is the OTHER
    #     agent's plan — the AOR rules + assign_loss_months date those);
    #   - not in the future, not a 12/31 plan-year end, not before the plan started;
    #   - not before the start of any plan the snapshots ever showed ACTIVE (the
    #     re-sync swapped an older, terminated policy back into some export rows).
    _cov_raw = (pd.to_datetime(all_df["coverage_end"], errors="coerce")
                if "coverage_end" in all_df.columns
                else pd.Series(pd.NaT, index=all_df.index, dtype="datetime64[ns]"))
    # "Newest" = the newest month that holds HealthSherpa rows: a state-exchange book
    # uploaded first in a new month must not switch coverage dating off.
    _hs_months = all_df.loc[all_df["_is_hs"].astype(bool), "month"]
    _hs_latest = _hs_months.max() if len(_hs_months) else max(months.keys())
    _in_latest = (all_df["month"] == _hs_latest) & all_df["_is_hs"].astype(bool)
    # Compare against the real start day where ingest carried it (older snapshots
    # only have the month-rounded effective_date).
    _start = (pd.to_datetime(all_df["plan_start"], errors="coerce")
              if "plan_start" in all_df.columns
              else pd.Series(pd.NaT, index=all_df.index, dtype="datetime64[ns]")).fillna(all_df["effective_date"])
    _newest_idx = (all_df.loc[_in_latest, ["_pkey", "effective_date"]]
                   .assign(_ce=_cov_raw[_in_latest])
                   .sort_values(["_pkey", "effective_date", "_ce"], na_position="first")
                   .groupby("_pkey").tail(1).index)
    _max_active_eff = all_df["_pkey"].map(
        _start[all_df["_srank"] == 1].groupby(all_df.loc[all_df["_srank"] == 1, "_pkey"]).max())
    _npn = str(npn or "").strip()
    _parts = [p for p in (name or "").lower().split() if p]

    def _foreign_aor(a) -> bool:
        al = str(a or "").strip().lower()
        if al in ("", "nan") or "none" in al:
            return False              # blank / disconnected = still the agent's
        if _npn and _npn in al:
            return False
        if _parts and all(p in al for p in _parts):
            return False
        return True                   # someone else (or no identity to judge by)

    _foreign = (all_df["policy_aor"].apply(_foreign_aor)
                if "policy_aor" in all_df.columns else pd.Series(False, index=all_df.index))
    _cov_ok = (
        _in_latest
        & all_df.index.isin(_newest_idx)
        & (all_df["status"] == "Terminated")
        & ~_foreign
        & _cov_raw.notna()
        & (_cov_raw <= pd.Timestamp.today().normalize())
        & ~((_cov_raw.dt.month == 12) & (_cov_raw.dt.day == 31))
        & (_start.isna() | (_cov_raw >= _start))
        & (_max_active_eff.isna() | (_cov_raw >= _max_active_eff))
    )
    all_df["_cov_end"] = _cov_raw.where(_cov_ok)

    # Sort: oldest month first, within same month inactive before active
    # → "last" in each group = most recent month, most active row
    all_df = all_df.sort_values(["_pkey", "month", "_srank"])

    # Fields that come from the most-recent (last) row
    last_fields = {
        col: (col, "last")
        for col in [
            "client_name", "first_name", "last_name", "carrier",
            "state", "ffm_app_id", "ffm_subscriber_id", "net_premium", "subsidy", "applicant_count",
            "status", "client_key", "email", "phone", "cancel_notes",
            # HealthSherpa verification follow-ups — carry latest snapshot's values
            "dmi_outstanding", "dmi_expired", "svi_outstanding", "svi_expired", "followup_docs",
            # current agent of record (for AOR-taken detection on Re-Engage)
            "policy_aor", "last_ede_sync",
            # carrier-assigned policy ID (member's card) — most recent plan's
            "policy_number",
        ]
        if col in all_df.columns
    }

    agg = (
        all_df.groupby("_pkey")
        .agg(
            first_seen        = ("month",          "min"),
            last_seen         = ("month",          "max"),
            last_active       = ("_active_month",  "max"),  # last month seen ACTIVE
            effective_date    = ("effective_date", "min"),   # earliest plan start (tenure)
            current_effective = ("effective_date", "last"),  # most-recent active plan start (dispute/commission timing)
            submission_date   = ("submission_date", "min"),  # first time they signed with us
            _term_date_last   = ("term_date",      "last"),  # most recent term_date
            _has_active       = ("_srank",         "max"),   # 1 if any active plan exists
            _has_hs           = ("_is_hs",         "max"),   # seen in any HS export?
            _cov_end          = ("_cov_end",       "max"),   # newest plan's trusted coverage end
            **last_fields,
        )
        .reset_index()
        .rename(columns={"_pkey": "name_key"})
    )

    # term_date: NaT when the person still has an active plan
    agg["term_date"] = agg["_term_date_last"].where(agg["_has_active"] == 0, other=pd.NaT)
    # A gone person whose newest HS plan passed every coverage-end test above is dated
    # by THAT day — ever-active clients (date blanked just above) and never-active ones
    # (whose date_cancelled may be the re-sync stamp) alike. It's a real date, so
    # assign_loss_months keeps it (term_estimated stays False).
    _use_cov = agg["status"].isin(["Cancelled", "Terminated"]) & agg["_cov_end"].notna()
    agg["coverage_end"] = agg["_cov_end"].where(_use_cov)
    agg["term_date"] = agg["term_date"].where(~_use_cov, agg["_cov_end"])
    # source: "healthsherpa" if seen in any FFM export, else "access" (exchange-only)
    agg["source"] = agg["_has_hs"].map(lambda x: "healthsherpa" if x else "access")
    agg = agg.drop(columns=["_term_date_last", "_has_active", "_has_hs", "_cov_end"])

    # months_on_book: calendar months from effective_date to the latest snapshot month
    latest       = max(months.keys())
    latest_y     = int(latest[:4])
    latest_m     = int(latest[5:7])

    def _calendar_months(eff_date) -> Optional[int]:
        try:
            eff = pd.Timestamp(eff_date)
            if pd.isna(eff):
                return None
            # completed months (matches report.py's day-aware tenure)
            return max((latest_y - eff.year) * 12 + (latest_m - eff.month), 0)
        except Exception:
            return None

    agg["months_on_book"] = agg["effective_date"].apply(_calendar_months)

    cols = [
        "name_key", "client_key", "first_name", "last_name", "carrier",
        "effective_date", "current_effective", "term_date", "status", "state", "ffm_app_id", "ffm_subscriber_id",
        "email", "phone", "cancel_notes", "net_premium", "subsidy", "applicant_count", "first_seen", "last_seen", "last_active", "months_on_book",
        "dmi_outstanding", "dmi_expired", "svi_outstanding", "svi_expired", "followup_docs",
        "policy_aor", "last_ede_sync", "policy_number", "submission_date", "source",
        "coverage_end",
    ]
    return agg[[c for c in cols if c in agg.columns]]


def assign_loss_months(all_clients: pd.DataFrame, last_paid=None) -> pd.DataFrame:
    """Give every gone client a real loss date so churn/loss math counts them.

    A client marked Cancelled/Terminated (AOR-taken, verification-expired, left-book,
    or an undated cancellation) often has NO term_date. The MoM engine dates losses by
    term_date, so a dateless gone client was counted ACTIVE forever and never registered
    as a loss — understating churn and overstating LTV.

    For each gone client with no real carrier cancel date, find the month the agent's
    commission stopped, matched to the commission records in this priority:
      1. by POLICY ID (exact) — name-independent, so misspelled / nickname / maiden
         names still match;
      2. by name_key (first+last letters, exact);
      3. by FUZZY name within the SAME carrier brand (corroborated so two different
         people aren't linked).
    If no commission match: exchange sync (last_ede_sync), then last month a snapshot
    showed them active. Never dated later than the current month. Plan switches skipped.

    `last_paid` = {"by_policy": {policy: 'YYYY-MM'}, "by_name": {name_key: 'YYYY-MM'},
    "by_carrier_names": {brand: {name_key: 'YYYY-MM'}}}; a flat {name_key: month} also OK.

    Must run AFTER all status rules (carrier-truth, AOR, verification, left-book, switch).
    """
    if all_clients is None or all_clients.empty or "status" not in all_clients.columns:
        return all_clients
    import re, difflib
    df = all_clients
    lp = last_paid if isinstance(last_paid, dict) else {}
    if "by_policy" in lp or "by_name" in lp or "by_carrier_names" in lp:
        by_policy = lp.get("by_policy", {}) or {}
        by_name   = lp.get("by_name", {}) or {}
        by_carrier = lp.get("by_carrier_names", {}) or {}
    else:
        by_policy, by_name, by_carrier = {}, dict(lp), {}
    churned = {"Cancelled", "Terminated"}
    if "term_estimated" not in df.columns:
        df["term_estimated"] = False
    if "term_date" not in df.columns:
        df["term_date"] = pd.NaT

    def _as_bool(v) -> bool:
        return v if isinstance(v, bool) else str(v).strip().lower() in ("true", "1", "yes", "t")

    def _pk(f, l) -> str:
        return re.sub(r"[^a-z]", "", f"{f}{l}".lower())

    def _polnorm(x) -> str:
        return re.sub(r"[^0-9a-z]", "", str(x).lower())

    def _brand(c) -> str:
        c = str(c).lower()
        for kw, b in (("ambetter", "ambetter"), ("oscar", "oscar"), ("wellpoint", "anthem"),
                      ("anthem", "anthem"), ("unitedhealth", "uhc"), ("united health", "uhc"),
                      ("uhc", "uhc"), ("cigna", "cigna"), ("molina", "molina"),
                      ("selecthealth", "selecthealth"), ("select health", "selecthealth"),
                      ("blue", "bcbs"), ("bcbs", "bcbs")):
            if kw in c:
                return b
        return re.sub(r"[^a-z]", "", c)[:10] or "other"

    def _valid(m) -> bool:
        return isinstance(m, str) and len(m) >= 7 and m[:4].isdigit() and m[4] == "-"

    term   = pd.to_datetime(df.get("term_date"), errors="coerce")
    est    = df["term_estimated"].apply(_as_bool)
    reason = df.get("cancel_reason", pd.Series("", index=df.index)).fillna("").astype(str).str.lower()
    sync   = pd.to_datetime(df.get("last_ede_sync"), format="%m/%d/%Y %H:%M:%S", errors="coerce")
    sync   = sync.fillna(pd.to_datetime(df.get("last_ede_sync"), errors="coerce"))
    fn = df.get("first_name", pd.Series("", index=df.index)).fillna("").astype(str)
    ln = df.get("last_name",  pd.Series("", index=df.index)).fillna("").astype(str)
    pol = df.get("policy_number", pd.Series("", index=df.index)).fillna("").astype(str)
    carr = df.get("carrier", pd.Series("", index=df.index)).fillna("").astype(str)
    la = df.get("last_active", pd.Series(pd.NA, index=df.index)).astype(str)
    fs = df.get("first_seen",  pd.Series(pd.NA, index=df.index)).astype(str)
    cur = pd.Timestamp.today().to_period("M")

    # loss_basis says HOW a dateless loss was dated: "commission" (pay stopped = a
    # confirmed month) vs "sync"/"active" (only WHEN the drop was noticed — an
    # exchange re-sync like Oct 7-9 2026 stamps ~today on months-old losses).
    # Re-Engage (core/views.losses) keeps sync/active rows off the outreach list;
    # churn still counts them. "" = a real cancel date.
    if "loss_basis" not in df.columns:
        df["loss_basis"] = ""
    df["loss_basis"] = df["loss_basis"].fillna("").astype(str)
    gone      = df["status"].isin(churned)
    is_switch = reason.str.contains("switch")          # plan switch = retention, skip
    has_real  = gone & term.notna() & ~est             # real carrier cancel date — keep
    need      = gone & ~has_real & ~is_switch          # these need a loss date

    def _clamp(mstr):
        p = pd.Period(mstr[:7], freq="M")
        return p if p <= cur else cur

    def _set(idx, mstr, basis):
        df.at[idx, "term_date"] = _clamp(mstr).to_timestamp("M")
        df.at[idx, "term_estimated"] = False
        df.at[idx, "loss_basis"] = basis

    for idx in df.index[need]:
        nk = _pk(fn.at[idx], ln.at[idx])
        pn = _polnorm(pol.at[idx])
        mm = by_policy.get(pn) if len(pn) >= 5 else None
        if _valid(mm): _set(idx, mm, "commission"); continue
        mm = by_name.get(nk)
        if _valid(mm): _set(idx, mm, "commission"); continue
        pool = by_carrier.get(_brand(carr.at[idx]), {})
        if pool and len(nk) >= 4:
            best_m, best_r = None, 0.0
            for cand_nk, cand_m in pool.items():
                r = difflib.SequenceMatcher(None, nk, cand_nk).ratio()
                if r > best_r:
                    best_r, best_m = r, cand_m
            if best_r >= 0.88 and _valid(best_m): _set(idx, best_m, "commission"); continue
        if pd.notna(sync.at[idx]):
            _set(idx, sync.at[idx].strftime("%Y-%m"), "sync"); continue
        anchor = la.at[idx] if _valid(la.at[idx]) else fs.at[idx]
        if _valid(anchor): _set(idx, anchor, "active")
    return df


def build_history_pivot(months: dict) -> pd.DataFrame:
    """
    Month-by-month commission pivot: rows = clients, columns = months.
    """
    from tracker.ingest import match_client_id

    frames = []
    for month_key in sorted(months.keys()):
        df = match_client_id(months[month_key])[["client_key", "client_name", "commission"]].copy()
        df["month"] = month_key
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    pivot = combined.pivot_table(
        index=["client_key", "client_name"],
        columns="month",
        values="commission",
        aggfunc="sum",
        fill_value=0,
    ).reset_index()
    pivot.columns.name = None
    return pivot
