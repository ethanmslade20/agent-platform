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

from core import (carrier_names, charts, daily, dashboard_kpis, ingest_service, paths,
                  settings, tenants, ui, updates, views)

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

  /* inputs — border ONLY on the outer wrapper (the inner container stays
     transparent so password fields don't render a doubled border) */
  [data-testid="stTextInput"] [data-baseweb="input"] {{
    background: rgba(9,16,34,0.72) !important;
    border: 1px solid rgba(96,165,250,0.28) !important;
    border-radius: 12px !important;
    background-repeat:no-repeat !important; background-position:15px center !important; background-size:18px 18px !important;
    overflow:hidden !important;
  }}
  [data-testid="stTextInput"] [data-baseweb="base-input"] {{
    background:transparent !important; border:none !important;
  }}
  [data-testid="stTextInput"]:has(input[type="password"]) [data-baseweb="input"] {{ background-image:url("{_ICON_LOCK}") !important; }}
  [data-testid="stTextInput"]:has(input:not([type="password"])) [data-baseweb="input"] {{ background-image:url("{_ICON_USER}") !important; }}
  [data-testid="stTextInput"] input {{
    background:transparent !important; color:#e6edf7 !important;
    padding: 13px 12px 13px 46px !important; font-size:1rem;
  }}
  [data-testid="stTextInput"] input::placeholder {{ color:#66768f !important; }}
  /* reveal-password eye — flat, no border/box, subtle until hover */
  [data-testid="stTextInput"] [data-baseweb="input"] button {{
    background:transparent !important; border:none !important; box-shadow:none !important;
    color:#66768f !important; margin-right:6px !important;
  }}
  [data-testid="stTextInput"] [data-baseweb="input"] button:hover {{ color:#e6edf7 !important; }}
  [data-testid="stTextInput"] [data-baseweb="input"]:focus-within {{ border-color:#3b82f6 !important; box-shadow:0 0 0 3px rgba(59,130,246,0.18) !important; }}

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
                new_npn = st.text_input("Your NPN", placeholder="National Producer Number")
                st.caption("Your NPN is what pulls only *your* clients out of an upload — it's required.")
                code = st.text_input("Invite code", type="password", placeholder="Enter your invite code")
                created = st.form_submit_button("Create account", use_container_width=True)
            if created:
                npn = (new_npn or "").strip()
                if code.strip() != invite:
                    st.error("Invalid invite code.")
                elif not (new_user.strip() and new_pass.strip()):
                    st.error("Username and password are required.")
                elif not npn.isdigit() or not (5 <= len(npn) <= 10):
                    st.error("Enter a valid NPN — 5 to 10 digits, numbers only.")
                else:
                    try:
                        tenants.create_tenant(new_user.strip(), new_pass, (new_name or new_user).strip(), npn=npn)
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

    if not str(tenant.get("npn", "")).strip():
        st.warning("Set your **NPN** on the **Settings** page before uploading — without it "
                   "we can't tell which clients in the file are yours.", icon="⚠️")
        return

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
                st.success(f"Done — read {len(df):,} rows. Taking you to your **Book Updates**…")
                # Redirect on the next run (the nav radio is already drawn this run).
                st.session_state["_pending_nav"] = "Book Updates"
                st.rerun()
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

    # First month of the agent's data drives the "since" sublabels (dynamic per agent).
    first_label, first_abbr = "your first month", "start"
    if mom is not None and not getattr(mom, "empty", True) and "Month" in mom.columns:
        _fm = pd.to_datetime(mom["Month"], errors="coerce").min()
        if pd.notna(_fm):
            first_label, first_abbr = _fm.strftime("%b %Y"), _fm.strftime("%b")
    since_sub = f"{first_label} – present"
    net_sub = f"Added ({first_abbr}+) minus Lost (all-time)"

    _hdr("Book Snapshot", "book")
    _cards([
        ui.metric_card("Total Active Policies", f"{d['policies']:,}", icon_key="shield", spark=spark("Total Policies", ui.ELEC)),
        ui.metric_card("Total Members", f"{d['members']:,}", icon_key="users", spark=spark("Total Members", ui.CYAN)),
        ui.metric_card("Avg Household Size", f"{d['household']:.1f}", icon_key="home"),
    ])

    _hdr("Growth Metrics", "trend")
    churn = (f"All history • {d['churn']:.2f}% monthly churn" if d["churn"] is not None else "All history")
    _cards([
        ui.metric_card("Avg Policies Added / Month", fnum(d["added"]), sub=since_sub, icon_key="plus", spark=spark("New Policies", ui.GREEN)),
        ui.metric_card("Avg Policies Lost / Month", fnum(d["lost"]), sub=churn, icon_key="minus", spark=spark("Policies Lost", ui.RED)),
        ui.metric_card("Avg Net Growth / Month", fnum(d["net_growth"], plus=True), sub=net_sub, icon_key="trend", spark=spark("Net Change", ui.ELEC)),
    ])

    _hdr("Member Growth", "trend")
    _cards([
        ui.metric_card("Avg Members Added / Month", fnum(d["m_added"]), sub=since_sub, icon_key="plus", spark=spark("New Members", ui.GREEN)),
        ui.metric_card("Avg Members Lost / Month", fnum(d["m_lost"]), sub="All history", icon_key="minus", spark=spark("Members Lost", ui.RED)),
        ui.metric_card("Net Members Gained / Month", fnum(d["net_members"], plus=True), sub=net_sub, icon_key="trend", spark=spark("New Members", ui.ELEC)),
    ])

    _hdr("Commission Forecast", "dollar")
    _cards([
        ui.metric_card("Expected Monthly Commission", f"${d['comm_monthly']:,.0f}", icon_key="dollar", spark=spark("Total Members", "#c4b5fd"), highlight="green"),
        ui.metric_card("Expected Annual Commission", f"${d['comm_annual']:,.0f}", icon_key="calendar"),
        ui.metric_card("Commission Per Policy / Mo", f"${d['per_policy']:.2f}", icon_key="file"),
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
        fig = charts.daily_month_fig(ddf)
        fig.update_xaxes(fixedrange=True); fig.update_yaxes(fixedrange=True)
        fig.update_layout(dragmode=False)
        evt = st.plotly_chart(fig, use_container_width=True, on_select="rerun",
                              key=f"daily_chart_{ym}",
                              config={"displayModeBar": False, "scrollZoom": False, "doubleClick": False})
        st.caption("💡 Click any bar to see who you signed that day.")
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

    # ── Drill-down: who you signed on the clicked day ─────────────────────────
    clicked_day = None
    try:
        pts = evt.selection.points if (evt and getattr(evt, "selection", None)) else []
        if pts:
            clicked_day = pts[0].get("x")
    except Exception:
        clicked_day = None

    st.markdown("<br>", unsafe_allow_html=True)
    with st.container(border=True):
        if not clicked_day:
            st.markdown(ui.chart_head("Policies for a Day",
                                      "Click a bar above to see who you signed that day", "users"),
                        unsafe_allow_html=True)
        else:
            col = "submission_date" if "submission_date" in roster.columns else "effective_date"
            dts = pd.to_datetime(roster.get(col), errors="coerce")
            try:
                day_date = pd.to_datetime(f"{clicked_day} {year}", format="%b %d %Y").date()
            except Exception:
                day_date = None
            rows = roster[dts.dt.date == day_date] if day_date else roster.iloc[0:0]
            mem = int(pd.to_numeric(rows.get("applicant_count"), errors="coerce").fillna(1).clip(lower=1).sum())
            st.markdown(ui.chart_head(f"Policies submitted — {clicked_day}",
                                      f"{len(rows)} policies · {mem} members", "users"),
                        unsafe_allow_html=True)
            if rows.empty:
                st.info("No policies recorded for that day.")
            else:
                show = pd.DataFrame({
                    "Name": (rows["first_name"].fillna("") + " " + rows["last_name"].fillna("")).str.strip().str.title(),
                    "Members": pd.to_numeric(rows.get("applicant_count"), errors="coerce").fillna(1).clip(lower=1).astype(int),
                    "Carrier": rows.get("carrier", ""),
                    "State": rows.get("state", ""),
                }).sort_values("Name")
                st.dataframe(show, use_container_width=True, hide_index=True,
                             height=min(80 + len(show) * 35, 460))


def page_trends(tenant: dict, roster) -> None:
    st.title("Month-over-Month Trends")
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    if roster is None:
        _need_book(); return
    d = dashboard_kpis.compute(tenant["agent_id"], roster)
    mom = d.get("mom") if d else None
    if mom is None or getattr(mom, "empty", True):
        st.info("No month-over-month data available yet."); return

    mom_plot = mom.copy()
    mom_plot["Month Label"] = mom_plot["Month"].apply(
        lambda m: pd.Timestamp(str(m) + "-01").strftime("%b %Y"))

    # ── Total members over time ─────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown(ui.chart_head("Total Active Members Over Time",
                                  "Cumulative active members by month", "trend"), unsafe_allow_html=True)
        ui.show_chart(charts.members_over_time_fig(mom_plot))
    st.markdown("<br>", unsafe_allow_html=True)

    # ── New vs Lost (policies + members) ────────────────────────────────────────
    col_l, col_r = st.columns(2)
    with col_l, st.container(border=True):
        st.markdown(ui.chart_head("New vs. Lost Policies", "Policies added vs. lost each month", "bars"),
                    unsafe_allow_html=True)
        ui.show_chart(charts.new_vs_lost_fig(mom_plot, "New Policies", "Policies Lost"))
    with col_r, st.container(border=True):
        st.markdown(ui.chart_head("New vs. Lost Members", "Members added vs. lost each month", "bars"),
                    unsafe_allow_html=True)
        ui.show_chart(charts.new_vs_lost_fig(mom_plot, "New Members", "Members Lost"))
    st.markdown("<br>", unsafe_allow_html=True)

    # ── Full trend table ────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown(ui.chart_head("Full Trend Table", "Month-by-month detail", "calendar"),
                    unsafe_allow_html=True)
        disp = mom_plot.drop(columns=["Month"]).rename(columns={"Month Label": "Month"})
        disp = disp[["Month"] + [c for c in disp.columns if c != "Month"]]
        st.dataframe(disp, use_container_width=True, hide_index=True, column_config={
            "% Growth": st.column_config.NumberColumn("% Growth", format="%.1f%%"),
            "Net Change": st.column_config.NumberColumn("Net Change", format="%+d"),
        })


_LOOKUP_CSS = """<style>
  .st-key-lookup_hero {max-width:620px;}
  .st-key-lookup_hero div[data-baseweb="select"] > div {
      font-size:1.08rem; padding:8px 12px; border-radius:14px;
      background:rgba(15,23,42,.65); border:1.5px solid rgba(96,165,250,.4);
      box-shadow:0 6px 22px rgba(0,0,0,.3);}
  .st-key-lookup_hero div[data-baseweb="select"] > div > div:first-child,
  .st-key-lookup_hero div[data-baseweb="select"] > div > div:first-child > div {
      color:#f8fafc !important; font-weight:700 !important; opacity:1 !important;}
  .st-key-lookup_hero div[data-baseweb="select"] input {
      color:#f8fafc !important; font-weight:600 !important; -webkit-text-fill-color:#f8fafc !important;}
</style>"""


def page_client_lookup(tenant: dict, roster) -> None:
    import re as _re
    st.title("Client Lookup")
    if roster is None:
        _need_book(); return
    st.caption("Start typing — the list narrows with every letter. Pick a client to open their profile.")

    people_all = (roster["first_name"].fillna("").astype(str).str.title().str.strip() + " "
                  + roster["last_name"].fillna("").astype(str).str.title().str.strip()).str.strip()
    names = sorted({p for p in people_all if p})
    with st.container(key="lookup_hero"):
        person = st.selectbox("Find a client", names, index=None, key="lookup_select",
                              placeholder="🔎  Type a name…  (e.g. “br” → every Brandon, Brittney, Bryan…)",
                              label_visibility="collapsed")
    st.markdown(_LOOKUP_CSS, unsafe_allow_html=True)

    if not person:
        st.info("🔎 Pick a client to see everything — policies, contact, and alerts.")
        return

    rows = roster[people_all == person].copy()
    if not len(rows):
        return
    rows["_eff"] = pd.to_datetime(rows["effective_date"], errors="coerce")
    rows = rows.sort_values("_eff", ascending=False)
    r = rows.iloc[0]  # newest policy is the headline

    is_active = r.get("status") in views.ACTIVE
    _mem_n = pd.to_numeric(r.get("applicant_count"), errors="coerce")
    _mem = 1 if pd.isna(_mem_n) else max(int(_mem_n), 1)

    # ── Header ────────────────────────────────────────────────────────────────
    pill_bg, pill_tx = (("rgba(34,197,94,.15)", "#4ade80") if is_active
                        else ("rgba(239,68,68,.15)", "#f87171"))
    pid = str(r.get("policy_number") or "").strip()
    pid_txt = (f" · Policy ID: <span style='color:#e2e8f0;font-weight:600;'>{pid}</span>"
               if pid and pid.lower() not in ("nan", "none") else "")
    st.markdown(
        f"<div style='display:flex;align-items:center;gap:14px;margin:6px 0 2px;'>"
        f"<span style='font-size:1.6rem;font-weight:800;color:#f8fafc;'>{person}</span>"
        f"<span style='background:{pill_bg};color:{pill_tx};padding:3px 12px;border-radius:999px;"
        f"font-size:.8rem;font-weight:700;'>{r.get('status', '?')}</span></div>"
        f"<div style='color:#94a3b8;font-size:.95rem;margin-bottom:10px;'>"
        f"{r.get('carrier', '—')} · {r.get('state', '—')}{pid_txt}</div>",
        unsafe_allow_html=True)

    # ── Agent-of-record banner ──────────────────────────────────────────────────
    aor = str(r.get("policy_aor") or "")
    npn = str(tenant.get("npn") or "")
    parts = [p for p in str(tenant.get("name") or "").lower().split() if p]
    mine = (npn and npn in aor) or (parts and all(p in aor.lower() for p in parts))
    if aor.strip().lower() in ("", "none", "nan"):
        st.caption("Agent of record: not recorded (usually fine — carrier book shows you).")
    elif mine:
        st.success("You are the agent of record.", icon="🛡️")
    else:
        who = _re.sub(r"\s*\(NPN.*\)", "", aor).strip().title()
        st.error(f"Agent of record is **{who}** — this client is on your AOR Defense page.", icon="🚨")

    # ── Stat cards ──────────────────────────────────────────────────────────────
    prem = pd.to_numeric(r.get("net_premium"), errors="coerce")
    mob = pd.to_numeric(r.get("months_on_book"), errors="coerce")
    _cards([
        ui.stat_card("Members", f"{_mem}", "users", ui.CYAN),
        ui.stat_card("Net Premium / Mo", f"${prem:,.0f}" if pd.notna(prem) else "—", "dollar", ui.GREEN),
        ui.stat_card("Months on Book",
                     ("<1" if int(mob) == 0 else f"{int(mob)}") if pd.notna(mob) else "—", "calendar", ui.ELEC),
        ui.stat_card("Est Commission / Yr", f"${_mem * 23 * 12:,.0f}" if is_active else "$0", "trend", ui.GOLD),
    ])

    # ── Contact ─────────────────────────────────────────────────────────────────
    ph = _re.sub(r"\D", "", str(r.get("phone") or ""))
    ph_fmt = f"({ph[:3]}) {ph[3:6]}-{ph[6:10]}" if len(ph) >= 10 else (ph or "—")
    em = str(r.get("email") or "").strip() or "—"
    cs = rows["_eff"].min()  # earliest policy = client since
    cs_fmt = cs.strftime("%b %-d, %Y") if pd.notna(cs) else "—"
    c1, c2, c3 = st.columns(3)
    c1.markdown(f"**📞 Phone:** {ph_fmt}")
    c2.markdown(f"**✉️ Email:** {em}")
    c3.markdown(f"**🗓️ Client since:** {cs_fmt}")

    # ── Why they left (churned) ─────────────────────────────────────────────────
    reason = str(r.get("cancel_reason") or "").strip()
    if not is_active and reason:
        st.warning(f"**Why they left:** {reason}", icon="📋")

    # ── Verification flags ──────────────────────────────────────────────────────
    dmi_n = pd.to_numeric(r.get("dmi_outstanding"), errors="coerce")
    svi_n = pd.to_numeric(r.get("svi_outstanding"), errors="coerce")
    dmi = 0 if pd.isna(dmi_n) else int(dmi_n)
    svi = 0 if pd.isna(svi_n) else int(svi_n)
    if dmi or svi:
        st.warning(f"📎 Outstanding verification docs: {dmi} DMI, {svi} SVI — their subsidy is at "
                   "risk until submitted (see Verifications).", icon="⚠️")

    # ── Policies (history) ──────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown(ui.chart_head("Policies", f"{len(rows)} on record for {person}", "file"),
                    unsafe_allow_html=True)
        pc = [c for c in ["carrier", "policy_number", "status", "effective_date", "term_date",
                          "net_premium", "applicant_count", "cancel_reason"] if c in rows.columns]
        pt = rows[pc].rename(columns={
            "carrier": "Carrier", "policy_number": "Policy ID", "status": "Status",
            "effective_date": "Effective", "term_date": "Term Date", "net_premium": "Premium",
            "applicant_count": "Members", "cancel_reason": "Why Ended"})
        st.dataframe(pt, use_container_width=True, hide_index=True,
                     column_config={
                         "Effective": st.column_config.DateColumn("Effective", format="MMM D, YYYY"),
                         "Term Date": st.column_config.DateColumn("Term Date", format="MMM D, YYYY"),
                     })


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


# Goal input-card icons + KPI-tile styling (mirrors Ethan's Goals page look).
_G_USERS = ("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' "
            "fill='none' stroke='%23a78bfa' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>"
            "<path d='M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2'/><circle cx='9' cy='7' r='4'/>"
            "<path d='M23 21v-2a4 4 0 0 0-3-3.87'/><path d='M16 3.13a4 4 0 0 1 0 7.75'/></svg>")
_G_CAL = ("data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' "
          "fill='none' stroke='%23a78bfa' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>"
          "<rect x='3' y='4' width='18' height='18' rx='2' ry='2'/><line x1='16' y1='2' x2='16' y2='6'/>"
          "<line x1='8' y1='2' x2='8' y2='6'/><line x1='3' y1='10' x2='21' y2='10'/></svg>")

_GOALS_CSS = f"""
<style>
  .st-key-goal_card_members, .st-key-goal_card_date {{
    position:relative; border-radius:20px; background:#0c1424;
    padding:30px 30px 30px 112px; min-height:132px; justify-content:center;
  }}
  .st-key-goal_card_members {{ box-shadow:0 0 24px rgba(139,92,246,.16); }}
  .st-key-goal_card_members::before {{
    content:""; position:absolute; inset:0; border-radius:20px; padding:1.5px;
    background:linear-gradient(120deg,#4285F4,#8b5cf6 55%,#b06ef7);
    -webkit-mask:linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
    -webkit-mask-composite:xor; mask-composite:exclude; pointer-events:none;
  }}
  .st-key-goal_card_date {{ box-shadow:0 0 20px rgba(66,133,244,.10); }}
  .st-key-goal_card_date::before {{
    content:""; position:absolute; inset:0; border-radius:20px; padding:1.5px;
    background:linear-gradient(120deg,rgba(66,133,244,.55),rgba(96,120,200,.30));
    -webkit-mask:linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
    -webkit-mask-composite:xor; mask-composite:exclude; pointer-events:none;
  }}
  .st-key-goal_card_members::after, .st-key-goal_card_date::after {{
    content:""; position:absolute; left:28px; top:50%; transform:translateY(-50%);
    width:56px; height:56px; border-radius:16px; background-color:#161f38;
    background-repeat:no-repeat; background-position:center; background-size:28px 28px;
    box-shadow:inset 0 0 0 1px rgba(139,92,246,.28); pointer-events:none;
  }}
  .st-key-goal_card_members::after {{ background-image:url("{_G_USERS}"); }}
  .st-key-goal_card_date::after    {{ background-image:url("{_G_CAL}"); }}
  .st-key-goal_card_members [data-testid="stWidgetLabel"] p,
  .st-key-goal_card_date [data-testid="stWidgetLabel"] p {{ font-size:.85rem !important; color:#8aacd6 !important; }}
  .st-key-goal_card_members [data-testid="stNumberInputContainer"],
  .st-key-goal_card_members div[data-baseweb="input"],
  .st-key-goal_card_members div[data-baseweb="input"] > div,
  .st-key-goal_card_members [data-baseweb="base-input"],
  .st-key-goal_card_date div[data-baseweb="input"],
  .st-key-goal_card_date div[data-baseweb="input"] > div,
  .st-key-goal_card_date [data-baseweb="base-input"] {{
    background:transparent !important; border:none !important; box-shadow:none !important;
  }}
  .st-key-goal_card_members input, .st-key-goal_card_date input {{
    font-size:1.9rem !important; font-weight:700 !important; color:#f2f5fb !important;
    background:transparent !important; padding-left:0 !important;
  }}
  .st-key-goal_card_members button[data-testid*="StepDown"],
  .st-key-goal_card_members button[data-testid*="StepUp"] {{
    background:transparent !important; border-radius:0 !important;
    border-left:1px solid rgba(138,172,214,.18) !important; width:54px !important; color:#e8edf5 !important;
  }}
  .st-key-goal_card_members button[data-testid*="StepDown"]:hover,
  .st-key-goal_card_members button[data-testid*="StepUp"]:hover {{ background:rgba(139,92,246,.12) !important; }}
  .goal-kpi-box {{
    background:#0c1424; border:1px solid rgba(96,165,250,0.16); border-radius:16px;
    padding:22px 20px 18px; height:100%; transition:transform .15s ease, border-color .15s ease;
  }}
  .goal-kpi-box:hover {{ transform:translateY(-2px); border-color:rgba(96,165,250,0.5); }}
  .goal-kpi-value {{ font-size:2.6rem; font-weight:800; color:#60a5fa; line-height:1.1; }}
  .goal-kpi-value.green {{ color:#22c55e; }}
  .goal-kpi-value.gold  {{ color:#f59e0b; }}
  .goal-kpi-value.red   {{ color:#ef4444; }}
  .goal-kpi-label {{ font-size:.72rem; color:#8aacd6; margin-top:6px; text-transform:uppercase; letter-spacing:.06em; }}
  .goal-kpi-sub {{ font-size:.82rem; color:#8aacd6; margin-top:4px; }}
</style>
"""


def _goal_kpi(label, value, sub, color=""):
    return (f'<div class="goal-kpi-box"><div class="goal-kpi-value {color}">{value}</div>'
            f'<div class="goal-kpi-label">{label}</div><div class="goal-kpi-sub">{sub}</div></div>')


def page_goals(tenant: dict, roster) -> None:
    PMPM, MAX_TENURE = 23, 60
    TODAY = dt.date.today()
    agent_id = tenant["agent_id"]
    cfg = settings.get(agent_id)
    goals = cfg.get("goals") or {}

    st.title("Goals")
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    st.markdown(ui.section_header("Set your goal", "target"), unsafe_allow_html=True)
    st.markdown(_GOALS_CSS, unsafe_allow_html=True)

    prev_members = int(goals.get("members", 2000) or 2000)
    try:
        prev_date = dt.date.fromisoformat(goals.get("date")) if goals.get("date") else dt.date(2027, 2, 1)
    except (TypeError, ValueError):
        prev_date = dt.date(2027, 2, 1)

    gi1, gi2 = st.columns(2, gap="large")
    with gi1, st.container(key="goal_card_members"):
        GOAL = st.number_input("Member goal", min_value=1, value=prev_members, step=50)
    with gi2, st.container(key="goal_card_date"):
        GOAL_DATE = st.date_input("Target date", value=prev_date)
    if GOAL != prev_members or GOAL_DATE != prev_date:
        settings.save(agent_id, {**cfg, "goals": {"members": int(GOAL), "date": GOAL_DATE.isoformat()}})

    if roster is None:
        _need_book(); return
    d = dashboard_kpis.compute(agent_id, roster)
    if d is None:
        _need_book(); return

    mom = d.get("mom")
    current = int(d["members"])
    avg_hh = d["household"] or 1.0
    goal_policies = round(GOAL / max(avg_hh, 1))
    st.markdown(
        f'<p style="color:#8aacd6;font-size:0.95rem;margin-top:-6px;">'
        f'<b style="color:#e8edf5">{GOAL:,} members</b> ≈ '
        f'<b style="color:#4285F4">{goal_policies:,} policies</b> '
        f'(based on your avg household size of {avg_hh:.2f})</p>', unsafe_allow_html=True)
    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

    gap = max(GOAL - current, 0)
    pct_done = min(current / GOAL * 100, 100) if GOAL else 0

    # LTV from all-time churn
    if mom is not None and not mom.empty and {"Members Lost", "Total Members"}.issubset(mom.columns):
        churn_rate = mom["Members Lost"].sum() / max(mom["Total Members"].sum(), 1)
    else:
        churn_rate = 0.0
    implied_tenure = min(1 / churn_rate if churn_rate > 0 else MAX_TENURE, MAX_TENURE)
    ltv_per = round(PMPM * implied_tenure)

    current_mrr, current_arr = current * PMPM, current * PMPM * 12
    current_book_ltv = current * ltv_per
    goal_mrr, goal_arr = GOAL * PMPM, GOAL * PMPM * 12
    revenue_gap_arr = goal_arr - current_arr

    days_left = (GOAL_DATE - TODAY).days
    months_left = max(round(days_left / 30.44, 1), 0.1)
    weeks_left = max(round(days_left / 7, 1), 0.1)
    needed_per_day = round(gap / days_left, 2) if days_left > 0 else 0
    needed_per_week = round(gap / weeks_left, 1) if weeks_left > 0 else 0
    needed_per_mo = round(gap / months_left, 1) if months_left > 0 else 0

    if mom is not None and not mom.empty and {"New Members", "Members Lost"}.issubset(mom.columns):
        recent_growth = (mom["New Members"] - mom["Members Lost"]).tail(3).mean()
    else:
        recent_growth = 0.0
    projected = round(current + recent_growth * months_left)
    projected_arr = projected * PMPM * 12
    on_track = projected >= GOAL

    st.markdown(
        f'<p style="color:#8aacd6;font-size:0.95rem;">LTV: all-time churn '
        f'({churn_rate*100:.2f}%/mo → {implied_tenure:.0f}-mo tenure → '
        f'<b style="color:#2ecc71">${ltv_per:,}/member</b>)</p>', unsafe_allow_html=True)

    # Dual progress bars
    rev_pct = min(current_arr / goal_arr * 100, 100) if goal_arr else 0
    bar_c = "#2ecc71" if pct_done >= 75 else ("#f39c12" if pct_done >= 40 else "#4285F4")
    rev_c = "#2ecc71" if rev_pct >= 75 else ("#f39c12" if rev_pct >= 40 else "#4285F4")
    st.markdown(f"""
      <div style="margin-bottom:4px;display:flex;justify-content:space-between;font-size:0.85rem;color:#8aacd6;">
        <span>Members &nbsp;<b style="color:#fff">{current:,}</b></span>
        <span><b style="color:#fff">{pct_done:.1f}%</b> of {GOAL:,}</span>
        <span><b>{gap:,} to go &nbsp;·&nbsp; {days_left:,} days left</b></span></div>
      <div class="progress-wrap" style="margin-bottom:14px;"><div class="progress-bar" style="width:{pct_done:.1f}%;background:{bar_c};"></div></div>
      <div style="margin-bottom:4px;display:flex;justify-content:space-between;font-size:0.85rem;color:#8aacd6;">
        <span>Annual Revenue &nbsp;<b style="color:#fff">${current_arr:,.0f}</b></span>
        <span><b style="color:#fff">{rev_pct:.1f}%</b> of ${goal_arr:,.0f}</span>
        <span><b>${revenue_gap_arr:,.0f} ARR to go</b></span></div>
      <div class="progress-wrap" style="margin-bottom:28px;"><div class="progress-bar" style="width:{rev_pct:.1f}%;background:{rev_c};"></div></div>
    """, unsafe_allow_html=True)

    st.markdown(ui.section_header("Revenue — where you are now", "dollar"), unsafe_allow_html=True)
    for col, html in zip(st.columns(4), [
        _goal_kpi("Monthly Recurring Revenue", f"${current_mrr:,.0f}", f"{current:,} members × ${PMPM}/mo"),
        _goal_kpi("Annual Run Rate", f"${current_arr:,.0f}", "MRR × 12 months"),
        _goal_kpi("LTV per Member", f"${ltv_per:,}", f"${PMPM}/mo × {implied_tenure:.0f}-mo tenure"),
        _goal_kpi("Total Book LTV", f"${current_book_ltv:,.0f}", f"{current:,} members × ${ltv_per:,}", "green")]):
        col.markdown(html, unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    st.markdown(ui.section_header("Pace needed to hit goal", "target"), unsafe_allow_html=True)
    for col, html in zip(st.columns(3), [
        _goal_kpi("New members / day", f"+{needed_per_day}", f"{days_left:,} days remaining"),
        _goal_kpi("New members / week", f"+{needed_per_week:.0f}", f"{weeks_left:.0f} weeks remaining"),
        _goal_kpi("New members / month", f"+{needed_per_mo:.0f}", f"{months_left:.0f} months remaining")]):
        col.markdown(html, unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    st.markdown(ui.section_header("At your current pace", "trend"), unsafe_allow_html=True)
    cur_mo, cur_wk, cur_dy = recent_growth, recent_growth * 12 / 52, recent_growth * 12 / 365
    c1, c2, c3 = st.columns(3)
    c1.markdown(_goal_kpi("New members / day", f"+{cur_dy:.2f}",
                f"vs +{needed_per_day} needed · {'ahead of pace ✓' if cur_dy >= needed_per_day else 'below pace'}",
                "green" if cur_dy >= needed_per_day else "red"), unsafe_allow_html=True)
    c2.markdown(_goal_kpi("New members / week", f"+{cur_wk:.0f}",
                f"vs +{needed_per_week:.0f} needed · {'ahead of pace ✓' if cur_wk >= needed_per_week else 'below pace'}",
                "green" if cur_wk >= needed_per_week else "red"), unsafe_allow_html=True)
    c3.markdown(_goal_kpi("New members / month", f"+{cur_mo:.0f}",
                f"vs +{needed_per_mo:.0f} needed · {'ahead of pace ✓' if cur_mo >= needed_per_mo else 'below pace'}",
                "green" if cur_mo >= needed_per_mo else "red"), unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    p1, p2, p3 = st.columns(3)
    p1.markdown(_goal_kpi("Avg net new members / mo (last 3)", f"+{recent_growth:.0f}", "based on recent history"), unsafe_allow_html=True)
    p2.markdown(_goal_kpi("Projected members by goal date", f"{projected:,}",
                "On track ✓" if on_track else "Behind pace", "green" if on_track else "red"), unsafe_allow_html=True)
    if GOAL - projected > 0:
        p3.markdown(_goal_kpi("Projected ARR by goal date", f"${projected_arr:,.0f}",
                    f"${goal_arr - projected_arr:,.0f} short of goal ARR", "red"), unsafe_allow_html=True)
    else:
        p3.markdown(_goal_kpi("Projected ARR by goal date", f"${projected_arr:,.0f}", "Goal ARR exceeded ✓", "green"), unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    # Growth vs required pace chart
    st.markdown(ui.section_header("Growth vs. required pace", "bars"), unsafe_allow_html=True)
    if mom is not None and not mom.empty and {"Month", "Total Members"}.issubset(mom.columns) and len(mom) >= 2:
        hist = mom[["Month", "Total Members"]].dropna().rename(columns={"Month": "month", "Total Members": "active"})
        hist["month"] = pd.to_datetime(hist["month"]); hist = hist.sort_values("month")
        hist["arr"] = hist["active"] * PMPM * 12
        start_date, start_count = hist["month"].iloc[0], hist["active"].iloc[0]
        goal_ts = pd.Timestamp(GOAL_DATE)
        pace_months = pd.date_range(start=start_date, end=goal_ts, freq="MS")
        span = max((goal_ts - start_date).days, 1)
        pace_vals = [start_count + (GOAL - start_count) * (t - start_date).days / span for t in pace_months]
        pace_df = pd.DataFrame({"month": pace_months, "required": pace_vals,
                                "required_arr": [v * PMPM * 12 for v in pace_vals]})
        fm, fr = charts.goal_growth_figs(hist, pace_df, GOAL, goal_arr, TODAY)
        tab_m, tab_r = st.tabs(["Members", "Annual Revenue"])
        with tab_m:
            ui.show_chart(fm)
        with tab_r:
            ui.show_chart(fr)
    else:
        st.info("Upload a couple months of exports and your growth chart fills in here.")
    st.markdown("<br>", unsafe_allow_html=True)

    # Weekly callout
    week_pol = round(needed_per_week / max(avg_hh, 1))
    st.markdown(
        f'<div style="background:linear-gradient(90deg,rgba(245,158,11,0.13),rgba(245,158,11,0.04));'
        f'border:1px solid rgba(245,158,11,0.4);border-left:4px solid {ui.GOLD};padding:16px 20px;'
        f'border-radius:14px;margin-bottom:20px;">'
        f'<div style="font-size:0.78rem;color:#8aacd6;text-transform:uppercase;letter-spacing:0.08em;font-weight:600;">This week\'s target</div>'
        f'<div style="font-size:1.9rem;font-weight:800;color:{ui.GOLD};margin-top:4px;">+{needed_per_week:.0f} members</div>'
        f'<div style="font-size:0.9rem;color:#8aacd6;margin-top:3px;">≈ {week_pol} policies &nbsp;·&nbsp; '
        f'{weeks_left:.0f} weeks remaining to reach {GOAL:,} members by {GOAL_DATE.strftime("%b %d, %Y")}</div></div>',
        unsafe_allow_html=True)

    # Monthly targets table
    st.markdown(ui.section_header("Monthly targets", "calendar"), unsafe_allow_html=True)
    rows, ref, running = [], TODAY.replace(day=1), current
    for i in range(int(months_left) + 2):
        mo = ref + pd.DateOffset(months=i)
        add = round(needed_per_mo)
        running = min(running + add, GOAL)
        rows.append({"Month": mo.strftime("%B %Y"), "Members to add": add,
                     "Policies to add": round(add / max(avg_hh, 1)), "Running members": running,
                     "MRR at target": f"${running * PMPM:,.0f}", "ARR at target": f"${running * PMPM * 12:,.0f}"})
        if running >= GOAL:
            break
    with st.container(border=True):
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=340)


_AEP_STATUSES = ["Not Started", "Contacted", "Renewed", "Lost"]


def page_aep(tenant: dict, roster) -> None:
    st.title("AEP Tracker")
    st.caption("Work every active client through open enrollment — set each one's status as you go.")
    if roster is None:
        _need_book(); return
    agent_id = tenant["agent_id"]
    cfg = settings.get(agent_id)
    saved = cfg.get("aep") or {}

    active = views.active(roster)
    if active.empty:
        st.info("No active clients to track yet."); return

    def _k(f, l):
        s = f"{f} {l}".lower().strip()
        return "".join(ch for ch in s if ch.isalnum() or ch == " ")

    rows = []
    for _, r in active.iterrows():
        k = _k(r.get("first_name", ""), r.get("last_name", ""))
        s = saved.get(k, {})
        rows.append({"_key": k,
                     "Client": f"{r.get('first_name', '')} {r.get('last_name', '')}".strip().title(),
                     "Carrier": r.get("carrier", ""), "State": r.get("state", ""),
                     "Status": s.get("status", "Not Started"), "Notes": s.get("notes", "")})
    df = pd.DataFrame(rows)

    done = int((df["Status"] == "Renewed").sum())
    started = int((df["Status"] != "Not Started").sum())
    _cards([
        ui.stat_card("Clients to Renew", f"{len(df):,}", "users", ui.BLUE),
        ui.stat_card("Worked", f"{started:,}", "trend", ui.GOLD),
        ui.stat_card("Renewed", f"{done:,}", "shield", ui.GREEN),
    ])
    st.progress(done / len(df) if len(df) else 0.0,
                text=f"{done:,} of {len(df):,} renewed ({round(done / len(df) * 100) if len(df) else 0}%)")

    edited = st.data_editor(
        df.drop(columns=["_key"]), hide_index=True, use_container_width=True, height=460,
        disabled=["Client", "Carrier", "State"], key="aep_editor",
        column_config={"Status": st.column_config.SelectboxColumn("Status", options=_AEP_STATUSES, width="small")})

    if st.button("Save statuses", type="primary"):
        out = {}
        for i in range(len(edited)):
            out[df.iloc[i]["_key"]] = {"status": edited.iloc[i]["Status"],
                                       "notes": str(edited.iloc[i].get("Notes", "") or "")}
        settings.save(agent_id, {**cfg, "aep": out})
        st.success("Statuses saved.")
        st.rerun()


_US_STATES = ["AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "IA", "ID",
              "IL", "IN", "KS", "KY", "LA", "MA", "MD", "ME", "MI", "MN", "MO", "MS", "MT",
              "NC", "ND", "NE", "NH", "NJ", "NM", "NV", "NY", "OH", "OK", "OR", "PA", "RI",
              "SC", "SD", "TN", "TX", "UT", "VA", "VT", "WA", "WI", "WV", "WY"]

_STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "IA": "Iowa", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "MA": "Massachusetts", "MD": "Maryland", "ME": "Maine",
    "MI": "Michigan", "MN": "Minnesota", "MO": "Missouri", "MS": "Mississippi", "MT": "Montana",
    "NC": "North Carolina", "ND": "North Dakota", "NE": "Nebraska", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NV": "Nevada", "NY": "New York", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VA": "Virginia", "VT": "Vermont", "WA": "Washington", "WI": "Wisconsin", "WV": "West Virginia",
    "WY": "Wyoming",
}


def page_settings(tenant: dict, roster) -> None:
    st.title("Settings")
    agent_id = tenant["agent_id"]
    cfg = settings.get(agent_id)

    # ── Profile / NPN ─────────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown(ui.chart_head("Your profile", "Your NPN keeps your book scoped to you", "shield"),
                    unsafe_allow_html=True)
        st.write(f"**Agent:** {tenant.get('name') or tenant.get('username')}")
        with st.form("username_form"):
            new_un = st.text_input("Username", value=tenant.get("username", ""),
                                   help="What you sign in with. Changing it keeps all your data.")
            if st.form_submit_button("Save username", type="primary"):
                try:
                    updated = tenants.rename(tenant["username"], new_un)
                    st.session_state.tenant.update(updated)
                    st.success(f"Username updated to '{updated['username']}'.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
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
        edit = st.session_state.get("appt_edit")

        # ── Your active states (click one to edit its carriers) ──
        st.markdown("**Your states**")
        if appts:
            active_states = sorted(appts, key=lambda s: _STATE_NAMES.get(s, s))
            per_row = 4
            for i in range(0, len(active_states), per_row):
                cols = st.columns(per_row)
                for col, s in zip(cols, active_states[i:i + per_row]):
                    n = len(appts.get(s) or [])
                    label = f"📍 {_STATE_NAMES.get(s, s)} · {n} carrier{'s' if n != 1 else ''}"
                    if col.button(label, key=f"pick_{s}", use_container_width=True,
                                  type=("primary" if s == edit else "secondary")):
                        st.session_state["appt_edit"] = s
                        st.rerun()
        else:
            st.caption("No states added yet — add the states you write business in below "
                       "(leave this empty to include every state).")

        # ── Add a state ──
        remaining = [s for s in _US_STATES if s not in appts]
        ac1, ac2 = st.columns([3, 1])
        add_s = ac1.selectbox("Add a state", remaining,
                              format_func=lambda s: _STATE_NAMES.get(s, s), key="appt_add",
                              label_visibility="collapsed") if remaining else None
        if add_s and ac2.button("Add state", use_container_width=True):
            settings.save(agent_id, {**cfg, "appointments": {**appts, add_s: []}})
            st.session_state["appt_edit"] = add_s
            st.rerun()

        # ── Edit the selected state's carriers ──
        if edit and edit in appts:
            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
            st.markdown(f"**Carriers you're appointed with in {_STATE_NAMES.get(edit, edit)}**")
            opts = carrier_names.brand_options(roster, extra=appts.get(edit))
            current = [c for c in (appts.get(edit) or []) if c in opts]
            picked = st.multiselect("Pick every carrier you can write in this state",
                                    opts, default=current, key=f"appt_carriers_{edit}",
                                    label_visibility="collapsed")
            b1, b2 = st.columns([1, 1])
            if b1.button(f"Save {_STATE_NAMES.get(edit, edit)}", type="primary", use_container_width=True):
                settings.save(agent_id, {**cfg, "appointments": {**appts, edit: sorted(picked)}})
                st.success(f"Saved {_STATE_NAMES.get(edit, edit)}.")
                st.rerun()
            if b2.button(f"Remove {_STATE_NAMES.get(edit, edit)}", use_container_width=True):
                settings.save(agent_id, {**cfg, "appointments": {k: v for k, v in appts.items() if k != edit}})
                st.session_state.pop("appt_edit", None)
                st.success(f"Removed {_STATE_NAMES.get(edit, edit)}.")
                st.rerun()
        elif appts:
            st.caption("Click a state above to add or edit the carriers you're appointed with there.")

    st.caption(f"Private workspace · `tenants/{agent_id}/`")


def page_book(tenant: dict, roster) -> None:
    st.title("Book of Business")
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    if roster is None:
        _need_book(); return

    df_all = roster.copy()
    df_all["status_display"] = df_all["status"].replace({"PendingEffectuation": "Effectuated"})
    active_sts = set(views.ACTIVE)

    # ── Filters ─────────────────────────────────────────────────────────────────
    f1, f2, f3, f4 = st.columns([2, 2, 2, 3])
    sel_status = f1.selectbox("Status", ["All"] + sorted(df_all["status_display"].dropna().unique().tolist()))
    sel_carrier = f2.selectbox("Carrier", ["All"] + sorted(df_all["carrier"].dropna().unique().tolist()))
    sel_state = f3.selectbox("State", ["All"] + sorted(df_all["state"].dropna().astype(str).unique().tolist()))
    search = f4.text_input("Search by name", placeholder="First or last name…")

    df = df_all.copy()
    if sel_status != "All":
        df = df[df["status_display"] == sel_status]
    if sel_carrier != "All":
        df = df[df["carrier"] == sel_carrier]
    if sel_state != "All":
        df = df[df["state"].astype(str) == sel_state]
    if search.strip():
        q = search.strip()
        df = df[df["first_name"].fillna("").str.contains(q, case=False)
                | df["last_name"].fillna("").str.contains(q, case=False)]

    # ── Status breakdown for the filtered set ───────────────────────────────────
    active_ct = int(df["status"].isin(active_sts).sum())
    inactive_ct = int((~df["status"].isin(active_sts)).sum())
    total_mem = int(pd.to_numeric(df.loc[df["status"].isin(active_sts), "applicant_count"],
                                  errors="coerce").fillna(1).clip(lower=1).sum())
    _cards([
        ui.stat_card("Total Policies", f"{len(df):,}", "file", ui.ELEC),
        ui.stat_card("Active Policies", f"{active_ct:,}", "shield", ui.GREEN),
        ui.stat_card("Inactive Policies", f"{inactive_ct:,}", "minus", ui.RED),
        ui.stat_card("Active Members", f"{total_mem:,}", "users", ui.CYAN),
    ])
    st.markdown("<br>", unsafe_allow_html=True)

    # ── Household size breakdown (active policies in view) ───────────────────────
    with st.container(border=True):
        st.markdown(ui.chart_head("Household Size", "Active policies by number of members on the plan", "users"),
                    unsafe_allow_html=True)
        adf = df[df["status"].isin(active_sts)]
        sz = pd.to_numeric(adf.get("applicant_count", pd.Series(dtype=float)),
                           errors="coerce").fillna(1).astype(int).clip(lower=1)
        if len(sz):
            b = sz.where(sz < 6, 6)
            lbl = {1: "1 (single)", 2: "2", 3: "3", 4: "4", 5: "5", 6: "6+"}
            hh = (pd.DataFrame({"n": b, "mem": sz.values})
                  .groupby("n").agg(Policies=("n", "size"), Members=("mem", "sum")).reset_index())
            hh["Size"] = hh["n"].map(lbl)
            hht = hh[["Size", "Policies", "Members"]].copy()
            hht.loc[len(hht)] = ["Total", int(hht["Policies"].sum()), int(hht["Members"].sum())]
            st.dataframe(hht, use_container_width=True, hide_index=True)
        else:
            st.caption("No active policies in the current view.")
    st.markdown("<br>", unsafe_allow_html=True)

    # ── Duplicate detection (only among policies still in force) ─────────────────
    live = df_all[~df_all["status"].isin(["Terminated", "Cancelled"])]
    dups = live[live.duplicated(subset=["first_name", "last_name"], keep=False)][
        ["first_name", "last_name", "carrier", "state", "status", "effective_date"]].sort_values(
        ["last_name", "first_name"])
    if not dups.empty:
        n_names = dups.groupby(["first_name", "last_name"]).ngroups
        st.warning(f"⚠️ {len(dups)} duplicate client names detected "
                   f"({n_names} unique names appear more than once)")
        with st.expander("View duplicates"):
            d2 = dups.copy()
            d2.columns = [c.replace("_", " ").title() for c in d2.columns]
            st.dataframe(d2, use_container_width=True, hide_index=True, column_config={
                "Effective Date": st.column_config.DateColumn("Effective Date", format="MMM D, YYYY")})
    st.markdown("<br>", unsafe_allow_html=True)

    # ── Client roster table ─────────────────────────────────────────────────────
    display_cols = ["first_name", "last_name", "carrier", "state", "status_display",
                    "effective_date", "term_date", "months_on_book", "applicant_count", "net_premium"]
    disp = df[[c for c in display_cols if c in df.columns]].rename(columns={"status_display": "status"})
    disp.columns = [c.replace("_", " ").title() for c in disp.columns]
    with st.container(border=True):
        st.markdown(ui.chart_head("Client Roster", f"{len(df):,} policies in current view", "book"),
                    unsafe_allow_html=True)
        st.dataframe(disp, use_container_width=True, hide_index=True, height=600, column_config={
            "Effective Date": st.column_config.DateColumn("Effective Date", format="MMM D, YYYY"),
            "Term Date": st.column_config.DateColumn("Term Date", format="MMM D, YYYY"),
            "Net Premium": st.column_config.NumberColumn("Net Premium", format="$%.2f"),
            "Applicant Count": st.column_config.NumberColumn("Members"),
            "Months On Book": st.column_config.NumberColumn("Mo. on Book"),
        })


def page_losses(tenant: dict, roster) -> None:
    st.title("Re-Engage")
    st.caption("Clients who cancelled or went missing — sorted by most recently lost. "
               "Reach out while the relationship is fresh.")
    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
    if roster is None:
        _need_book(); return

    today_ts = pd.Timestamp(dt.date.today())
    lost = views.losses(roster).copy()
    if lost.empty:
        st.success("No cancelled or terminated clients — everyone's still active. 🎉"); return

    lost["term_date"] = pd.to_datetime(lost.get("term_date"), errors="coerce")
    lost["days_since_lost"] = (today_ts - lost["term_date"]).dt.days.clip(lower=0)

    def _urgency(days):
        if pd.isna(days):
            return "⚪ Unknown"
        if days <= 30:
            return "🔴 <30 days"
        if days <= 60:
            return "🟡 30–60 days"
        if days <= 90:
            return "🟠 60–90 days"
        return "⚪ 90+ days"

    def _rel_day(ts):
        if pd.isna(ts):
            return "Unknown"
        d = (today_ts - ts).days
        return "today" if d <= 0 else ("yesterday" if d == 1 else f"{d} days ago")

    lost["Urgency"] = lost["days_since_lost"].apply(_urgency)
    d30 = int((lost["days_since_lost"] <= 30).sum())
    d60 = int((lost["days_since_lost"] <= 60).sum())
    d90 = int((lost["days_since_lost"] <= 90).sum())
    _cards([
        ui.stat_card("Need Outreach", f"{len(lost):,}", "users", ui.ELEC),
        ui.stat_card("Lost < 30 Days", f"{d30:,}", "clock", ui.RED),
        ui.stat_card("Lost < 60 Days", f"{d60:,}", "clock", ui.GOLD),
        ui.stat_card("Lost < 90 Days", f"{d90:,}", "clock", ui.CYAN),
    ])
    st.markdown("<br>", unsafe_allow_html=True)

    f1, f2, f3 = st.columns(3)
    window = {"Last 30 days": 30, "Last 60 days": 60, "Last 90 days": 90, "All time": 99999}
    wlabel = f1.selectbox("Show lost in", list(window), index=3)
    carrier = f2.selectbox("Carrier", ["All"] + sorted(lost["carrier"].dropna().astype(str).unique().tolist()))
    state = f3.selectbox("State", ["All"] + sorted(lost["state"].dropna().astype(str).unique().tolist()))
    view = lost[lost["days_since_lost"].fillna(99999) <= window[wlabel]].copy()
    if carrier != "All":
        view = view[view["carrier"].astype(str) == carrier]
    if state != "All":
        view = view[view["state"].astype(str) == state]
    view = view.sort_values("days_since_lost", ascending=True, na_position="last")

    st.caption(f"Showing **{len(view)}** clients · {wlabel.lower()}")
    if view.empty:
        st.info("No clients match the current filters."); return
    show = pd.DataFrame({
        "Name": (view["first_name"].fillna("") + " " + view["last_name"].fillna("")).str.strip().str.title(),
        "Urgency": view["Urgency"],
        "Lost": view["term_date"].apply(_rel_day),
        "Carrier": view["carrier"],
        "State": view["state"],
        "Members": pd.to_numeric(view.get("applicant_count"), errors="coerce").fillna(1).clip(lower=1).astype(int),
        "Why Ended": (view["cancel_reason"].fillna("").replace("", "—")
                      if "cancel_reason" in view.columns else "—"),
        "Phone": view.get("phone", ""),
    })
    st.dataframe(show, use_container_width=True, hide_index=True, height=min(120 + len(show) * 34, 620))


def page_aor(tenant: dict, roster) -> None:
    st.title("AOR Defense")
    st.caption("Clients another agent filed an Agent-of-Record change on — call them, most don't "
               "know they were switched. Newest steals first — the freshest are the most winnable.")
    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
    if roster is None:
        _need_book(); return

    taken = views.aor_taken(roster, tenant.get("npn", ""), tenant.get("name", "")).copy()
    members = pd.to_numeric(taken.get("applicant_count"), errors="coerce").fillna(1).clip(lower=1)
    stake = int(members.sum()) * 23 * 12

    _cards([
        ui.stat_card("Taken by Another Agent", f"{len(taken):,}", "minus", ui.RED),
        ui.stat_card("Members at Risk", f"{int(members.sum()):,}", "users", ui.ELEC),
        ui.stat_card("$/yr at Stake", f"${stake:,}", "dollar", ui.GREEN),
    ])
    st.markdown("<br>", unsafe_allow_html=True)

    with st.container(border=True):
        st.markdown(ui.chart_head("Taken — call these first",
                                  "Script: “I saw your plan got moved to a different agent — did you mean to do that?”",
                                  "minus"), unsafe_allow_html=True)
        if taken.empty:
            st.success("None taken — you hold every client's AOR. 🛡️")
        else:
            t = taken.copy()
            t["_mem"] = members.values
            t["Est $/yr"] = (t["_mem"] * 23 * 12).map(lambda v: f"${v:,.0f}")
            show = pd.DataFrame({
                "Client": (t["first_name"].fillna("") + " " + t["last_name"].fillna("")).str.strip().str.title(),
                "Taken By": t.get("taken_by", ""),
                "Carrier": t.get("carrier", ""),
                "State": t.get("state", ""),
                "Members": t["_mem"].astype(int),
                "Est $/yr": t["Est $/yr"],
                "Phone": t.get("phone", ""),
            })
            st.dataframe(show, use_container_width=True, hide_index=True,
                         height=min(46 + 35 * max(len(show), 1), 560))


def page_verifications(tenant: dict, roster) -> None:
    st.title("Verifications")
    st.caption("HealthSherpa verifications your clients still owe. **DMI** = income/coverage match; "
               "**SVI** = enrollment verification. If one **expires, the client loses their premium "
               "subsidy** and usually drops. **Open** ones are still savable — reach out before they expire.")
    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
    if roster is None:
        _need_book(); return

    def _num(col):
        return (pd.to_numeric(roster[col], errors="coerce").fillna(0)
                if col in roster.columns else pd.Series(0.0, index=roster.index))

    open_mask = ((_num("dmi_outstanding") > 0) | (_num("svi_outstanding") > 0)) & roster["status"].isin(views.ACTIVE)
    exp_mask = roster.get("cancel_reason", pd.Series("", index=roster.index)).astype(str) == "Verification expired"
    fu = roster[open_mask | exp_mask].copy()
    if fu.empty:
        st.success("No outstanding verification follow-ups right now. 🎉"); return
    fu["Status"] = fu.index.map(lambda i: "Open" if open_mask.get(i, False) else "Expired")

    open_n = int((fu["Status"] == "Open").sum())
    exp_n = int((fu["Status"] == "Expired").sum())
    _cards([
        ui.stat_card("Open — Save the Subsidy", f"{open_n:,}", "clock", ui.GOLD),
        ui.stat_card("Expired — Lost", f"{exp_n:,}", "minus", ui.RED),
        ui.stat_card("Total Follow-ups", f"{len(fu):,}", "shield", ui.ELEC),
    ])
    st.markdown("<br>", unsafe_allow_html=True)

    e1, e2, e3 = st.columns(3)
    fs = e1.selectbox("Status", ["Open first", "Open only", "Expired only", "All"], key="fu_status")
    fc = e2.selectbox("Carrier", ["All"] + sorted(fu["carrier"].dropna().astype(str).unique().tolist()), key="fu_carrier")
    fst = e3.selectbox("State", ["All"] + sorted(fu["state"].dropna().astype(str).unique().tolist()), key="fu_state")
    fv = fu.copy()
    if fs == "Open only":
        fv = fv[fv["Status"] == "Open"]
    elif fs == "Expired only":
        fv = fv[fv["Status"] == "Expired"]
    if fc != "All":
        fv = fv[fv["carrier"].astype(str) == fc]
    if fst != "All":
        fv = fv[fv["state"].astype(str) == fst]
    fv = fv.sort_values("Status")  # Open before Expired

    fd = pd.DataFrame({
        "Name": (fv["first_name"].fillna("") + " " + fv["last_name"].fillna("")).str.strip().str.title(),
        "Status": fv["Status"],
        "DMI": pd.to_numeric(fv.get("dmi_outstanding"), errors="coerce").fillna(0).astype(int),
        "SVI": pd.to_numeric(fv.get("svi_outstanding"), errors="coerce").fillna(0).astype(int),
        "Carrier": fv["carrier"],
        "State": fv["state"],
        "Phone": fv.get("phone", ""),
    })
    st.caption(f"Showing **{len(fd)}** follow-ups · open first")
    st.dataframe(fd, use_container_width=True, hide_index=True, height=min(120 + len(fd) * 34, 620))
    st.caption("**Open** items are still savable — reach out before they expire. **Expired** items have "
               "lost the subsidy and move to Cancelled → Re-Engage.")


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
_NO_ROSTER = {"Upload", "Settings", "Book Updates"}


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
        # Apply a pending redirect BEFORE the radio is drawn — Streamlit won't let
        # us change a widget's state after it's instantiated.
        if "_pending_nav" in st.session_state:
            st.session_state["nav"] = st.session_state.pop("_pending_nav")
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
