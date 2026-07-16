"""Agent Platform — multi-tenant app.

Phase 1: sign-in gate + per-tenant isolation.
Phase 2: in-app upload (HealthSherpa builds the book; carriers stored for reconciliation)
         and a first look at the agent's book, all scoped to their own workspace.
"""
import calendar
import datetime as dt
import os

import pandas as pd
import streamlit as st

from core import (charts, daily, dashboard_kpis, ingest_service, paths, settings, tenants,
                  ui, updates, views)

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


_ICON_USER = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' "
              "fill='none' stroke='%237286ad' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E"
              "%3Ccircle cx='12' cy='8' r='4'/%3E%3Cpath d='M4 20c0-4 4-6.5 8-6.5s8 2.5 8 6.5'/%3E%3C/svg%3E")
_ICON_LOCK = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' "
              "fill='none' stroke='%237286ad' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E"
              "%3Crect x='4' y='11' width='16' height='10' rx='2'/%3E%3Cpath d='M8 11V7a4 4 0 0 1 8 0v4'/%3E%3C/svg%3E")

_LOGIN_CSS = f"""
<style>
  [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"], footer {{ display:none !important; }}
  header[data-testid="stHeader"] {{ background:transparent; }}

  [data-testid="stAppViewContainer"] {{
    background:
      radial-gradient(820px 460px at 50% 10%, rgba(59,130,246,0.18), transparent 60%),
      radial-gradient(680px 480px at 12% 82%, rgba(37,99,235,0.16), transparent 55%),
      radial-gradient(680px 480px at 88% 74%, rgba(124,58,237,0.16), transparent 55%),
      #060b1a !important;
  }}

  /* the glass card = the centered content block */
  .block-container {{
    max-width: 600px !important;
    margin: 6vh auto 0 !important;
    padding: 44px 54px 40px !important;
    background: linear-gradient(160deg, rgba(32,46,88,0.55), rgba(14,22,46,0.6)) !important;
    border: 1px solid rgba(129,140,248,0.34);
    border-radius: 26px;
    box-shadow: 0 34px 90px rgba(0,0,0,0.55), 0 0 70px rgba(59,130,246,0.14), inset 0 1px 0 rgba(255,255,255,0.05);
    backdrop-filter: blur(16px);
  }}

  [data-testid="stMarkdownContainer"] p.brand {{ text-align:center; font-size:2.6rem !important; font-weight:800 !important; color:#fff !important; margin:0 !important; letter-spacing:-.02em; line-height:1.1; }}
  [data-testid="stMarkdownContainer"] p.brand-sub {{ text-align:center; color:#9fb0cc !important; margin:.4rem 0 1.5rem !important; font-size:1.05rem !important; }}

  /* tabs */
  [data-baseweb="tab-list"] {{ justify-content:center; gap:40px; border-bottom:1px solid rgba(129,140,248,0.16) !important; }}
  [data-baseweb="tab"] {{ color:#8a98b5 !important; font-weight:600; font-size:1rem; padding:8px 2px !important; }}
  [data-baseweb="tab"][aria-selected="true"] {{ color:#60a5fa !important; }}
  [data-baseweb="tab-highlight"] {{ background:#3b82f6 !important; height:2px !important; }}

  [data-testid="stTextInput"] label {{ color:#e6edf7 !important; font-weight:600; font-size:.95rem; }}

  /* inputs */
  [data-testid="stTextInput"] [data-baseweb="input"],
  [data-testid="stTextInput"] [data-baseweb="base-input"] {{
    background: rgba(9,16,34,0.72) !important;
    border: 1px solid rgba(96,165,250,0.28) !important;
    border-radius: 12px !important;
    background-repeat:no-repeat !important; background-position:15px center !important; background-size:18px 18px !important;
  }}
  [data-testid="stTextInput"]:has(input[type="password"]) [data-baseweb="input"] {{ background-image:url("{_ICON_LOCK}") !important; }}
  [data-testid="stTextInput"]:has(input:not([type="password"])) [data-baseweb="input"] {{ background-image:url("{_ICON_USER}") !important; }}
  [data-testid="stTextInput"] input {{
    background:transparent !important; color:#e6edf7 !important;
    padding: 13px 12px 13px 46px !important; font-size:1rem;
  }}
  [data-testid="stTextInput"] input::placeholder {{ color:#66768f !important; }}
  [data-baseweb="input"]:focus-within {{ border-color:#3b82f6 !important; box-shadow:0 0 0 3px rgba(59,130,246,0.18) !important; }}

  .forgot {{ text-align:right; margin:2px 0 6px; }}
  .forgot span {{ color:#60a5fa; font-size:.85rem; cursor:pointer; }}

  /* gradient Sign in button */
  [data-testid="stFormSubmitButton"] button {{
    background: linear-gradient(90deg, #3b82f6 0%, #7c3aed 100%) !important;
    color:#fff !important; font-weight:700 !important; font-size:1.05rem !important;
    border:none !important; border-radius:14px !important; padding:13px !important;
    box-shadow: 0 12px 30px rgba(79,70,229,0.42) !important; transition:filter .15s ease;
  }}
  [data-testid="stFormSubmitButton"] button:hover {{ filter:brightness(1.08); }}
</style>
"""


# ── Auth ────────────────────────────────────────────────────────────────────
def _invite_code() -> str:
    """Invite code required to create accounts (from host secret or env var).
    Empty = signup fully closed, login only."""
    try:
        c = st.secrets.get("INVITE_CODE")
    except Exception:
        c = None
    return str(c or os.environ.get("INVITE_CODE") or "").strip()


def login_screen() -> None:
    st.markdown(_LOGIN_CSS, unsafe_allow_html=True)
    st.markdown(f'<p class="brand">📘 {APP_NAME}</p>', unsafe_allow_html=True)
    st.markdown('<p class="brand-sub">Sign in to your book.</p>', unsafe_allow_html=True)

    # Invite-only: account creation is shown ONLY when an INVITE_CODE is configured
    # (host secret / env), and the correct code must be entered. No code = login-only,
    # so a random visitor to the public URL can never create an account.
    invite = _invite_code()
    tabs = st.tabs(["Sign in", "Create account (invite)"] if invite else ["Sign in"])

    with tabs[0]:
        with st.form("login"):
            username = st.text_input("Username", placeholder="Enter your username")
            password = st.text_input("Password", type="password", placeholder="Enter your password")
            st.markdown('<div class="forgot"><span>Forgot password?</span></div>', unsafe_allow_html=True)
            submitted = st.form_submit_button("Sign in", use_container_width=True)
        if submitted:
            tenant = tenants.verify(username, password)
            if tenant:
                paths.ensure_dirs(tenant["agent_id"])
                st.session_state.tenant = tenant
                st.rerun()
            else:
                st.error("Wrong username or password.")

    if invite:
        with tabs[1]:
            st.caption("New agents can only be added with an invite code.")
            with st.form("signup"):
                new_name = st.text_input("Agent's name", placeholder="Full name")
                new_user = st.text_input("Choose a username", placeholder="Pick a username")
                new_pass = st.text_input("Choose a password", type="password", placeholder="Pick a password")
                code = st.text_input("Invite code", type="password", placeholder="Enter your invite code")
                created = st.form_submit_button("Create account", use_container_width=True)
            if created:
                if code.strip() != invite:
                    st.error("Invalid invite code.")
                elif not (new_user.strip() and new_pass.strip()):
                    st.error("Username and password are required.")
                else:
                    try:
                        tenants.create_tenant(new_user.strip(), new_pass, (new_name or new_user).strip())
                        tenant = tenants.verify(new_user.strip(), new_pass)
                        paths.ensure_dirs(tenant["agent_id"])
                        st.session_state.tenant = tenant
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))


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
                roster = ingest_service.build_book(agent_id, tenant.get("npn", ""), tenant.get("name", ""))
                if roster is not None:
                    updates.compute_and_log(agent_id, roster)
                st.success(f"Done — read {len(df):,} rows. Your update summary is on the "
                           f"**Book Updates** page.")
                st.session_state["nav"] = "Book Updates"
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
    with st.container(border=True):
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


def page_updates(tenant: dict, roster) -> None:
    st.title("Book Updates")
    st.caption("What changed each time you uploaded — the same rundown you'd get by text.")
    hist = updates.history(tenant["agent_id"])
    if not hist:
        st.info("No updates yet — upload a HealthSherpa export and your summary shows up here.", icon="📥")
        return
    for e in hist:
        with st.container(border=True):
            st.markdown(f"**📘 Book updated · {e.get('date', '')}**")
            if e.get("first"):
                st.caption("First upload — baseline set. Changes show here starting with your next upload.")
                continue
            st.markdown(f"✅ **Signed:** {e.get('signed', 0)} new policies / {e.get('members', 0)} members")
            lost, taken = e.get("lost", []), e.get("taken", [])
            vexp, won = e.get("vexp", []), e.get("won", [])
            if not lost and not taken:
                st.markdown("⬇️ **Lost 0 clients — all clear.**")
            else:
                if lost:
                    st.markdown(f"⬇️ **Cancelled (→ Re-Engage):** {', '.join(lost)}")
                if taken:
                    st.markdown(f"🔻 **Taken by another agent:** {', '.join(taken)}")
            if vexp:
                st.markdown(f"⚠️ **Verification expired (still active, needs docs):** {', '.join(vexp)}")
            if won:
                st.markdown(f"🎉 **Won back:** {', '.join(won)}")


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
    if roster is None:
        _need_book(); return

    # ── All-time personal bests ───────────────────────────────────────────────
    best_day, best_week, best_month = daily.personal_bests(roster)
    _hdr("🏆 Personal Bests — New Business (All Time)", "trend")
    for col, title, rec in zip(st.columns(3), ["Best Day", "Best Week", "Best Month"],
                               [best_day, best_week, best_month]):
        with col, st.container(border=True):
            st.markdown(f"<div style='font-size:.72rem;letter-spacing:.09em;color:#94a3b8;"
                        f"text-transform:uppercase;font-weight:700'>{title}</div>", unsafe_allow_html=True)
            if rec:
                st.markdown(
                    f"<div style='font-size:1.9rem;font-weight:800;color:#fff;line-height:1.1;margin-top:6px'>"
                    f"{rec['pol']} <span style='font-size:.85rem;color:#22c55e;font-weight:700'>policies</span></div>"
                    f"<div style='font-size:.78rem;color:#94a3b8'>{rec['pol_when']}</div>"
                    f"<div style='font-size:1.5rem;font-weight:800;color:#fff;line-height:1.1;margin-top:10px'>"
                    f"{rec['mem']} <span style='font-size:.85rem;color:#60a5fa;font-weight:700'>members</span></div>"
                    f"<div style='font-size:.78rem;color:#94a3b8'>{rec['mem_when']}</div>", unsafe_allow_html=True)
            else:
                st.markdown("—")

    months_av = daily.months_available(roster)
    if not months_av:
        st.info("No dated policies to chart yet."); return
    labels = {pd.Timestamp(m + "-01").strftime("%B %Y"): m for m in months_av}
    ym = labels[st.selectbox("Select month", list(labels))]

    ddf = daily.daily_counts(roster, ym)
    year, mnum = int(ym[:4]), int(ym[5:7])
    dim = calendar.monthrange(year, mnum)[1]
    today = dt.date.today()
    elapsed = today.day if (today.year == year and today.month == mnum) else dim
    total_pol, total_mem = int(ddf["Policies"].sum()), int(ddf["Members"].sum())
    days_active = int((ddf["Policies"] > 0).sum())
    avg = round(total_pol / max(elapsed, 1), 1)
    pct = round(days_active / dim * 100)

    _cards([
        ui.stat_card("Total Policies Submitted", f"{total_pol:,}", "file", ui.BLUE),
        ui.stat_card("Total Heads Sold", f"{total_mem:,}", "users", ui.ELEC),
        ui.stat_card(f"Daily Avg ({elapsed} days elapsed)", avg, "trend", ui.CYAN),
        ui.stat_card(f"Days with Activity ({pct}% of {dim})", days_active, "calendar", ui.PURPLE),
    ])
    st.markdown("<br>", unsafe_allow_html=True)

    col_chart, col_table = st.columns([3, 2])
    with col_chart, st.container(border=True):
        st.markdown(ui.chart_head("Submissions by Day", "Policies submitted per day this month", "bars"),
                    unsafe_allow_html=True)
        ui.show_chart(charts.daily_month_fig(ddf))
    with col_table, st.container(border=True):
        st.markdown(ui.chart_head("Day-by-Day Breakdown", "Daily policies & members", "calendar"),
                    unsafe_allow_html=True)
        tbl = ddf.copy()
        tbl["Day"] = tbl["Date"].dt.strftime("%b %d")
        st.dataframe(
            tbl[["Day", "Policies", "Members"]], hide_index=True, use_container_width=True, height=430,
            column_config={
                "Policies": st.column_config.ProgressColumn(
                    "Policies", min_value=0, max_value=max(int(ddf["Policies"].max()), 1), format="%d"),
                "Members": st.column_config.ProgressColumn(
                    "Members", min_value=0, max_value=max(int(ddf["Members"].max()), 1), format="%d"),
            })


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


_US_STATES = ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "IA", "ID",
              "IL", "IN", "KS", "KY", "LA", "MA", "MD", "ME", "MI", "MN", "MO", "MS", "MT",
              "NC", "ND", "NE", "NH", "NJ", "NM", "NV", "NY", "OH", "OK", "OR", "PA", "RI",
              "SC", "SD", "TN", "TX", "UT", "VA", "VT", "WA", "WI", "WV", "WY"]

# Friendly carrier name → keyword(s) matched (case-insensitive substring) against
# the client's carrier. Stored appointments hold the keywords.
_CARRIERS_UI = {
    "Ambetter": ["ambetter"],
    "Oscar": ["oscar"],
    "Anthem / Wellpoint": ["anthem", "wellpoint"],
    "UnitedHealthcare": ["united", "uhc"],
    "Blue Cross Blue Shield": ["blue cross", "blue shield", "bcbs", "bcbst"],
    "Cigna": ["cigna"],
    "Molina": ["molina"],
    "Aetna / Coventry": ["aetna", "coventry"],
    "CareSource": ["caresource"],
    "SelectHealth": ["selecthealth", "select health"],
    "Allstate": ["allstate"],
    "Golden Rule": ["golden rule"],
}


def _carriers_for(keywords: list) -> list:
    kw = [str(x).lower() for x in (keywords or [])]
    return [name for name, ks in _CARRIERS_UI.items() if any(k in kw for k in ks)]


def page_settings(tenant: dict, roster) -> None:
    st.title("Settings")
    agent_id = tenant["agent_id"]
    cfg = settings.get(agent_id)

    # ── Profile / NPN ─────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown(ui.chart_head("Your profile", "Your NPN keeps your book scoped to you", "shield"),
                    unsafe_allow_html=True)
        st.write(f"**Agent:** {tenant.get('name') or tenant.get('username')}")
        with st.form("npn_form"):
            npn = st.text_input("Your NPN (National Producer Number)", value=tenant.get("npn", ""),
                                help="Keeps only YOUR clients when you upload. Set it before your first upload.")
            if st.form_submit_button("Save NPN", type="primary"):
                tenants.update_npn(tenant["username"], npn)
                st.session_state.tenant["npn"] = npn.strip()
                st.success("Saved. Re-upload your export so it re-scopes to your clients.")

    # ── States & carrier appointments ─────────────────────────────────────────
    with st.container(border=True):
        st.markdown(ui.chart_head("States & carrier appointments",
                                  "Only clients in these states, on carriers you're appointed with, "
                                  "count in your book", "pin"), unsafe_allow_html=True)
        appts = cfg.get("appointments", {}) or {}

        if appts:
            rows = [{"State": s, "Appointed carriers": ", ".join(_carriers_for(kw)) or ", ".join(kw)}
                    for s, kw in sorted(appts.items())]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.caption("No states added yet — add the states you write business in below "
                       "(leave this empty to include every state).")

        st.markdown("**Add or edit a state**")
        stt = st.selectbox("State", _US_STATES, key="appt_state")
        default_c = _carriers_for(appts.get(stt, []))
        picked = st.multiselect(f"Carriers you're appointed with in {stt}",
                                list(_CARRIERS_UI), default=default_c, key=f"appt_carriers_{stt}")
        b1, b2 = st.columns(2)
        if b1.button(f"Save {stt}", type="primary", use_container_width=True):
            kws = sorted({k for c in picked for k in _CARRIERS_UI[c]})
            new = {**appts}
            if kws:
                new[stt] = kws
            else:
                new.pop(stt, None)
            settings.save(agent_id, {**cfg, "appointments": new})
            st.success(f"Saved {stt}.")
            st.rerun()
        if stt in appts and b2.button(f"Remove {stt}", use_container_width=True):
            settings.save(agent_id, {**cfg, "appointments": {k: v for k, v in appts.items() if k != stt}})
            st.success(f"Removed {stt}.")
            st.rerun()

    # ── Excluded clients ──────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown(ui.chart_head("Excluded clients", "Hidden from your book entirely (e.g. never-sold "
                                  "noise)", "minus"), unsafe_allow_html=True)
        excl = cfg.get("exclusions", [])
        if excl:
            st.dataframe(pd.DataFrame(excl).rename(columns={"first": "First", "last": "Last", "state": "State"}),
                         use_container_width=True, hide_index=True)
        else:
            st.caption("None yet.")
        with st.form("excl_form"):
            c1, c2, c3 = st.columns(3)
            f = c1.text_input("First name")
            l = c2.text_input("Last name")
            s = c3.text_input("State", max_chars=2, placeholder="GA")
            if st.form_submit_button("Add exclusion") and f.strip() and l.strip():
                excl = excl + [{"first": f.strip(), "last": l.strip(), "state": s.strip().upper()}]
                settings.save(agent_id, {**cfg, "exclusions": excl})
                st.success(f"Excluded {f} {l}.")
                st.rerun()

    st.caption(f"Private workspace · `tenants/{agent_id}/`")


def page_book(tenant: dict, roster) -> None:
    st.title("My Book")
    if roster is None:
        _need_book(); return
    a = views.active(roster)
    members = pd.to_numeric(a.get("applicant_count"), errors="coerce").fillna(1).clip(lower=1).sum()
    _cards([
        ui.stat_card("Active clients", f"{len(a):,}", "shield", ui.GREEN),
        ui.stat_card("Members", f"{int(members):,}", "users", ui.ELEC),
        ui.stat_card("Total on file", f"{len(roster):,}", "file", ui.BLUE),
    ])
    st.divider()
    _table(a, ["first_name", "last_name", "carrier", "state", "status", "effective_date"], "")


def page_losses(tenant: dict, roster) -> None:
    st.title("Losses  ·  Re-Engage")
    st.caption("Clients who cancelled or terminated — your win-back list.")
    if roster is None:
        _need_book(); return
    lost = views.losses(roster)
    _stat(ui.stat_card("Cancelled / terminated", f"{len(lost):,}", "minus", ui.RED))
    _table(lost, ["first_name", "last_name", "carrier", "state", "status", "term_date"],
           "No losses — everyone's still active. 🎉")


def page_aor(tenant: dict, roster) -> None:
    st.title("AOR Defense")
    st.caption("Clients another agent is now the agent of record on — your recovery list.")
    if roster is None:
        _need_book(); return
    taken = views.aor_taken(roster, tenant.get("npn", ""), tenant.get("name", ""))
    _stat(ui.stat_card("Taken by another agent", f"{len(taken):,}", "shield", ui.GOLD))
    _table(taken, ["first_name", "last_name", "state", "taken_by", "carrier"],
           "None taken — you hold every client's AOR. 🛡️")


def page_verifications(tenant: dict, roster) -> None:
    st.title("Verifications")
    st.caption("Active clients with an expired document check — coverage at risk unless docs go in.")
    if roster is None:
        _need_book(); return
    v = views.verifications(roster)
    _stat(ui.stat_card("Docs expired", f"{len(v):,}", "clock", ui.GOLD))
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
    _stat(ui.stat_card("Past due", f"{len(pd_df):,}", "clock", ui.RED))
    with st.container(border=True):
        st.dataframe(pd_df, use_container_width=True, hide_index=True)


# ── Shell ───────────────────────────────────────────────────────────────────
# Nav order matters — the section labels + bottom divider are painted by CSS
# (nth-of-type), so keep group starts at positions 1 / 4 / 7 / 9 and the
# Upload+Settings pair last (13, 14).
_NAV = ["Dashboard", "Book Updates", "Daily Tracker", "Goals",
        "Client Lookup", "Book", "Monthly Trends",
        "Commissions", "Past Due",
        "AOR Defense", "Verifications", "Re-Engage", "AEP Tracker",
        "Upload", "Settings"]

_PAGES = {
    "Dashboard": page_dashboard, "Book Updates": page_updates, "Daily Tracker": page_daily,
    "Goals": page_goals, "Client Lookup": page_client_lookup, "Book": page_book,
    "Monthly Trends": page_trends, "Commissions": page_commissions, "Past Due": page_pastdue,
    "AOR Defense": page_aor, "Verifications": page_verifications,
    "Re-Engage": page_losses, "AEP Tracker": page_aep, "Settings": page_settings,
}
_NO_ROSTER = {"Upload", "Settings", "Goals", "AEP Tracker", "Book Updates"}


def _nav_css() -> None:
    sb = 'section[data-testid="stSidebar"] div[role="radiogroup"] > label'
    css = [f'{sb}::before{{content:none;}}']  # drop the empty icon slots (per-item icons not ported)
    for i, title in [(1, "OVERVIEW"), (5, "CLIENTS"), (8, "MONEY"), (10, "FOLLOW UPS")]:
        css.append(f'{sb}:nth-of-type({i}){{margin-top:{12 if i == 1 else 22}px;position:relative;overflow:visible;}}')
        css.append(f'{sb}:nth-of-type({i})::after{{content:"{title}";position:absolute;top:-15px;left:10px;'
                   f'font-size:.64rem;letter-spacing:.13em;color:#6b84ad;font-weight:700;}}')
    css.append(f'{sb}:nth-of-type(14){{margin-top:26px;border-top:1px solid rgba(96,165,250,0.18);padding-top:12px;}}')
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
    roster = (None if page in _NO_ROSTER
              else ingest_service.build_book(agent_id, tenant.get("npn", ""), tenant.get("name", "")))
    _PAGES[page](tenant, roster)


if st.session_state.tenant:
    workspace()
else:
    login_screen()
