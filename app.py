"""Agent Platform — multi-tenant app.

Phase 1: sign-in gate + per-tenant isolation.
Phase 2: in-app upload (HealthSherpa builds the book; carriers stored for reconciliation)
         and a first look at the agent's book, all scoped to their own workspace.
"""
import pandas as pd
import streamlit as st

from core import charts, dashboard_kpis, ingest_service, paths, tenants, ui, views

# The product name your agents see. Placeholder — change it here anytime.
APP_NAME = "Agent Book"

st.set_page_config(page_title=APP_NAME, page_icon="📘", layout="wide")

ui.inject_css()  # Ethan's midnight-fintech theme (cards, sidebar, typography)
st.markdown(
    """
    <style>
      [data-testid="stSidebarNav"]{display:none}
      .login-card{max-width:380px;margin:8vh auto 0}
      .brand{font-size:1.9rem;font-weight:800;letter-spacing:-.02em;margin:0}
      .brand-sub{color:#8a94a6;margin:.35rem 0 1.4rem;font-size:.95rem}
      .ws{color:#8a94a6;font-size:.85rem}
    </style>
    """,
    unsafe_allow_html=True,
)

if "tenant" not in st.session_state:
    st.session_state.tenant = None


# ── Auth ────────────────────────────────────────────────────────────────────
def login_screen() -> None:
    st.markdown('<div class="login-card">', unsafe_allow_html=True)
    st.markdown(f'<p class="brand">📘 {APP_NAME}</p>', unsafe_allow_html=True)
    st.markdown('<p class="brand-sub">Sign in to your book.</p>', unsafe_allow_html=True)
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", use_container_width=True)
    if submitted:
        tenant = tenants.verify(username, password)
        if tenant:
            paths.ensure_dirs(tenant["agent_id"])
            st.session_state.tenant = tenant
            st.rerun()
        else:
            st.error("Wrong username or password.")
    st.markdown("</div>", unsafe_allow_html=True)


# ── Pages ───────────────────────────────────────────────────────────────────
def page_upload(tenant: dict) -> None:
    agent_id = tenant["agent_id"]
    st.title("Upload your files")
    st.caption(
        "HealthSherpa builds your whole book. The carrier files add your payments, "
        "disputes, and policy IDs on top."
    )

    st.subheader("HealthSherpa export  ·  required")
    st.caption("Clients → Export · Custom date range 01/01/2025 → today · both boxes checked.")
    hs = st.file_uploader("HealthSherpa (.csv)", type=["csv"], key="hs")
    if hs is not None and st.button("Build my book from this file", type="primary"):
        try:
            with st.spinner("Reading your export and building your book…"):
                _snap, df = ingest_service.ingest_healthsherpa(
                    agent_id, hs.getvalue(), npn=tenant.get("npn", ""), name=tenant.get("name", "")
                )
            if len(df) == 0:
                st.warning(
                    f"We read the file, but no clients came back under your NPN "
                    f"({tenant.get('npn') or '—'}). Double-check this is your HealthSherpa "
                    f"export and that your NPN is correct on your account.",
                    icon="⚠️",
                )
            else:
                st.success(f"Done — read {len(df):,} rows. Your book is on the **My Book** page.")
                st.session_state["nav"] = "My Book"
        except (Exception, SystemExit) as e:
            st.error(f"Couldn't read that file: {e}")

    st.divider()
    st.subheader("Carrier books  ·  optional")
    st.caption("Add these to unlock the payment & dispute checks. Stored privately in your workspace.")
    cols = st.columns(2)
    for i, (key, spec) in enumerate(ingest_service.carriers().items()):
        with cols[i % 2]:
            up = st.file_uploader(f"{spec['label']} (.{spec['types'][0]})", type=spec["types"], key=key)
            if up is not None:
                try:
                    ingest_service.save_carrier(agent_id, key, up.getvalue())
                    st.success(f"{spec['label']} saved ✓")
                except Exception as e:
                    st.error(f"{spec['label']}: {e}")


_NAMES = {"first_name": "First", "last_name": "Last", "carrier": "Carrier",
          "state": "State", "status": "Status", "effective_date": "Effective",
          "term_date": "Ended", "taken_by": "Now with"}


def _table(df: pd.DataFrame, cols: list, empty: str) -> None:
    if df is None or df.empty:
        st.info(empty)
        return
    show = [c for c in cols if c in df.columns]
    st.dataframe(df[show].rename(columns=_NAMES), use_container_width=True, hide_index=True)


def _need_book() -> None:
    st.info("No book yet — upload your HealthSherpa export on the **Upload** page.", icon="📥")


def _cards(htmls: list) -> None:
    for col, html in zip(st.columns(len(htmls)), htmls):
        col.markdown(html, unsafe_allow_html=True)


def _hdr(title: str, icon: str) -> None:
    st.markdown(ui.section_header(title, icon), unsafe_allow_html=True)


def _stat(html: str) -> None:
    st.columns(3)[0].markdown(html, unsafe_allow_html=True)


def page_dashboard(tenant: dict, roster) -> None:
    st.title("Dashboard")
    d = dashboard_kpis.compute(tenant["agent_id"], roster)
    if d is None:
        _need_book(); return

    mom = d.get("mom")

    def spark(col, color):
        if mom is None or getattr(mom, "empty", True) or col not in mom.columns:
            return ""
        return ui.sparkline(ui._spark_vals(mom[col]), color=color)

    def fnum(v, plus=False):
        if v is None:
            return "—"
        return f"{'+' if plus and v >= 0 else ''}{v:,.1f}"

    _hdr("Book snapshot", "shield")
    _cards([
        ui.metric_card("Total active policies", f"{d['policies']:,}", icon_key="shield", spark=spark("Total Members", ui.ELEC)),
        ui.metric_card("Total members", f"{d['members']:,}", icon_key="users", spark=spark("Total Members", ui.CYAN)),
        ui.metric_card("Avg household size", f"{d['household']:.1f}", icon_key="home"),
    ])

    _hdr("Growth · policies / month", "trend")
    churn = f"{d['churn']:.2f}% monthly churn" if d["churn"] is not None else "All history"
    _cards([
        ui.metric_card("Avg added / month", fnum(d["added"]), icon_key="plus", spark=spark("New Policies", ui.GREEN)),
        ui.metric_card("Avg lost / month", fnum(d["lost"]), sub=churn, icon_key="minus", spark=spark("Policies Lost", ui.RED)),
        ui.metric_card("Avg net growth / month", fnum(d["net_growth"], plus=True), icon_key="trend", spark=spark("New Policies", ui.ELEC)),
    ])

    _hdr("Growth · members / month", "trend")
    _cards([
        ui.metric_card("Avg members added / month", fnum(d["m_added"]), icon_key="plus", spark=spark("New Members", ui.GREEN)),
        ui.metric_card("Avg members lost / month", fnum(d["m_lost"]), icon_key="minus", spark=spark("Members Lost", ui.RED)),
        ui.metric_card("Net members / month", fnum(d["net_members"], plus=True), icon_key="trend", spark=spark("New Members", ui.ELEC)),
    ])

    _hdr("Commission forecast", "dollar")
    _cards([
        ui.metric_card("Expected monthly", f"${d['comm_monthly']:,.0f}", icon_key="dollar", spark=spark("Total Members", "#c4b5fd"), highlight="green"),
        ui.metric_card("Expected annual", f"${d['comm_annual']:,.0f}", icon_key="calendar"),
        ui.metric_card("Per policy / mo", f"${d['per_policy']:.2f}", icon_key="file"),
    ])

    if d["history_months"] < 2:
        st.caption(
            "Growth metrics reflect your latest upload. They sharpen into true "
            "month-over-month averages as you upload each month."
        )

    # ── Book age ──────────────────────────────────────────────────────────────
    active = views.active(roster)
    buckets = charts.book_age_buckets(active)
    total_p = sum(buckets.values()) or 1
    with st.container(border=True):
        st.markdown(ui.chart_head("Book age — months on book",
                                  "Active policies grouped by tenure", "calendar"), unsafe_allow_html=True)
        cols = st.columns(5)
        for col, (label, count), color in zip(cols, buckets.items(), charts.BUCKET_COLORS):
            pct = round(count / total_p * 100)
            clock = (f'<svg viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" '
                     f'stroke-linecap="round" stroke-linejoin="round">'
                     f'<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>')
            col.markdown(
                f'<div class="ba-card"><div class="ba-bar" style="background:linear-gradient(90deg,{color},rgba(0,0,0,0));"></div>'
                f'<div class="ba-icon" style="background:{color}22;border:1px solid {color}55;">{clock}</div>'
                f'<div class="ba-val">{count:,}</div><div class="ba-lbl">{label}</div>'
                f'<div class="ba-pct" style="color:{color};">{pct}%</div></div>',
                unsafe_allow_html=True)
        ui.show_chart(charts.book_age_fig(buckets))
        new_pct = round((buckets["< 3 MO"] + buckets["3–6 MO"]) / total_p * 100)
        vet_pct = round(buckets["18 MO+"] / total_p * 100)
        st.markdown(
            f'<div class="insight"><div class="in-icon">{ui.ICONS.get("info", "")}</div>'
            f'<div><div class="in-main">{new_pct}% of your book is under 6 months old (higher AEP risk)</div>'
            f'<div class="in-sub">{vet_pct}% has been with you 18+ months (most loyal clients)</div></div></div>',
            unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    ca, cb = st.columns(2)
    with ca:
        with st.container(border=True):
            st.markdown(ui.chart_head("Policies by Carrier",
                                      "Carrier distribution across active policies", "pie"), unsafe_allow_html=True)
            cdf = d.get("carrier_df")
            if cdf is not None and not cdf.empty:
                ui.show_chart(charts.carrier_fig(cdf))
    with cb:
        with st.container(border=True):
            st.markdown(ui.chart_head("Policies by State (Top 15)",
                                      "Top 15 states by active policy count", "pin"), unsafe_allow_html=True)
            sdf = d.get("state_df")
            if sdf is not None and not sdf.empty:
                ui.show_chart(charts.state_fig(sdf))


def page_daily(tenant: dict, roster) -> None:
    st.title("Daily Tracker")
    st.caption("New policies added per day (last 60 days with activity).")
    if roster is None:
        _need_book(); return
    fig = charts.daily_new_fig(roster)
    if fig is None:
        st.info("No dated policies to chart yet."); return
    ui.show_chart(fig)


def page_trends(tenant: dict, roster) -> None:
    st.title("Monthly Trends")
    st.caption("Policies added vs lost, month over month.")
    if roster is None:
        _need_book(); return
    d = dashboard_kpis.compute(tenant["agent_id"], roster)
    mom = d.get("mom") if d else None
    fig = charts.trends_fig(mom)
    if fig is None:
        st.info("Upload a few months of exports and the trend fills in here."); return
    ui.show_chart(fig)
    if mom is not None and not mom.empty:
        st.dataframe(mom, use_container_width=True, hide_index=True)


def page_client_lookup(tenant: dict, roster) -> None:
    st.title("Client Lookup")
    if roster is None:
        _need_book(); return
    q = st.text_input("Search by name", placeholder="Start typing a client's name…")
    if not q.strip():
        st.caption("Type a name to pull up a client's details.")
        return
    ql = q.lower().strip()
    mask = (roster["first_name"].fillna("").astype(str).str.lower().str.contains(ql)
            | roster["last_name"].fillna("").astype(str).str.lower().str.contains(ql))
    hits = roster[mask]
    st.caption(f"{len(hits)} match(es)")
    cols = [c for c in ["first_name", "last_name", "carrier", "state", "status",
                        "effective_date", "policy_aor", "phone", "email"] if c in hits.columns]
    st.dataframe(hits[cols].rename(columns=_NAMES), use_container_width=True, hide_index=True)


def page_commissions(tenant: dict, roster) -> None:
    st.title("Commissions")
    st.caption("Projected commission from your active book (members × $23/mo). "
               "Actual paid-commission tracking needs a payments feed — that comes later.")
    if roster is None:
        _need_book(); return
    d = dashboard_kpis.compute(tenant["agent_id"], roster)
    _cards([
        ui.metric_card("Expected monthly", f"${d['comm_monthly']:,.0f}", icon_key="dollar", highlight="green"),
        ui.metric_card("Expected annual", f"${d['comm_annual']:,.0f}", icon_key="calendar"),
        ui.metric_card("Per policy / mo", f"${d['per_policy']:.2f}", icon_key="file"),
    ])


def page_goals(tenant: dict, roster) -> None:
    st.title("Goals")
    st.info("Goal tracking is on the way — set monthly policy/member targets and watch your progress.", icon="🎯")


def page_aep(tenant: dict, roster) -> None:
    st.title("AEP Tracker")
    st.info("The open-enrollment re-enrollment tracker (keep / switch / done per client) is on the way.", icon="🗂️")


def page_settings(tenant: dict, roster) -> None:
    st.title("Settings")
    st.write(f"**Agent:** {tenant.get('name') or tenant.get('username')}")
    if tenant.get("npn"):
        st.write(f"**NPN:** {tenant['npn']}")
    st.write(f"**Private workspace:** `tenants/{tenant['agent_id']}/`")
    st.caption("Change password and licensed-states settings are coming soon.")


def page_book(tenant: dict, roster) -> None:
    st.title("My Book")
    if roster is None:
        _need_book(); return
    a = views.active(roster)
    members = pd.to_numeric(a.get("applicant_count"), errors="coerce").fillna(1).clip(lower=1).sum()
    _cards([
        ui.metric_card("Active clients", f"{len(a):,}", icon_key="shield"),
        ui.metric_card("Members", f"{int(members):,}", icon_key="users"),
        ui.metric_card("Total on file", f"{len(roster):,}", icon_key="file"),
    ])
    st.divider()
    _table(a, ["first_name", "last_name", "carrier", "state", "status", "effective_date"], "")


def page_losses(tenant: dict, roster) -> None:
    st.title("Losses  ·  Re-Engage")
    st.caption("Clients who cancelled or terminated — your win-back list.")
    if roster is None:
        _need_book(); return
    lost = views.losses(roster)
    _stat(ui.metric_card("Cancelled / terminated", f"{len(lost):,}", icon_key="minus"))
    st.divider()
    _table(lost, ["first_name", "last_name", "carrier", "state", "status", "term_date"],
           "No losses — everyone's still active. 🎉")


def page_aor(tenant: dict, roster) -> None:
    st.title("AOR Defense")
    st.caption("Clients another agent is now the agent of record on — your recovery list.")
    if roster is None:
        _need_book(); return
    taken = views.aor_taken(roster, tenant.get("npn", ""), tenant.get("name", ""))
    _stat(ui.metric_card("Taken by another agent", f"{len(taken):,}", icon_key="shield"))
    st.divider()
    _table(taken, ["first_name", "last_name", "state", "taken_by", "carrier"],
           "None taken — you hold every client's AOR. 🛡️")


def page_verifications(tenant: dict, roster) -> None:
    st.title("Verifications")
    st.caption("Active clients with an expired document check — coverage at risk unless docs go in.")
    if roster is None:
        _need_book(); return
    v = views.verifications(roster)
    _stat(ui.metric_card("Docs expired", f"{len(v):,}", icon_key="clock"))
    st.divider()
    _table(v, ["first_name", "last_name", "carrier", "state", "status"],
           "No expired verifications — you're clean. ✅")


def page_pastdue(tenant: dict, roster) -> None:
    st.title("Past Due")
    st.caption("Behind-on-payment clients from your Ambetter & Oscar carrier books.")
    pd_df = views.past_due(tenant["agent_id"])
    if pd_df is None:
        st.info("Upload your Ambetter and/or Oscar carrier books on the **Upload** page to "
                "see who's behind on payment.", icon="📥")
        return
    _stat(ui.metric_card("Past due", f"{len(pd_df):,}", icon_key="clock"))
    st.divider()
    st.dataframe(pd_df, use_container_width=True, hide_index=True)


# ── Shell ───────────────────────────────────────────────────────────────────
# Nav order matters — the section labels + bottom divider are painted by CSS
# (nth-of-type), so keep group starts at positions 1 / 4 / 7 / 9 and the
# Upload+Settings pair last (13, 14).
_NAV = ["Dashboard", "Daily Tracker", "Goals",
        "Client Lookup", "Book", "Monthly Trends",
        "Commissions", "Past Due",
        "AOR Defense", "Verifications", "Re-Engage", "AEP Tracker",
        "Upload", "Settings"]

_PAGES = {
    "Dashboard": page_dashboard, "Daily Tracker": page_daily, "Goals": page_goals,
    "Client Lookup": page_client_lookup, "Book": page_book, "Monthly Trends": page_trends,
    "Commissions": page_commissions, "Past Due": page_pastdue,
    "AOR Defense": page_aor, "Verifications": page_verifications,
    "Re-Engage": page_losses, "AEP Tracker": page_aep, "Settings": page_settings,
}
_NO_ROSTER = {"Upload", "Settings", "Goals", "AEP Tracker"}


def _nav_css() -> None:
    sb = 'section[data-testid="stSidebar"] div[role="radiogroup"] > label'
    css = [f'{sb}::before{{content:none;}}']  # drop the empty icon slots (per-item icons not ported)
    for i, title in [(1, "OVERVIEW"), (4, "CLIENTS"), (7, "MONEY"), (9, "FOLLOW UPS")]:
        css.append(f'{sb}:nth-of-type({i}){{margin-top:{12 if i == 1 else 22}px;position:relative;overflow:visible;}}')
        css.append(f'{sb}:nth-of-type({i})::after{{content:"{title}";position:absolute;top:-15px;left:10px;'
                   f'font-size:.64rem;letter-spacing:.13em;color:#6b84ad;font-weight:700;}}')
    css.append(f'{sb}:nth-of-type(13){{margin-top:26px;border-top:1px solid rgba(96,165,250,0.18);padding-top:12px;}}')
    st.markdown(f"<style>{''.join(css)}</style>", unsafe_allow_html=True)


def workspace() -> None:
    tenant = st.session_state.tenant
    agent_id = tenant["agent_id"]
    with st.sidebar:
        st.markdown(
            f'<div style="display:flex;align-items:center;gap:10px;padding:2px 2px 0;">'
            f'<span style="font-size:1.3rem;">📘</span>'
            f'<span style="font-size:1.12rem;font-weight:800;letter-spacing:-.01em;">{APP_NAME}</span></div>',
            unsafe_allow_html=True)
        st.caption(tenant.get("name") or tenant.get("username"))
        _nav_css()
        page = st.radio("Go to", _NAV, key="nav", label_visibility="collapsed")
        st.divider()
        if st.button("Log out", use_container_width=True):
            st.session_state.tenant = None
            st.rerun()

    if page == "Upload":
        page_upload(tenant)
        return
    roster = None if page in _NO_ROSTER else ingest_service.build_book(agent_id)
    _PAGES[page](tenant, roster)


if st.session_state.tenant:
    workspace()
else:
    login_screen()
