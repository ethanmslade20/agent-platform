"""Actual paid-commission ingestion — format-agnostic across agents.

Every agent's commission statement is shaped differently (different carriers,
different uplines/FMOs, different columns, different grain), so we never hardcode
a format. Instead we define ONE canonical record:

    { client, carrier, period (YYYY-MM), amount, source_file }

and let each agent map their file's columns to it once. The mapping is
auto-detected from the headers, confirmed in the UI, and saved per-tenant keyed
by the file's header signature — so the next upload of the same statement shape
auto-applies. Everything downstream (KPIs, by-carrier, by-month) reads only the
canonical records, so it works no matter how the source file was organized.
"""
from __future__ import annotations

import io
import json
import re
from pathlib import Path

import pandas as pd

from core import carrier_names, paths, store

# Canonical target fields the UI maps columns onto. (key, label, required)
CANON = [
    ("amount",      "Commission amount ($)", True),
    ("carrier",     "Carrier",               False),
    ("period",      "Payment date / month",  False),
    ("client",      "Client name",           False),
    ("policy_id",   "Policy / member ID",    False),
]

# Header keyword → canonical field, most-specific first. Lowercased substring match.
_HINTS = {
    "amount": ["commission amount", "commission paid", "commission", "amount paid",
               "paid amount", "payment amount", "net pay", "net amount", "payout",
               "earnings", "amount", "paid", "payment", "total"],
    "carrier": ["carrier", "issuer", "insurance company", "company", "insurer", "plan carrier"],
    "period": ["pay date", "paid date", "paid on", "payment date", "statement date",
               "period", "pay period", "month", "date"],
    "client": ["client name", "member name", "insured name", "subscriber name",
               "enrollee", "client", "member", "insured", "subscriber", "name"],
    "policy_id": ["subscriber id", "member id", "policy number", "policy id",
                  "certificate", "policy", "contract"],
}

_MONEY_RE = re.compile(r"[^0-9.\-]")

# A row whose client cell is one of these is a statement total/footer, not a real
# commission line — drop it so it doesn't double the sum (common in PDFs/exports).
_SUMMARY_RE = re.compile(
    r"^\s*(grand\s*total|sub\s*total|totals?|sum|balance|amount\s*due|"
    r"total\s*(commission|paid|due|amount))\s*:?\s*$", re.I)


def _norm(s) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())


# Column-label words that mark a header row — lets us skip a statement's title
# block (agent name, "Commission Statement", totals) and find the real header.
_HEADER_WORDS = {
    "agent", "npn", "carrier", "issuer", "company", "insurer", "policy", "member",
    "insured", "subscriber", "client", "name", "commission", "amount", "paid",
    "payment", "premium", "effective", "pay", "period", "date", "state", "product",
    "plan", "description", "subscribers", "id", "metal", "county", "enroll",
}


def read_table(data: bytes, filename: str) -> pd.DataFrame:
    """Read a commission file (CSV, Excel, or PDF) into a DataFrame of raw columns.

    Handles a leading title/preamble block by auto-finding the real header row
    (FMO statements start with agent name, "Commission Statement", totals, etc.).
    PDFs are best-effort table extraction — the mapping step lets the agent fix any
    columns that came out shifted, which is the whole point of the wizard.
    """
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        return read_pdf(data)
    if name.endswith((".xlsx", ".xls")):
        raw = pd.read_excel(io.BytesIO(data), header=None, dtype=str)
    else:
        raw = pd.read_csv(io.BytesIO(data), header=None, dtype=str)
    return _locate_and_frame(raw)


def _find_header_row(raw: pd.DataFrame) -> int:
    """Index of the row that looks most like the column header (most cells that
    are known column-label words). Falls back to the first row."""
    best_i, best_score = 0, 0
    for i in range(min(len(raw), 25)):
        cells = [_clean_cell(c).lower() for c in raw.iloc[i].tolist()]
        nonempty = [c for c in cells if c]
        if len(nonempty) < 2:
            continue
        score = sum(1 for c in nonempty
                    if any(re.search(rf"\b{w}\b", c) for w in _HEADER_WORDS))
        if score > best_score:
            best_score, best_i = score, i
    return best_i


def _locate_and_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """Turn a header-less raw read into a clean DataFrame: drop blank rows, find
    the header row, use it as columns, and clean every cell."""
    raw = raw.dropna(how="all").reset_index(drop=True)
    if raw.empty:
        return pd.DataFrame()
    h = _find_header_row(raw)
    header = _dedupe_headers(list(raw.iloc[h]))
    body = raw.iloc[h + 1:].reset_index(drop=True)
    body.columns = header
    body = body.map(_clean_cell)
    body = body[body.apply(lambda r: any(v for v in r), axis=1)].reset_index(drop=True)
    return body


def _clean_cell(c) -> str:
    s = re.sub(r"\s+", " ", str(c if c is not None else "").replace("\n", " ")).strip()
    return "" if s.lower() in ("nan", "none", "nat") else s


def _dedupe_headers(cells: list) -> list:
    out, seen = [], {}
    for i, c in enumerate(cells):
        name = _clean_cell(c) or f"Column {i + 1}"
        if name in seen:
            seen[name] += 1
            name = f"{name} ({seen[name]})"
        else:
            seen[name] = 0
        out.append(name)
    return out


def _header_is_data(cells: list) -> bool:
    """True when the 'header' row is really data (few word-like cells) — e.g. a PDF
    table whose column titles didn't extract, so row 1 is the first record."""
    wordy = sum(1 for c in cells if re.search(r"[A-Za-z]{3,}", str(c)))
    return wordy < max(2, len(cells) // 2)


def _frame_from_rows(rows: list) -> pd.DataFrame:
    """Build a DataFrame from extracted rows, inferring whether row 0 is a header."""
    rows = [r for r in rows if any(_clean_cell(c) for c in r)]
    if not rows:
        return pd.DataFrame()
    head = [_clean_cell(c) for c in rows[0]]
    if _header_is_data(head):
        cols = [f"Column {i + 1}" for i in range(len(head))]
        body = rows
    else:
        cols = _dedupe_headers(head)
        body = rows[1:]
    body = [r for r in body if [_clean_cell(c) for c in r] != head]  # drop repeated headers
    body = [(list(r) + [""] * len(cols))[:len(cols)] for r in body]   # pad/trim ragged rows
    return pd.DataFrame([[_clean_cell(c) for c in r] for r in body], columns=cols)


def read_pdf(data: bytes) -> pd.DataFrame:
    """Extract a commission table from a PDF. Tries ruled/unruled tables first
    (concatenating the same table shape across pages), then a text-line fallback."""
    try:
        import pdfplumber
    except Exception as e:
        raise ValueError(f"PDF support isn't available on this server ({e}). "
                         "Export your statement as CSV or Excel instead.")
    from collections import Counter

    tables = []
    text_lines = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            for tbl in (page.extract_tables() or []):
                if tbl and len(tbl) >= 1 and len(tbl[0]) >= 2:
                    tables.append(tbl)
            txt = page.extract_text() or ""
            text_lines += [ln for ln in txt.split("\n") if ln.strip()]

    if tables:
        widths = Counter(len(t[0]) for t in tables)
        best_w = widths.most_common(1)[0][0]
        rows = [row for t in tables if len(t[0]) == best_w for row in t]
        df = _frame_from_rows(rows)
        if not df.empty:
            return df

    # Fallback: reconstruct a table from text lines split on runs of 2+ spaces.
    split = [re.split(r"\s{2,}", ln.strip()) for ln in text_lines]
    cnt = Counter(len(r) for r in split if len(r) >= 2)
    if cnt:
        w = cnt.most_common(1)[0][0]
        rows = [r for r in split if len(r) == w]
        if len(rows) >= 2:
            return _frame_from_rows(rows)

    raise ValueError("Couldn't find a table in that PDF. If it's a scanned image, "
                     "export the statement as CSV/Excel instead.")


def header_sig(df: pd.DataFrame) -> str:
    """Stable signature of a file's shape so a saved mapping can be re-matched."""
    return "|".join(sorted(_norm(c) for c in df.columns))


def detect(df: pd.DataFrame) -> dict:
    """Best-guess {canon_field: source_column or None} from the headers."""
    cols = list(df.columns)
    lc = {c: _norm(c) for c in cols}
    used, mapping = set(), {}
    for field, hints in _HINTS.items():
        best = None
        for hint in hints:                       # earlier hint = higher priority
            for c in cols:
                if c in used:
                    continue
                if hint == lc[c] or hint in lc[c]:
                    best = c
                    break
            if best:
                break
        if best:
            mapping[field] = best
            used.add(best)
        else:
            mapping[field] = None
    # If no amount column matched by name, fall back to the most $-looking numeric column.
    if not mapping.get("amount"):
        best, best_score = None, 0
        for c in cols:
            if c in used:
                continue
            vals = df[c].astype(str).head(50)
            score = sum(bool(re.search(r"[\d].*\.\d|\$", v)) for v in vals)
            if score > best_score:
                best, best_score = c, score
        if best and best_score >= 3:
            mapping["amount"] = best
    return mapping


def _money(v) -> float:
    s = str(v).strip()
    if not s or s.lower() in ("nan", "none", "-", "--"):
        return 0.0
    neg = s.startswith("(") and s.endswith(")")   # (123.45) = -123.45
    s = _MONEY_RE.sub("", s)
    if s in ("", ".", "-"):
        return 0.0
    try:
        val = float(s)
    except ValueError:
        return 0.0
    return -val if neg else val


def parse(df: pd.DataFrame, mapping: dict, source_file: str) -> pd.DataFrame:
    """Turn a raw file + column mapping into canonical commission records."""
    amt_col = mapping.get("amount")
    if not amt_col or amt_col not in df.columns:
        raise ValueError("Pick which column holds the commission amount.")

    out = pd.DataFrame()
    out["amount"] = df[amt_col].apply(_money)

    car_col = mapping.get("carrier")
    if car_col and car_col in df.columns:
        out["carrier"] = df[car_col].apply(lambda c: carrier_names.brand_of(c) if str(c).strip() else "Unknown")
    else:
        out["carrier"] = "Unknown"

    per_col = mapping.get("period")
    if per_col and per_col in df.columns:
        dts = pd.to_datetime(df[per_col], errors="coerce")
        out["period"] = dts.dt.strftime("%Y-%m").fillna("Unknown")
    else:
        out["period"] = "Unknown"

    cli_col = mapping.get("client")
    out["client"] = df[cli_col].astype(str).str.strip() if (cli_col and cli_col in df.columns) else ""

    pid_col = mapping.get("policy_id")
    out["policy_id"] = df[pid_col].astype(str).str.strip() if (pid_col and pid_col in df.columns) else ""

    out["source_file"] = source_file
    # Drop statement total/footer lines (client cell is "Total", "Grand Total", …)
    # so they don't double the sum.
    out = out[~out["client"].astype(str).str.match(_SUMMARY_RE)]
    # Drop $0 rows — footers/blank lines. Negative amounts (chargebacks) are real
    # money movement and are kept.
    out = out[out["amount"] != 0].reset_index(drop=True)
    return out


# ── persistence ───────────────────────────────────────────────────────────────
def _records_path(agent_id: str) -> Path:
    return paths.data_dir(agent_id) / "commissions.parquet"


def _maps_path(agent_id: str) -> Path:
    return paths.data_dir(agent_id) / "commission_maps.json"


def _hydrate_if_needed(agent_id: str, p: Path) -> None:
    if store.using_db() and not p.exists():
        store.hydrate(agent_id, paths.tenant_root(agent_id))


def load_records(agent_id: str) -> pd.DataFrame:
    p = _records_path(agent_id)
    _hydrate_if_needed(agent_id, p)
    if p.exists():
        try:
            return pd.read_parquet(p)
        except Exception:
            pass
    return pd.DataFrame(columns=["amount", "carrier", "period", "client", "policy_id", "source_file"])


def saved_maps(agent_id: str) -> dict:
    p = _maps_path(agent_id)
    _hydrate_if_needed(agent_id, p)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}


def save_records(agent_id: str, new_records: pd.DataFrame, mapping: dict, sig: str) -> int:
    """Append canonical records, replacing any prior rows from the same file
    (so re-uploading a corrected statement doesn't double-count). Saves the
    column mapping under the file's header signature for next time. Returns the
    running total row count."""
    import hashlib
    paths.ensure_dirs(agent_id)
    src = new_records["source_file"].iloc[0] if len(new_records) else ""
    # Content signature so the SAME statement re-downloaded under a "(1)" filename
    # can't double-count — dedup on content as well as on filename.
    if len(new_records):
        key_cols = [c for c in ["client", "carrier", "period", "amount", "policy_id"]
                    if c in new_records.columns]
        bid = hashlib.md5(pd.util.hash_pandas_object(
            new_records[key_cols], index=False).values.tobytes()).hexdigest()[:12]
    else:
        bid = ""
    new_records = new_records.copy()
    new_records["batch_id"] = bid

    existing = load_records(agent_id)
    if not existing.empty:
        if "source_file" not in existing.columns:
            existing["source_file"] = ""
        if "batch_id" not in existing.columns:
            existing["batch_id"] = ""
        existing = existing[(existing["source_file"] != src) & (existing["batch_id"] != bid)]
    combined = pd.concat([existing, new_records], ignore_index=True)

    rp = _records_path(agent_id)
    combined.to_parquet(rp, index=False)
    if store.using_db():
        store.put_file(agent_id, "data/commissions.parquet", rp.read_bytes())

    maps = saved_maps(agent_id)
    maps[sig] = mapping
    mp = _maps_path(agent_id)
    mp.write_text(json.dumps(maps, indent=2))
    if store.using_db():
        store.put_file(agent_id, "data/commission_maps.json", mp.read_bytes())

    from core import ingest_service
    ingest_service._record_upload(agent_id, "commissions")
    return len(combined)


def summary(records: pd.DataFrame) -> dict:
    """Totals for the Money Received view: grand total, this-month, by carrier, by month."""
    if records is None or records.empty:
        return {"total": 0.0, "this_month": 0.0, "by_carrier": pd.DataFrame(), "by_month": pd.DataFrame()}
    amt = pd.to_numeric(records["amount"], errors="coerce").fillna(0.0)
    total = float(amt.sum())

    by_carrier = (records.assign(amount=amt).groupby("carrier")["amount"].sum()
                  .sort_values(ascending=False).reset_index())
    by_carrier.columns = ["Carrier", "Paid"]

    bm = records.assign(amount=amt)
    bm = bm[bm["period"] != "Unknown"]
    by_month = (bm.groupby("period")["amount"].sum().sort_index().reset_index()
                if not bm.empty else pd.DataFrame(columns=["period", "amount"]))
    by_month.columns = ["Month", "Paid"]

    this_month = 0.0
    if not by_month.empty:
        latest = by_month["Month"].max()
        this_month = float(by_month.loc[by_month["Month"] == latest, "Paid"].sum())

    return {"total": total, "this_month": this_month,
            "by_carrier": by_carrier, "by_month": by_month}


# ── reconciliation: who in the book am I actually getting paid on? ───────────────
def _nk(first, last) -> str:
    return re.sub(r"[^a-z]", "", f"{first}{last}".lower())


def _nk_str(name) -> str:
    """Name key from a free-form statement name — handles 'Last, First', 'First Last',
    and drops a trailing 'Family'/'Household'."""
    s = str(name).strip()
    s = re.sub(r"\b(family|household)\b", "", s, flags=re.I).strip()
    if "," in s:
        last, first = s.split(",", 1)
        fp = first.strip().split()
        return _nk(fp[0] if fp else "", last.strip())
    parts = s.split()
    if len(parts) >= 2:
        return _nk(parts[0], parts[-1])
    return re.sub(r"[^a-z]", "", s.lower())


def _idk(x) -> str:
    v = re.sub(r"[^0-9a-z]", "", str(x).lower())
    return v if len(v) >= 4 else ""     # ignore trivially-short ids


def _mdiff(a: str, b: str) -> int:
    try:
        return (int(a[:4]) - int(b[:4])) * 12 + (int(a[5:7]) - int(b[5:7]))
    except Exception:
        return 0


def reconcile(roster, records, pmpm: int = 23) -> dict:
    """Cross-check the active book against paid-commission records.

    Match a client to a payment by policy/member ID (strong) or full name (handles
    'Last, First'). A client is a GAP if active in the book but either never paid
    or paid before with nothing in the last 2 statement months ("Stopped" — the
    dispute signal). Matching is deliberately strict: a false gap is a quick verify,
    but a false "paid" would HIDE money you're owed.

    Returns {reconcilable, active, paid, gaps(df), monthly_gap, unmatched}.
    Not reconcilable when statements carry no client name or ID (lump sums).
    """
    out = {"reconcilable": False, "active": 0, "paid": 0,
           "gaps": pd.DataFrame(), "monthly_gap": 0.0, "unmatched": 0}
    if roster is None or records is None or records.empty:
        return out
    from core import views
    active = views.active(roster)
    if active is None or active.empty:
        return out
    usable = records[(records["client"].astype(str).str.strip() != "")
                     | (records["policy_id"].astype(str).str.strip() != "")]
    if usable.empty:
        return out           # carrier-level lump sums → no per-client reconciliation

    out["reconcilable"], out["active"] = True, len(active)

    paid_name, paid_id = {}, {}
    for _, r in usable.iterrows():
        per = str(r.get("period", ""))
        per = "" if per == "Unknown" else per
        nk = _nk_str(r.get("client", "")) if str(r.get("client", "")).strip() else ""
        if nk:
            paid_name[nk] = max(paid_name.get(nk, ""), per)
        idk = _idk(r.get("policy_id", ""))
        if idk:
            paid_id[idk] = max(paid_id.get(idk, ""), per)

    months = [p for p in usable["period"].tolist() if p != "Unknown"]
    latest = max(months) if months else ""

    rows, paid_current, matched_names = [], 0, set()
    for _, c in active.iterrows():
        nk = _nk(c.get("first_name", ""), c.get("last_name", ""))
        ids = [i for i in (_idk(c.get("ffm_subscriber_id", "")), _idk(c.get("policy_number", ""))) if i]
        last_paid, hit = "", False
        if nk and nk in paid_name:
            hit = True; last_paid = max(last_paid, paid_name[nk]); matched_names.add(nk)
        for i in ids:
            if i in paid_id:
                hit = True; last_paid = max(last_paid, paid_id[i])
        mem = pd.to_numeric(c.get("applicant_count"), errors="coerce")
        mem = 1 if pd.isna(mem) else max(int(mem), 1)

        if not hit:
            status = "Never paid"
        elif latest and last_paid and _mdiff(latest, last_paid) >= 2:
            status = "Stopped"
        else:
            paid_current += 1
            continue
        rows.append({
            "Client": f"{c.get('first_name','')} {c.get('last_name','')}".strip(),
            "Carrier": c.get("carrier", ""), "State": str(c.get("state", "") or ""),
            "Members": mem, "Est $/mo": mem * pmpm, "Status": status,
            "Last Paid": last_paid or "—", "Phone": str(c.get("phone", "") or ""),
        })

    g = pd.DataFrame(rows)
    if not g.empty:
        # Never paid first, then biggest dollars — chase the largest fresh gaps first.
        g = g.sort_values(["Status", "Est $/mo"], ascending=[True, False]).reset_index(drop=True)
    out["paid"] = paid_current
    out["gaps"] = g
    out["monthly_gap"] = float(g["Est $/mo"].sum()) if not g.empty else 0.0
    out["unmatched"] = int(sum(1 for k in paid_name if k not in matched_names))
    return out
