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

from core import (aor_track, carrier_names, charts, commissions_ingest, daily, dashboard_kpis,
                  ingest_service, paths, settings, tenants, ui, updates, views)

# Product name — drives the browser-tab title and the sidebar/login aria-labels.
# The on-screen wordmark is the fixed two-tone BookPilot logo (see ui.brand_lockup).
APP_NAME = "BookPilot"

# Favicon: a raster PNG (Pillow can open it on every host, unlike SVG) with an emoji
# fallback, so a missing/unsupported icon can never crash set_page_config — which runs
# at module top, so a failure there takes the whole app down ("Oh no. Error running app").
_ICON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "brand", "favicon.png")
st.set_page_config(page_title=APP_NAME, page_icon=(_ICON if os.path.exists(_ICON) else "🧭"), layout="wide")

# Light mode is the default experience; the sidebar toggle switches to dark. Must be
# set BEFORE inject_css() (which reads agent_theme to pick the palette).
st.session_state.setdefault("agent_theme", "light")

ui.inject_css()  # BookPilot theme (cards, sidebar, typography)
st.markdown(
    """
    <style>
      [data-testid="stSidebarNav"]{display:none}
      /* Hide Streamlit's in-app chrome on EVERY page so the product reads clean for
         end users: the Deploy button, the ⋮ menu, the "Fork"/view-source action buttons
         (stToolbarActions — these DO show to every visitor on Community Cloud), the status
         widget, and the footer "Hosted with Streamlit" badge. NOTE: hide only these
         specific elements — NOT the whole stToolbar, because the sidebar's reopen control
         (stExpandSidebarButton) is a sibling inside the toolbar; hiding the toolbar trapped
         a collapsed sidebar with no way to reopen it. (The Community Cloud OWNER overlay —
         Share / Manage-app / the top-right admin icons — is rendered by the outer host
         shell OUTSIDE the app iframe and is gated to the logged-in owner; visitors never
         see it and app CSS cannot reach it.) */
      [data-testid="stDecoration"], [data-testid="stStatusWidget"],
      [data-testid="stAppDeployButton"], [data-testid="stMainMenu"],
      [data-testid="stToolbarActions"], #MainMenu, footer {display:none !important;}
      header[data-testid="stHeader"]{background:transparent !important;}
      /* the sidebar reopen control (shows when collapsed) — make it on-brand, not a
         washed-out grey box. NB: stExpandSidebarButton IS the <button>; its children
         are just the icon spans. */
      [data-testid="stExpandSidebarButton"]{
        background:var(--sidebar-tile) !important; border:1px solid var(--border) !important;
        border-radius:10px !important;}
      [data-testid="stExpandSidebarButton"]:hover{
        background:var(--hover) !important; border-color:var(--accent-blue) !important;}
      [data-testid="stExpandSidebarButton"] span, [data-testid="stExpandSidebarButton"] svg{
        color:var(--accent-blue) !important; fill:var(--accent-blue) !important;}
      /* Primary (blue) buttons: force a white label on every page/theme. Otherwise
         the light-mode markdown rules paint the label dark → unreadable on blue. */
      button[kind="primary"], button[kind="primaryFormSubmit"],
      [data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"],
      button[kind="primary"] p, button[kind="primaryFormSubmit"] p,
      [data-testid="stBaseButton-primary"] p, [data-testid="stBaseButton-primaryFormSubmit"] p,
      [data-testid="stBaseButton-primary"] div, button[kind="primary"] div
      {color:#fff !important; -webkit-text-fill-color:#fff !important;}
      .login-card{max-width:380px;margin:8vh auto 0}
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

def _login_css(theme: str) -> str:
    """Login-screen styling, themed. Light is the default; dark keeps the glass look."""
    light = theme == "light"
    page_bg = (
        "radial-gradient(820px 460px at 50% 8%, rgba(36,116,255,0.10), transparent 60%),"
        "radial-gradient(680px 480px at 12% 82%, rgba(20,85,245,0.08), transparent 55%),"
        "radial-gradient(680px 480px at 88% 74%, rgba(36,116,255,0.07), transparent 55%),#eef4ff"
        if light else
        "radial-gradient(820px 460px at 50% 10%, rgba(59,130,246,0.18), transparent 60%),"
        "radial-gradient(680px 480px at 12% 82%, rgba(37,99,235,0.16), transparent 55%),"
        "radial-gradient(680px 480px at 88% 74%, rgba(124,58,237,0.16), transparent 55%),#060b1a")
    card_bg = "#ffffff" if light else "linear-gradient(160deg, rgba(32,46,88,0.55), rgba(14,22,46,0.6))"
    card_border = "#dce4ee" if light else "rgba(129,140,248,0.34)"
    card_shadow = ("0 24px 64px rgba(15,23,42,0.10),0 2px 8px rgba(15,23,42,0.05)" if light
                   else "0 34px 90px rgba(0,0,0,0.55),0 0 70px rgba(59,130,246,0.14),inset 0 1px 0 rgba(255,255,255,0.05)")
    blur = "none" if light else "blur(16px)"
    sub = "#62728d" if light else "#9fb0cc"
    tab = "#62728d" if light else "#8a98b5"
    tab_active = "#1455F5" if light else "#60a5fa"
    tab_hl = "#1455F5" if light else "#3b82f6"
    label = "#0f172a" if light else "#e6edf7"
    in_bg = "#ffffff" if light else "rgba(9,16,34,0.72)"
    in_border = "#cbd5e1" if light else "rgba(96,165,250,0.28)"
    in_text = "#0f172a" if light else "#e6edf7"
    in_ph = "#94a3b8" if light else "#66768f"
    focus = "#1455F5" if light else "#3b82f6"
    focus_ring = "rgba(20,85,245,0.15)" if light else "rgba(59,130,246,0.18)"
    eye = "#94a3b8" if light else "#66768f"
    eye_hover = "#0f172a" if light else "#e6edf7"
    forgot = "#1455F5" if light else "#60a5fa"
    btn = "linear-gradient(90deg,#1455F5 0%,#2474FF 100%)" if light else "linear-gradient(90deg,#3b82f6 0%,#7c3aed 100%)"
    btn_shadow = "0 12px 28px rgba(20,85,245,0.30)" if light else "0 12px 30px rgba(79,70,229,0.42)"
    return f"""
<style>
  [data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"], footer {{ display:none !important; }}
  header[data-testid="stHeader"] {{ background:transparent; }}

  [data-testid="stAppViewContainer"] {{ background: {page_bg} !important; }}

  /* the card = the centered content block */
  .block-container {{
    max-width: 600px !important; margin: 6vh auto 0 !important; padding: 44px 54px 40px !important;
    background: {card_bg} !important; border: 1px solid {card_border}; border-radius: 26px;
    box-shadow: {card_shadow}; backdrop-filter: {blur};
  }}

  [data-testid="stMarkdownContainer"] div.login-brand {{ margin:0 0 .2rem; }}
  [data-testid="stMarkdownContainer"] p.brand-sub {{ text-align:center; color:{sub} !important; margin:.4rem 0 1.5rem !important; font-size:1.05rem !important; }}

  /* tabs */
  [data-baseweb="tab-list"] {{ justify-content:center; gap:40px; border-bottom:1px solid {in_border} !important; }}
  [data-baseweb="tab"] {{ color:{tab} !important; font-weight:600; font-size:1rem; padding:8px 2px !important; }}
  [data-baseweb="tab"][aria-selected="true"] {{ color:{tab_active} !important; }}
  [data-baseweb="tab-highlight"] {{ background:{tab_hl} !important; height:2px !important; }}

  [data-testid="stTextInput"] label {{ color:{label} !important; font-weight:600; font-size:.95rem; }}

  /* inputs — border ONLY on the outer wrapper (inner stays transparent so password
     fields don't render a doubled border) */
  [data-testid="stTextInput"] [data-baseweb="input"] {{
    background: {in_bg} !important; border: 1px solid {in_border} !important; border-radius: 12px !important;
    background-repeat:no-repeat !important; background-position:15px center !important; background-size:18px 18px !important; overflow:hidden !important;
  }}
  [data-testid="stTextInput"] [data-baseweb="base-input"] {{ background:transparent !important; border:none !important; }}
  [data-testid="stTextInput"]:has(input[type="password"]) [data-baseweb="input"] {{ background-image:url("{_ICON_LOCK}") !important; }}
  [data-testid="stTextInput"]:has(input:not([type="password"])) [data-baseweb="input"] {{ background-image:url("{_ICON_USER}") !important; }}
  [data-testid="stTextInput"] input {{
    background:transparent !important; color:{in_text} !important; -webkit-text-fill-color:{in_text} !important;
    padding: 13px 12px 13px 46px !important; font-size:1rem;
  }}
  [data-testid="stTextInput"] input::placeholder {{ color:{in_ph} !important; -webkit-text-fill-color:{in_ph} !important; }}
  /* reveal-password eye — flat, subtle until hover */
  [data-testid="stTextInput"] [data-baseweb="input"] button {{
    background:transparent !important; border:none !important; box-shadow:none !important; color:{eye} !important; margin-right:6px !important;
  }}
  [data-testid="stTextInput"] [data-baseweb="input"] button:hover {{ color:{eye_hover} !important; }}
  [data-testid="stTextInput"] [data-baseweb="input"]:focus-within {{ border-color:{focus} !important; box-shadow:0 0 0 3px {focus_ring} !important; }}

  .forgot {{ text-align:right; margin:2px 0 6px; }}
  .forgot span {{ color:{forgot}; font-size:.85rem; cursor:pointer; }}

  /* gradient Sign in button */
  [data-testid="stFormSubmitButton"] button {{
    background: {btn} !important; color:#fff !important; font-weight:700 !important; font-size:1.05rem !important;
    border:none !important; border-radius:14px !important; padding:13px !important;
    box-shadow: {btn_shadow} !important; transition:filter .15s ease;
  }}
  /* keep the label white — light-mode markdown rules otherwise paint it grey */
  [data-testid="stFormSubmitButton"] button p,
  [data-testid="stFormSubmitButton"] button div,
  [data-testid="stFormSubmitButton"] button span {{ color:#fff !important; -webkit-text-fill-color:#fff !important; }}
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
    theme = st.session_state.get("agent_theme", "light")
    st.markdown(_login_css(theme), unsafe_allow_html=True)
    name_color = "#06143D" if theme == "light" else "#ffffff"
    st.markdown(
        f'<div class="login-brand">{ui.brand_lockup(icon_px=62, text_rem=3.4, name_color=name_color, gap=18, center=True)}</div>',
        unsafe_allow_html=True)
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
def _ago(iso: str) -> str:
    """Human 'x ago' from an ISO timestamp."""
    try:
        t = dt.datetime.fromisoformat(iso)
    except Exception:
        return ""
    secs = (dt.datetime.now() - t).total_seconds()
    if secs < 90:
        return "just now"
    if secs < 5400:
        return f"{int(secs // 60)} min ago"
    if secs < 129600:
        return f"{int(secs // 3600)} hr ago"
    if secs < 1209600:
        return f"{int(secs // 86400)} days ago"
    return t.strftime("%b %d, %Y")


def _last_up(ups: dict, key: str) -> None:
    """Caption showing when a source was last uploaded (nothing if never)."""
    if ups.get(key):
        st.caption(f"✅ Last uploaded {_ago(ups[key])}")
    else:
        st.caption("—  not uploaded yet")


# ── Upload page look (hero icon, section pills, file cards) ──────────────────────
_CLOUD_SVG = ('<svg viewBox="0 0 24 24" width="30" height="30" fill="none" stroke="#ffffff" '
              'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
              '<path d="M16 16l-4-4-4 4"/><path d="M12 12v9"/>'
              '<path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg>')

# Carrier accent colors for the file icon on each carrier card.
_CARRIER_ICON = {"ambetter": "#a78bfa", "oscar": "#22c55e", "anthem": "#3b82f6", "uhc": "#ec4899"}


def _file_icon(color: str) -> str:
    return (f'<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="{color}" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
            f'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>'
            f'<polyline points="14 2 14 8 20 8"/></svg>')


def _up_section(title: str, tail: str, pill: str, pill_cls: str, sub: str) -> str:
    return (f'<div class="up-sec"><span class="up-sec-t">{title}</span>'
            f'<span class="up-sec-tail"> • {tail}</span>'
            f'<span class="up-pill {pill_cls}">{pill}</span></div>'
            f'<div class="up-sec-sub">{sub}</div>')


def _up_status(ups: dict, key: str) -> None:
    if ups.get(key):
        st.markdown(f'<div class="up-status ok">✓ Last updated {_ago(ups[key])}</div>',
                    unsafe_allow_html=True)
    else:
        st.markdown('<div class="up-status">— not uploaded yet</div>', unsafe_allow_html=True)


_UPLOAD_CSS = """
<style>
  .up-hero{display:flex;align-items:center;gap:16px;margin:2px 0 20px;}
  .up-hero-ic{width:58px;height:58px;border-radius:16px;display:flex;align-items:center;
    justify-content:center;flex:0 0 auto;background:linear-gradient(135deg,#3b82f6,#7c3aed);
    box-shadow:0 8px 26px rgba(124,58,237,.38);}
  .up-hero-title{font-size:2rem;font-weight:800;color:var(--text);line-height:1.05;letter-spacing:-.01em;}
  .up-hero-sub{font-size:.9rem;color:var(--text2);margin-top:4px;max-width:640px;}
  .up-sec{display:flex;align-items:center;gap:2px;margin:26px 0 2px;}
  .up-sec-t{font-size:1.32rem;font-weight:800;color:var(--text);}
  .up-sec-tail{font-size:1.32rem;font-weight:400;color:var(--text3);}
  .up-pill{font-size:.6rem;font-weight:800;letter-spacing:.09em;padding:3px 9px;border-radius:999px;margin-left:10px;}
  .up-pill.req{background:rgba(59,130,246,.18);color:#7dd3fc;border:1px solid rgba(59,130,246,.42);}
  .up-pill.opt{background:rgba(148,163,184,.14);color:var(--text2);border:1px solid rgba(148,163,184,.30);}
  .up-sec-sub{font-size:.85rem;color:var(--text3);margin:0 0 12px;max-width:760px;}
  .up-card-h{display:flex;align-items:center;gap:9px;font-weight:700;color:var(--text);
    font-size:.98rem;margin-bottom:8px;}
  .up-status{font-size:.8rem;color:var(--text3);margin-top:6px;}
  .up-status.ok{color:#22c55e;font-weight:600;}
  .up-foot{margin-top:28px;padding-top:14px;border-top:1px solid rgba(96,165,250,.14);
    font-size:.82rem;color:var(--text3);}
  /* upload cards */
  [class*="st-key-upcard_"]{background:var(--panel-solid);border:1px solid rgba(96,165,250,.16)!important;
    border-radius:16px!important;padding:16px 18px!important;}
  [class*="st-key-upcard_"] [data-testid="stFileUploaderDropzone"]{
    background:var(--input-bg);border:1.5px dashed rgba(96,165,250,.30);border-radius:12px;}
</style>
"""


def page_upload(tenant: dict) -> None:
    agent_id = tenant["agent_id"]
    st.markdown(_UPLOAD_CSS, unsafe_allow_html=True)
    st.markdown(
        f'<div class="up-hero"><div class="up-hero-ic">{_CLOUD_SVG}</div>'
        f'<div><div class="up-hero-title">Upload your files</div>'
        f'<div class="up-hero-sub">HealthSherpa data is your whole book. The carrier files '
        f'add your payments, disputes, and policy IDs on top.</div></div></div>',
        unsafe_allow_html=True)

    if not str(tenant.get("npn", "")).strip():
        st.warning("Set your **NPN** on the **Settings** page before uploading — without it "
                   "we can't tell which clients in the file are yours.", icon="⚠️")
        return

    ups = ingest_service.last_uploads(agent_id)

    # ── HealthSherpa export (required) ───────────────────────────────────────────
    st.markdown(_up_section(
        "HealthSherpa export", "required", "REQUIRED", "req",
        "Clients → Export · Custom date range 01/01/2025 → today · both boxes checked."),
        unsafe_allow_html=True)
    with st.container(border=True, key="upcard_hs"):
        hs = st.file_uploader("HealthSherpa (.csv)", type=["csv"], key="hs",
                              label_visibility="collapsed")
        _up_status(ups, "healthsherpa")
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
                        updates.compute_and_log(agent_id, roster,
                                                npn=tenant.get("npn", ""), name=tenant.get("name", ""))
                    st.success(f"Done — read {len(df):,} rows. Taking you to your **Book Updates**…")
                    st.session_state["_pending_nav"] = "Book Updates"
                    st.rerun()
            except (Exception, SystemExit) as e:
                st.error(f"Couldn't read that file: {e}")

    # ── State marketplaces (optional) ────────────────────────────────────────────
    st.markdown(_up_section(
        "State marketplaces", "optional", "OPTIONAL", "opt",
        "Some states run their own exchange instead of HealthSherpa (Get Covered IL, Georgia "
        "Access, Virginia). Add those clients here — enrolled ones merge into your book "
        "(shopping leads are skipped, and anyone already in HealthSherpa isn't double-counted)."),
        unsafe_allow_html=True)
    scols = st.columns(3)
    for i, (skey, sspec) in enumerate(ingest_service.state_sources().items()):
        with scols[i % 3]:
            with st.container(border=True, key=f"upcard_state_{skey}"):
                st.markdown(f'<div class="up-card-h">{sspec["label"]} (csv)</div>',
                            unsafe_allow_html=True)
                sup = st.file_uploader(sspec["label"], type=["csv"], key=f"se_{skey}",
                                       label_visibility="collapsed")
                _up_status(ups, f"state_{skey}")
                if sup is not None and st.button("Add these clients", key=f"se_btn_{skey}",
                                                 type="primary", use_container_width=True):
                    try:
                        with st.spinner("Reading and merging…"):
                            _snap, sdf = ingest_service.ingest_state_exchange(agent_id, sup.getvalue(), skey)
                            roster = ingest_service.build_book(agent_id, tenant.get("npn", ""), tenant.get("name", ""))
                            if roster is not None:
                                updates.compute_and_log(agent_id, roster,
                                                        npn=tenant.get("npn", ""), name=tenant.get("name", ""))
                        st.success(f"Added — {len(sdf):,} enrolled clients merged. Your update summary "
                                   f"is on the **Book Updates** page.")
                        st.session_state["_pending_nav"] = "Book Updates"
                        st.rerun()
                    except (Exception, SystemExit) as e:
                        st.error(f"Couldn't read that file: {e}")

    # ── Carrier books (optional) ─────────────────────────────────────────────────
    st.markdown(_up_section(
        "Carrier books", "optional", "OPTIONAL", "opt",
        "Add these to unlock the payment & dispute checks. Stored privately in your workspace."),
        unsafe_allow_html=True)
    cols = st.columns(2)
    for i, (key, spec) in enumerate(ingest_service.carriers().items()):
        with cols[i % 2]:
            with st.container(border=True, key=f"upcard_carrier_{key}"):
                st.markdown(
                    f'<div class="up-card-h">{_file_icon(_CARRIER_ICON.get(key, "#60a5fa"))}'
                    f'<span>{spec["label"]} ({spec["types"][0]})</span></div>',
                    unsafe_allow_html=True)
                up = st.file_uploader(spec["label"], type=spec["types"], key=key,
                                      label_visibility="collapsed")
                _up_status(ups, key)
                if up is not None:
                    try:
                        ingest_service.save_carrier(agent_id, key, up.getvalue())
                        st.success(f"{spec['label']} saved ✓")
                    except Exception as e:
                        st.error(f"{spec['label']}: {e}")

    st.markdown('<div class="up-foot">ℹ️ Need help? Visit the <b>support center</b> or reach out '
                'to your admin.</div>', unsafe_allow_html=True)


_NAMES = {"first_name": "First", "last_name": "Last", "carrier": "Carrier",
          "state": "State", "status": "Status", "effective_date": "Effective",
          "term_date": "Ended", "taken_by": "Now with"}


def _table(df: pd.DataFrame, cols: list, empty: str) -> None:
    if df is not None and not df.empty:
        df = df[[c for c in cols if c in df.columns]].rename(columns=_NAMES)
    ui.styled_table(df, empty=empty)


def _need_book() -> None:
    st.info("No book yet — upload your HealthSherpa export on the **Upload** page.", icon="📥")


def _cards(htmls: list) -> None:
    for col, html in zip(st.columns(len(htmls)), htmls):
        col.markdown(html, unsafe_allow_html=True)


def _hdr(title: str, icon: str) -> None:
    st.markdown(ui.section_header(title, icon), unsafe_allow_html=True)


def _stat(html: str) -> None:
    st.columns(3)[0].markdown(html, unsafe_allow_html=True)


# ── Book Updates: summary cards + upload-history timeline ───────────────────────
_BU_CHECK = ("<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2.2' stroke-linecap='round' "
             "stroke-linejoin='round'><circle cx='12' cy='12' r='10'/><path d='M8 12.3l2.6 2.6L16 9.4'/></svg>")
_BU_X = ("<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2.2' stroke-linecap='round' "
         "stroke-linejoin='round'><circle cx='12' cy='12' r='10'/><path d='M15 9l-6 6M9 9l6 6'/></svg>")
_BU_STAR = ("<svg viewBox='0 0 24 24' fill='currentColor' stroke='currentColor' stroke-width='1.1' "
            "stroke-linejoin='round'><polygon points='12 2.6 14.9 8.6 21.5 9.3 16.5 13.9 18 20.5 12 17 6 20.5 7.5 13.9 2.5 9.3 9.1 8.6'/></svg>")
_BU_FILE = ("<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' "
            "stroke-linejoin='round'><path d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z'/>"
            "<polyline points='14 2 14 8 20 8'/></svg>")
_BU_INFO = ("<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' "
            "stroke-linejoin='round'><circle cx='12' cy='12' r='10'/><line x1='12' y1='16' x2='12' y2='12'/>"
            "<line x1='12' y1='8' x2='12.01' y2='8'/></svg>")
_BU_UP = ("<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' "
          "stroke-linejoin='round'><path d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'/>"
          "<polyline points='7 10 12 15 17 10'/><line x1='12' y1='15' x2='12' y2='3'/></svg>")
_BU_AOR = ("<svg viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' "
           "stroke-linejoin='round'><path d='M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2'/><circle cx='9' cy='7' r='4'/>"
           "<line x1='17' y1='8' x2='22' y2='13'/><line x1='22' y1='8' x2='17' y2='13'/></svg>")

_BU_CSS = """<style>
.bu-summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin:8px 0 30px;}
.bu-sc{display:flex;align-items:center;gap:16px;background:var(--panel-solid);border:1px solid var(--border);
 border-radius:16px;box-shadow:var(--card-shadow);padding:20px 22px;min-width:0;}
.bu-sc-ic{width:52px;height:52px;flex:0 0 52px;border-radius:999px;display:grid;place-items:center;}
.bu-sc-ic svg{width:24px;height:24px;}
.bu-sc-l{font-size:13.5px;font-weight:650;color:var(--text);}
.bu-sc-v{font-size:28px;font-weight:800;line-height:1;letter-spacing:-.02em;margin-top:4px;}
.bu-sc-d{font-size:12.5px;color:var(--text2);margin-top:7px;}
.bu-sc.sg .bu-sc-ic{background:var(--bu-sg-bg);color:var(--bu-sg-tx);} .bu-sc.sg .bu-sc-v{color:var(--bu-sg-tx);}
.bu-sc.cx .bu-sc-ic{background:var(--bu-cx-bg);color:var(--bu-cx-tx);} .bu-sc.cx .bu-sc-v{color:var(--bu-cx-tx);}
.bu-sc.wb .bu-sc-ic{background:var(--bu-wb-bg);color:var(--bu-wb-tx);} .bu-sc.wb .bu-sc-v{color:var(--bu-wb-tx);}
.bu-sc.up .bu-sc-ic{background:var(--pill-bg);color:var(--accent-blue);} .bu-sc.up .bu-sc-v{color:var(--accent-blue);}
.bu-sc.ar .bu-sc-ic{background:var(--bu-ar-bg);color:var(--bu-ar-tx);} .bu-sc.ar .bu-sc-v{color:var(--bu-ar-tx);}
.bu-tl{position:relative;padding-left:92px;}
.bu-tl::before{content:"";position:absolute;top:26px;bottom:32px;left:15px;width:2px;background:var(--border);}
.bu-item{position:relative;margin-bottom:20px;}
.bu-dot{position:absolute;left:-85px;top:24px;width:16px;height:16px;border:4px solid var(--panel-solid);
 border-radius:999px;background:var(--accent-blue);box-shadow:0 0 0 1px var(--pill-bd);z-index:2;}
.bu-ic{position:absolute;left:-64px;top:8px;width:44px;height:44px;border-radius:999px;background:var(--pill-bg);
 border:1px solid var(--pill-bd);color:var(--accent-blue);display:grid;place-items:center;z-index:2;}
.bu-ic svg{width:20px;height:20px;}
.bu-card{background:var(--panel-solid);border:1px solid var(--border);border-radius:16px;
 box-shadow:var(--card-shadow);overflow:hidden;}
.bu-hd{min-height:56px;display:flex;align-items:center;justify-content:space-between;gap:16px;
 padding:14px 22px;border-bottom:1px solid var(--border);}
.bu-hd-t{font-size:14.5px;font-weight:700;color:var(--text);}
.bu-body{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));padding:20px 22px;}
.bu-sec{min-width:0;padding:0 16px;}
.bu-sec:first-child{padding-left:0;} .bu-sec:last-child{padding-right:0;}
.bu-sec + .bu-sec{border-left:1px solid var(--border);}
.bu-sh{display:flex;align-items:center;gap:8px;margin-bottom:12px;flex-wrap:wrap;}
.bu-sh svg{width:18px;height:18px;flex:0 0 18px;}
.bu-sl{font-size:13px;font-weight:700;color:var(--text);}
.bu-cnt{font-size:12.5px;color:var(--text2);}
.bu-pills{display:flex;flex-wrap:wrap;gap:7px;align-items:flex-start;}
.bu-pill{display:inline-flex;align-items:center;padding:4px 10px;border-radius:999px;font-size:12px;
 line-height:1.2;border:1px solid transparent;white-space:nowrap;max-width:100%;}
.bu-pill.sg{color:var(--bu-sg-tx);background:var(--bu-sg-bg);border-color:var(--bu-sg-bd);}
.bu-pill.cx{color:var(--bu-cx-tx);background:var(--bu-cx-bg);border-color:var(--bu-cx-bd);}
.bu-pill.wb{color:var(--bu-wb-tx);background:var(--bu-wb-bg);border-color:var(--bu-wb-bd);}
.bu-pill.ar{color:var(--bu-ar-tx);background:var(--bu-ar-bg);border-color:var(--bu-ar-bd);}
.bu-more{display:inline-block;}
.bu-more>summary{list-style:none;cursor:pointer;color:var(--text2)!important;background:var(--input-bg)!important;border-color:var(--border)!important;}
.bu-more>summary::-webkit-details-marker{display:none;} .bu-more>summary::marker{content:"";}
.bu-empty{font-size:13px;color:var(--text2);}
.bu-baseline{display:flex;align-items:center;gap:10px;margin:16px 22px 20px;padding:12px 14px;
 background:var(--pill-bg);border:1px solid var(--pill-bd);border-radius:11px;color:var(--text);font-size:13px;}
.bu-baseline svg{width:18px;height:18px;flex:0 0 18px;color:var(--accent-blue);}
.bu-end{display:inline-flex;align-items:center;gap:7px;padding:8px 14px;color:var(--text2);
 background:var(--input-bg);border:1px solid var(--border);border-radius:999px;font-size:12px;}
@media(max-width:1000px){.bu-body{grid-template-columns:1fr;}
 .bu-sec{padding:16px 0;} .bu-sec:first-child{padding-top:0;} .bu-sec:last-child{padding-bottom:0;}
 .bu-sec + .bu-sec{border-left:0;border-top:1px solid var(--border);}
 .bu-ic{display:none;} .bu-tl{padding-left:30px;} .bu-tl::before{left:9px;} .bu-dot{left:-27px;}}
@media(max-width:560px){.bu-summary{grid-template-columns:1fr;}}
</style>"""


def _bu_esc(s) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _bu_names(names: list, cls: str) -> str:
    names = [n for n in names if str(n).strip()]
    if not names:
        return '<div class="bu-empty">No changes</div>'
    def pill(n):
        return f'<span class="bu-pill {cls}">{_bu_esc(n)}</span>'
    vis, rest = names[:6], names[6:]
    out = "".join(pill(n) for n in vis)
    if rest:
        out += ('<details class="bu-more"><summary class="bu-pill">+' + str(len(rest)) +
                ' more</summary><div class="bu-pills" style="margin-top:8px">'
                + "".join(pill(n) for n in rest) + '</div></details>')
    return f'<div class="bu-pills">{out}</div>'


def _bu_section(icon: str, color: str, cls: str, label: str, counts: str, names: list) -> str:
    head = (f'<div class="bu-sh"><span style="display:inline-flex;color:{color}">{icon}</span>'
            f'<span class="bu-sl">{label}</span><span class="bu-cnt">· {counts}</span></div>')
    return f'<div class="bu-sec">{head}{_bu_names(names, cls)}</div>'


def _bu_cx_names(e: dict) -> list:
    # Genuine cancellations (+ verification-expired) → Re-Engage. AOR steals are
    # kept separate (e["taken"]) so they show in their own column.
    return list(e.get("lost", [])) + list(e.get("vexp", []))


def page_updates(tenant: dict, roster) -> None:
    st.title("Book Updates")
    st.caption("Track changes each time you upload — the same rundown you'd get by text.")
    st.markdown(_BU_CSS, unsafe_allow_html=True)
    hist = updates.history(tenant["agent_id"])
    if not hist:
        st.info("No updates yet — upload a HealthSherpa export and your summary shows up here.", icon="📥")
        return

    cards = []
    for e in hist:  # history is stored newest-first (log.insert(0, ...))
        hd = (f'<div class="bu-hd"><span class="bu-hd-t" style="display:inline-flex;align-items:center;gap:7px;">'
              f'{ui.brand_icon_svg(15)}Book updated · {_bu_esc(e.get("date", ""))}</span></div>')
        if e.get("first"):
            body = ('<div class="bu-baseline">' + _BU_INFO
                    + '<span>First upload — baseline set. Changes appear starting with your next upload.</span></div>')
        else:
            sg = _bu_section(_BU_CHECK, "var(--bu-sg-tx)", "sg", "Signed",
                             f'{int(e.get("signed", 0) or 0)} new policies / {int(e.get("members", 0) or 0)} members',
                             e.get("signed_names", []))
            cxn = _bu_cx_names(e)
            cx = _bu_section(_BU_X, "var(--bu-cx-tx)", "cx", "Cancelled", f'{len(cxn)} policies', cxn)
            arn = list(e.get("taken", []))
            ar = _bu_section(_BU_AOR, "var(--bu-ar-tx)", "ar", "AOR Taken", f'{len(arn)} policies', arn)
            won = e.get("won", [])
            wb = _bu_section(_BU_STAR, "var(--bu-wb-tx)", "wb", "Won Back", f'{len(won)} policies', won)
            body = f'<div class="bu-body">{sg}{cx}{ar}{wb}</div>'
        cards.append(f'<div class="bu-item"><span class="bu-dot"></span>'
                     f'<span class="bu-ic">{_BU_UP}</span><div class="bu-card">{hd}{body}</div></div>')

    st.markdown('<div class="bu-tl">' + "".join(cards) + '</div>', unsafe_allow_html=True)
    st.markdown('<div style="text-align:center;margin-top:8px"><span class="bu-end">▲ '
                "You've reached the beginning</span></div>", unsafe_allow_html=True)


def page_dashboard(tenant: dict, roster) -> None:
    st.title("ACA Dashboard")
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

    # "Added / month" averages over year-to-date (Feb of the current year forward),
    # matching Ethan's site — so the sublabel must show that YTD window, not the
    # book's earliest month.
    added_label, added_abbr = "your first month", "start"
    if mom is not None and not getattr(mom, "empty", True) and "Month" in mom.columns:
        _ytd = mom[mom["Month"] >= f"{dt.date.today().year}-02"]
        _win = _ytd if not _ytd.empty else mom
        _aw = pd.to_datetime(_win["Month"], errors="coerce").min()
        if pd.notna(_aw):
            added_label, added_abbr = _aw.strftime("%b %Y"), _aw.strftime("%b")
    since_sub = f"{added_label} – present"
    net_sub = f"Added ({added_abbr}+) minus Lost (all-time)"

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

    _mom_len = 0 if (mom is None or getattr(mom, "empty", True)) else len(mom)
    if _mom_len < 3:
        st.caption(
            "Not much dated history in this upload yet — growth metrics sharpen as "
            "more of your book's history comes through."
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
            f'<div><div class="in-main">{new_pct}% of your book is under 6 months old (higher OEP risk)</div>'
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
        ui.theme_fig(fig)
        evt = st.plotly_chart(fig, use_container_width=True, on_select="rerun",
                              key=f"daily_chart_{ym}",
                              config={"displayModeBar": False, "scrollZoom": False, "doubleClick": False})
        st.caption("💡 Click any bar to see who you signed that day.")
    with col_table, st.container(border=True):
        st.markdown(ui.chart_head("Day-by-Day Breakdown", "Daily policies & members", "calendar"),
                    unsafe_allow_html=True)
        tbl = ddf.copy()
        tbl["Day"] = tbl["Date"].dt.strftime("%b %d")
        ui.styled_table(tbl[["Day", "Policies", "Members"]], height=430, bare=True)

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
                ui.styled_table(show, height=min(80 + len(show) * 35, 460), bare=True)


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
        disp = disp[["Month"] + [c for c in disp.columns if c != "Month"]].copy()
        if "% Growth" in disp.columns:
            disp["% Growth"] = pd.to_numeric(disp["% Growth"], errors="coerce").map(
                lambda v: f"{v:.1f}%" if pd.notna(v) else "—")
        if "Net Change" in disp.columns:
            disp["Net Change"] = pd.to_numeric(disp["Net Change"], errors="coerce").map(
                lambda v: f"{v:+d}" if pd.notna(v) else "—")
        ui.styled_table(disp, height=560, bare=True)


_LOOKUP_CSS = """<style>
  .st-key-lookup_hero {max-width:620px;}
  .st-key-lookup_hero div[data-baseweb="select"] > div {
      font-size:1.08rem; padding:8px 12px; border-radius:14px;
      background:var(--input-bg); border:1.5px solid rgba(96,165,250,.4);
      box-shadow:var(--card-shadow);}
  /* Force the typed text + selected value dark/readable in both themes (the exact
     BaseWeb DOM path shifts between versions, so cover the value div/span + input). */
  .st-key-lookup_hero div[data-baseweb="select"] div,
  .st-key-lookup_hero div[data-baseweb="select"] span,
  .st-key-lookup_hero div[data-baseweb="select"] input,
  .st-key-lookup_hero input {
      color:var(--text) !important; -webkit-text-fill-color:var(--text) !important;
      caret-color:var(--text) !important; opacity:1 !important;}
  /* When the selected value is auto-highlighted, keep it readable (dark on pale blue). */
  .st-key-lookup_hero *::selection {
      background:#cfe2ff !important; color:#0f172a !important; -webkit-text-fill-color:#0f172a !important;}
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
    pid_txt = (f" · Policy ID: <span style='color:var(--accent-blue);font-weight:700;'>{pid}</span>"
               if pid and pid.lower() not in ("nan", "none") else "")
    st.markdown(
        f"<div style='display:flex;align-items:center;gap:14px;margin:6px 0 2px;'>"
        f"<span style='font-size:1.6rem;font-weight:800;color:var(--text);'>{person}</span>"
        f"<span style='background:{pill_bg};color:{pill_tx};padding:3px 12px;border-radius:999px;"
        f"font-size:.8rem;font-weight:700;'>{r.get('status', '?')}</span></div>"
        f"<div style='color:var(--text2);font-size:.95rem;margin-bottom:10px;'>"
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
        st.error(f"Agent of record is **{who}** — this client is on your AOR at Risk page.", icon="🚨")

    # ── Stat cards ──────────────────────────────────────────────────────────────
    prem = pd.to_numeric(r.get("net_premium"), errors="coerce")
    mob = pd.to_numeric(r.get("months_on_book"), errors="coerce")
    _cards([
        ui.stat_card("Members", f"{_mem}", "users", ui.CYAN),
        ui.stat_card("Net Premium / Mo", f"${prem:,.0f}" if pd.notna(prem) else "—", "dollar", ui.GREEN),
        ui.stat_card("Months on Book",
                     ("<1" if int(mob) == 0 else f"{int(mob)}") if pd.notna(mob) else "—", "calendar", ui.ELEC),
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
                   "risk until submitted (see Documents Due).", icon="⚠️")

    # ── Policies (history) ──────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown(ui.chart_head("Policies", f"{len(rows)} on record for {person}", "file"),
                    unsafe_allow_html=True)
        pc = [c for c in ["carrier", "policy_number", "status", "effective_date", "term_date",
                          "net_premium", "applicant_count", "cancel_reason"] if c in rows.columns]
        pt = rows[pc].rename(columns={
            "carrier": "Carrier", "policy_number": "Policy ID", "status": "Status",
            "effective_date": "Effective", "term_date": "Term Date", "net_premium": "Premium",
            "applicant_count": "Members", "cancel_reason": "Why Ended"}).copy()
        for _dc in ("Effective", "Term Date"):
            if _dc in pt.columns:
                pt[_dc] = pd.to_datetime(pt[_dc], errors="coerce").dt.strftime("%b %-d, %Y")
        if "Premium" in pt.columns:
            pt["Premium"] = pd.to_numeric(pt["Premium"], errors="coerce").map(
                lambda v: f"${v:,.2f}" if pd.notna(v) else "—")
        ui.styled_table(pt, bare=True)


def _commission_upload(agent_id: str) -> None:
    """Upload any commission statement → auto-map columns (saved per format) → canonical records."""
    recs = commissions_ingest.load_records(agent_id)
    with st.expander("➕  Add a commission statement", expanded=recs.empty):
        st.caption("CSV, Excel, or PDF — whatever layout your carrier or upline sends. You map the "
                   "columns once, and we remember the format for next time. (PDF tables are "
                   "auto-extracted; just double-check the columns before saving.)")
        up = st.file_uploader("Commission statement (.csv / .xlsx / .pdf)",
                              type=["csv", "xlsx", "xls", "pdf"],
                              key="comm_up", label_visibility="collapsed")
        if up is None:
            return
        try:
            df = commissions_ingest.read_table(up.getvalue(), up.name)
        except Exception as e:
            st.error(f"Couldn't read that file: {e}")
            return
        if df.empty:
            st.warning("That file has no rows.")
            return

        sig = commissions_ingest.header_sig(df)
        saved = commissions_ingest.saved_maps(agent_id).get(sig)
        mapping0 = saved or commissions_ingest.detect(df)
        st.caption("Using your saved column setup for this format ✓" if saved
                   else "We auto-detected your columns — check them and fix any that are off.")
        st.dataframe(df.head(5), use_container_width=True, hide_index=True)

        opts = ["(none)"] + [str(c) for c in df.columns]
        chosen, mcols = {}, st.columns(len(commissions_ingest.CANON))
        for (key, label, req), col in zip(commissions_ingest.CANON, mcols):
            default = mapping0.get(key)
            idx = opts.index(default) if default in opts else 0
            sel = col.selectbox(label + (" *" if req else ""), opts, index=idx, key=f"cm_{key}")
            chosen[key] = None if sel == "(none)" else sel

        # Capture check: does the parsed sum match the statement's own printed total?
        stated = commissions_ingest.stated_total(up.getvalue(), up.name)
        if chosen.get("amount"):
            try:
                preview = commissions_ingest.parse(df, chosen, up.name)
                psum = float(preview["amount"].sum())
                if stated is not None and abs(psum - stated) < 0.5:
                    st.success(f"Captured ${psum:,.2f} across {len(preview):,} lines — "
                               f"matches the statement's total ✓")
                elif stated is not None:
                    st.warning(f"Captured ${psum:,.2f}, but the statement's total says "
                               f"${stated:,.2f} (off by ${abs(psum - stated):,.2f}). "
                               f"Double-check the amount column before saving.")
                else:
                    st.caption(f"Captured ${psum:,.2f} across {len(preview):,} lines.")
            except Exception:
                pass

        if st.button("Save & add", type="primary"):
            try:
                new = commissions_ingest.parse(df, chosen, up.name)
                if new.empty:
                    st.warning("No commission rows found with that mapping — double-check the amount column.")
                    return
                total = commissions_ingest.save_records(agent_id, new, chosen, sig)
                st.success(f"Added {len(new):,} records from {up.name}. {total:,} on file now.")
                st.rerun()
            except Exception as e:
                st.error(str(e))


def page_commissions(tenant: dict, roster) -> None:
    agent_id = tenant["agent_id"]
    st.title("Commissions")
    st.caption("Track commission you've actually been paid — upload any statement format — and see "
               "what your active book projects to earn on top.")
    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)

    # ── Money received (actual, from uploaded statements) ───────────────────────
    _hdr("Money Received", "dollar")
    _commission_upload(agent_id)
    recs = commissions_ingest.load_records(agent_id)
    if recs.empty:
        st.info("No commission statements yet — add one above to see money received.")
    else:
        s = commissions_ingest.summary(recs)
        _cards([
            ui.metric_card("Total Received", f"${s['total']:,.0f}", sub=f"{len(recs):,} line items",
                           icon_key="dollar", highlight="green"),
            ui.metric_card("Latest Month", f"${s['this_month']:,.0f}",
                           sub=(s["by_month"]["Month"].max() if not s["by_month"].empty else "add a date column"),
                           icon_key="calendar"),
            ui.metric_card("Carriers Paying", f"{s['by_carrier'].shape[0]}", sub="distinct carriers", icon_key="pie"),
        ])
        st.markdown("<br>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            with st.container(border=True):
                st.markdown(ui.chart_head("Paid by Carrier", "Actual commission received per carrier", "pie"),
                            unsafe_allow_html=True)
                bc = s["by_carrier"].copy()
                bc["Paid"] = bc["Paid"].map(lambda v: f"${v:,.0f}")
                ui.styled_table(bc, height=min(46 + 35 * (len(bc) + 1), 420), bare=True)
        with c2:
            with st.container(border=True):
                st.markdown(ui.chart_head("Paid by Month", "Commission received over time", "trend"),
                            unsafe_allow_html=True)
                bm = s["by_month"]
                if bm.empty:
                    st.caption("Map a payment-date column to see the monthly trend.")
                else:
                    st.bar_chart(bm.set_index("Month")["Paid"], color="#22c55e", height=300)
        st.caption("Money Received comes straight from your uploaded statements. "
                   "Re-uploading the same file replaces its rows (no double-counting).")

    # ── Commission gaps (reconcile paid records against the book) ────────────────
    if not recs.empty:
        st.markdown("<br>", unsafe_allow_html=True)
        st.divider()
        _hdr("Commission Gaps", "shield")
        if roster is None:
            st.info("Upload your HealthSherpa book on the **Upload** page to cross-check who "
                    "you're actually being paid on.")
        else:
            rec = commissions_ingest.reconcile(roster, recs)
            if not rec["reconcilable"]:
                st.info("These statements don't include client names or policy IDs, so per-client "
                        "gap-checking isn't possible yet. Re-add a statement and map a **Client** or "
                        "**Policy / member ID** column to unlock this.")
            else:
                full = rec["active"] > 0 and rec["paid"] == rec["active"]
                _cards([
                    ui.metric_card("Paid Coverage", f"{rec['paid']}/{rec['active']}",
                                   sub="active clients you're paid on", icon_key="users",
                                   highlight="green" if full else False),
                    ui.metric_card("Gaps to Chase", f"{len(rec['gaps']):,}",
                                   sub="active but unpaid or stopped", icon_key="minus",
                                   highlight="gold" if len(rec["gaps"]) else "green"),
                    ui.metric_card("$/mo At Risk", f"${rec['monthly_gap']:,.0f}",
                                   sub="commission you may be owed", icon_key="dollar",
                                   highlight="red" if rec["monthly_gap"] else False),
                ])
                if rec["gaps"].empty:
                    st.success("Every active client has a matching commission — no gaps found. 🎉")
                else:
                    st.markdown("<br>", unsafe_allow_html=True)
                    with st.container(border=True):
                        st.markdown(ui.chart_head("Active clients you're not getting paid on",
                            "“Never paid” = no matching commission on record. “Stopped” = paid "
                            "before, nothing in the last 2 statement months (likely a dispute to file).", "minus"),
                            unsafe_allow_html=True)
                        gdf = rec["gaps"].copy()
                        gdf["Est $/mo"] = gdf["Est $/mo"].map(lambda v: f"${v:,.0f}")
                        ui.styled_table(gdf, height=min(46 + 35 * (len(gdf) + 1), 600), bare=True)
                    if rec["unmatched"]:
                        st.caption(f"↳ {rec['unmatched']} payment name(s) didn't match an active client — "
                                   "usually churned clients or a name spelled differently on the statement.")

    st.markdown("<br>", unsafe_allow_html=True)
    st.divider()

    # ── Projected from the active book (members × $23/mo) ────────────────────────
    _hdr("Projected from Your Book", "trend")
    if roster is None:
        st.info("Upload your HealthSherpa export on the **Upload** page to see projected commission.")
        return
    d = dashboard_kpis.compute(tenant["agent_id"], roster)
    PMPM, MAX_TENURE = 23, 60
    members = int(d["members"])
    mom = d.get("mom")

    # LTV from all-time churn (same basis as the Goals page).
    if mom is not None and not getattr(mom, "empty", True) and {"Members Lost", "Total Members"}.issubset(mom.columns):
        churn_rate = mom["Members Lost"].sum() / max(mom["Total Members"].sum(), 1)
    else:
        churn_rate = 0.0
    tenure = min(1 / churn_rate if churn_rate > 0 else MAX_TENURE, MAX_TENURE)
    ltv_per = round(PMPM * tenure)
    book_ltv = members * ltv_per

    # ── Recurring revenue ───────────────────────────────────────────────────────
    _hdr("Recurring Revenue", "dollar")
    _cards([
        ui.metric_card("Expected Monthly", f"${d['comm_monthly']:,.0f}",
                       sub=f"{members:,} members × ${PMPM}/mo", icon_key="dollar", highlight="green"),
        ui.metric_card("Expected Annual", f"${d['comm_annual']:,.0f}", sub="MRR × 12 months", icon_key="calendar"),
        ui.metric_card("Per Policy / Mo", f"${d['per_policy']:.2f}", sub="MRR ÷ active policies", icon_key="file"),
    ])
    st.markdown("<br>", unsafe_allow_html=True)

    # ── Lifetime value ──────────────────────────────────────────────────────────
    _hdr("Lifetime Value", "trend")
    _cards([
        ui.metric_card("LTV per Member", f"${ltv_per:,}",
                       sub=f"${PMPM}/mo × {tenure:.0f}-mo tenure", icon_key="users"),
        ui.metric_card("Total Book LTV", f"${book_ltv:,.0f}",
                       sub=f"{members:,} members × ${ltv_per:,}", icon_key="shield", highlight="green"),
        ui.metric_card("Avg Client Tenure", f"{tenure:.0f} mo",
                       sub=f"{churn_rate * 100:.2f}% monthly churn", icon_key="calendar"),
    ])
    st.markdown("<br>", unsafe_allow_html=True)

    # ── Where the commission comes from (per carrier) ───────────────────────────
    a = views.active(roster)
    if not a.empty and "carrier" in a.columns:
        a = a.copy()
        a["_mem"] = pd.to_numeric(a.get("applicant_count"), errors="coerce").fillna(1).clip(lower=1)
        g = a.groupby("carrier")["_mem"].sum().sort_values(ascending=False)
        cc = g.reset_index()
        cc.columns = ["Carrier", "Members"]
        cc["Members"] = cc["Members"].astype(int)
        cc["Monthly"] = (cc["Members"] * PMPM).map(lambda v: f"${v:,.0f}")
        cc["Annual"] = (cc["Members"] * PMPM * 12).map(lambda v: f"${v:,.0f}")
        with st.container(border=True):
            st.markdown(ui.chart_head("Commission by Carrier", "Where your monthly commission comes from", "pie"),
                        unsafe_allow_html=True)
            ui.styled_table(cc, height=min(46 + 35 * (len(cc) + 1), 460), bare=True)


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
    position:relative; border-radius:20px; background:var(--panel-solid);
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
    width:56px; height:56px; border-radius:16px; background-color:var(--panel-solid);
    background-repeat:no-repeat; background-position:center; background-size:28px 28px;
    box-shadow:inset 0 0 0 1px rgba(139,92,246,.28); pointer-events:none;
  }}
  .st-key-goal_card_members::after {{ background-image:url("{_G_USERS}"); }}
  .st-key-goal_card_date::after    {{ background-image:url("{_G_CAL}"); }}
  .st-key-goal_card_members [data-testid="stWidgetLabel"] p,
  .st-key-goal_card_date [data-testid="stWidgetLabel"] p {{ font-size:.85rem !important; color:var(--text2) !important; }}
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
    font-size:1.9rem !important; font-weight:700 !important; color:var(--text) !important;
    background:transparent !important; padding-left:0 !important;
  }}
  .st-key-goal_card_members button[data-testid*="StepDown"],
  .st-key-goal_card_members button[data-testid*="StepUp"] {{
    background:transparent !important; border-radius:0 !important;
    border-left:1px solid rgba(138,172,214,.18) !important; width:54px !important; color:var(--text) !important;
  }}
  .st-key-goal_card_members button[data-testid*="StepDown"]:hover,
  .st-key-goal_card_members button[data-testid*="StepUp"]:hover {{ background:rgba(139,92,246,.12) !important; }}
  .goal-kpi-box {{
    background:var(--panel-solid); border:1px solid rgba(96,165,250,0.16); border-radius:16px;
    padding:22px 20px 18px; height:100%; transition:transform .15s ease, border-color .15s ease;
  }}
  .goal-kpi-box:hover {{ transform:translateY(-2px); border-color:rgba(96,165,250,0.5); }}
  .goal-kpi-value {{ font-size:2.6rem; font-weight:800; color:#60a5fa; line-height:1.1; }}
  .goal-kpi-value.green {{ color:#22c55e; }}
  .goal-kpi-value.gold  {{ color:#f59e0b; }}
  .goal-kpi-value.red   {{ color:#ef4444; }}
  .goal-kpi-label {{ font-size:.72rem; color:var(--text2); margin-top:6px; text-transform:uppercase; letter-spacing:.06em; }}
  .goal-kpi-sub {{ font-size:.82rem; color:var(--text2); margin-top:4px; }}
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
        f'<p style="color:var(--text2);font-size:0.95rem;margin-top:-6px;">'
        f'<b style="color:var(--text)">{GOAL:,} members</b> ≈ '
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
        f'<p style="color:var(--text2);font-size:0.95rem;">LTV: all-time churn '
        f'({churn_rate*100:.2f}%/mo → {implied_tenure:.0f}-mo tenure → '
        f'<b style="color:#2ecc71">${ltv_per:,}/member</b>)</p>', unsafe_allow_html=True)

    # Dual progress bars
    rev_pct = min(current_arr / goal_arr * 100, 100) if goal_arr else 0
    bar_c = "#2ecc71" if pct_done >= 75 else ("#f39c12" if pct_done >= 40 else "#4285F4")
    rev_c = "#2ecc71" if rev_pct >= 75 else ("#f39c12" if rev_pct >= 40 else "#4285F4")
    st.markdown(f"""
      <div style="margin-bottom:4px;display:flex;justify-content:space-between;font-size:0.85rem;color:var(--text2);">
        <span>Members &nbsp;<b style="color:var(--text)">{current:,}</b></span>
        <span><b style="color:var(--text)">{pct_done:.1f}%</b> of {GOAL:,}</span>
        <span><b>{gap:,} to go &nbsp;·&nbsp; {days_left:,} days left</b></span></div>
      <div class="progress-wrap" style="margin-bottom:14px;"><div class="progress-bar" style="width:{pct_done:.1f}%;background:{bar_c};"></div></div>
      <div style="margin-bottom:4px;display:flex;justify-content:space-between;font-size:0.85rem;color:var(--text2);">
        <span>Annual Revenue &nbsp;<b style="color:var(--text)">${current_arr:,.0f}</b></span>
        <span><b style="color:var(--text)">{rev_pct:.1f}%</b> of ${goal_arr:,.0f}</span>
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
        f'<div style="font-size:0.78rem;color:var(--text2);text-transform:uppercase;letter-spacing:0.08em;font-weight:600;">This week\'s target</div>'
        f'<div style="font-size:1.9rem;font-weight:800;color:{ui.GOLD};margin-top:4px;">+{needed_per_week:.0f} members</div>'
        f'<div style="font-size:0.9rem;color:var(--text2);margin-top:3px;">≈ {week_pol} policies &nbsp;·&nbsp; '
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
        ui.styled_table(pd.DataFrame(rows), height=340, bare=True)


_AEP_STATUSES = ["Not Started", "Contacted", "Renewed", "Lost"]


def page_aep(tenant: dict, roster) -> None:
    st.title("OEP Tracker")
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

    st.markdown("<style>.st-key-aepgrid [data-testid='stDataFrame'],"
                ".st-key-aepgrid [data-testid='stDataFrameResizable']{border:none !important;"
                "border-radius:12px;overflow:hidden;}</style>", unsafe_allow_html=True)
    with st.container(border=True, key="aepgrid"):
        st.markdown(ui.chart_head("Client Renewal Tracker",
                                  "Set each client's status and add notes, then hit Save", "users"),
                    unsafe_allow_html=True)
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


_SETTINGS_CSS = """<style>
  .set-h{display:flex;align-items:center;gap:14px;margin:2px 0 6px;}
  .set-badge{width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;
     background:rgba(96,165,250,.14);border:1px solid rgba(96,165,250,.30);flex:none;}
  .set-badge svg{width:20px;height:20px;stroke:#93c5fd;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;}
  .set-h .t{font-size:1.15rem;font-weight:800;color:var(--text);line-height:1.15;}
  .set-h .s{font-size:.85rem;color:var(--text2);}
  .set-sub{font-size:.8rem;color:var(--text3);margin-top:-6px;}
  .set-chip{background:var(--input-bg);border:1px solid rgba(96,165,250,.25);border-radius:14px;
     padding:8px 16px;display:flex;align-items:center;gap:12px;}
  .set-chip svg{width:22px;height:22px;stroke:#93c5fd;fill:none;stroke-width:2;}
  .set-chip .n{font-size:1.45rem;font-weight:800;color:var(--text);line-height:1;}
  .set-chip .l{font-size:.7rem;color:var(--text2);text-transform:uppercase;letter-spacing:.05em;}
  /* state list buttons → cards with a chevron */
  .st-key-statelist [data-testid="stButton"] button{width:100%;justify-content:flex-start;text-align:left;
     border-radius:12px;padding:12px 34px 12px 14px;border:1px solid rgba(96,165,250,.18);
     background:var(--input-bg);font-weight:600;position:relative;white-space:pre-line;line-height:1.35;}
  .st-key-statelist [data-testid="stButton"] button::after{content:"›";position:absolute;right:14px;top:50%;
     transform:translateY(-50%);color:#64748b;font-size:1.25rem;}
  /* carrier checkbox grid → selectable cards */
  .st-key-carriergrid [data-testid="stCheckbox"]{border:1px solid rgba(96,165,250,.18);border-radius:10px;
     padding:11px 13px;background:var(--input-bg);transition:border-color .12s,background .12s;}
  .st-key-carriergrid [data-testid="stCheckbox"]:hover{border-color:rgba(96,165,250,.45);}
  .st-key-carriergrid [data-testid="stCheckbox"]:has(input:checked){border-color:#3b82f6;background:rgba(59,130,246,.14);}
  .st-key-carriergrid [data-testid="stCheckbox"] label{width:100%;}
  .set-footer{background:rgba(34,197,94,.10);border:1px solid rgba(34,197,94,.30);border-radius:10px;
     padding:10px 14px;display:flex;justify-content:space-between;align-items:center;margin-top:10px;
     font-size:.85rem;color:var(--text);}
  /* Save Changes — blue→purple gradient like the sign-in button */
  .st-key-savebar [data-testid="stButton"] button{
     background:linear-gradient(90deg,#3b82f6 0%,#7c3aed 100%) !important;border:none !important;
     color:#fff !important;font-weight:700 !important;border-radius:12px !important;padding:12px 20px !important;
     box-shadow:0 6px 18px rgba(59,130,246,.28) !important;}
  .st-key-savebar [data-testid="stButton"] button:hover{filter:brightness(1.08);}
  .st-key-savebar [data-testid="stButton"] button p{color:#fff !important;}
</style>"""


def _sec_head(icon: str, title: str, sub: str) -> str:
    return (f'<div class="set-h"><span class="set-badge">{ui.ICONS.get(icon, "")}</span>'
            f'<span><div class="t">{title}</div><div class="s">{sub}</div></span></div>')


def _chip(icon: str, n, label: str) -> str:
    return (f'<div class="set-chip"><span>{ui.ICONS.get(icon, "")}</span>'
            f'<span><div class="n">{n}</div><div class="l">{label}</div></span></div>')


def page_settings(tenant: dict, roster) -> None:
    st.title("Settings")
    st.caption("Manage your profile, licensed states, and carrier appointments.")
    st.markdown(_SETTINGS_CSS, unsafe_allow_html=True)
    agent_id = tenant["agent_id"]
    cfg = settings.get(agent_id)
    appts = cfg.get("appointments", {}) or {}

    # ── Profile Information ─────────────────────────────────────────────────────
    with st.container(border=True):
        st.markdown(_sec_head("shield", "Profile Information",
                              "This information is used to manage your book of business."),
                    unsafe_allow_html=True)
        p1, p2 = st.columns(2)
        with p1:
            st.text_input("Username", value=tenant.get("username", ""), key="set_username")
            st.markdown('<div class="set-sub">Used for your account and private workspace URL.</div>',
                        unsafe_allow_html=True)
        with p2:
            st.text_input("National Producer Number (NPN)", value=tenant.get("npn", ""), key="set_npn")
            st.markdown('<div class="set-sub">Your NPN keeps your book scoped to you.</div>',
                        unsafe_allow_html=True)
        st.markdown('<div class="set-sub" style="margin-top:16px;font-weight:700;color:var(--text);'
                    'text-transform:uppercase;letter-spacing:.05em;">Change password</div>',
                    unsafe_allow_html=True)
        pw1, pw2, pw3 = st.columns(3)
        _cur = pw1.text_input("Current password", type="password", key="set_pw_cur")
        _new = pw2.text_input("New password", type="password", key="set_pw_new")
        _conf = pw3.text_input("Confirm new password", type="password", key="set_pw_conf")
        if st.button("Update password", key="set_pw_btn"):
            if not _cur or not _new:
                st.error("Enter your current password and a new password.")
            elif _new != _conf:
                st.error("The new passwords don't match.")
            else:
                try:
                    tenants.change_password(st.session_state.tenant["username"], _cur, _new)
                    st.success("Password updated — use it next time you sign in.")
                except ValueError as e:
                    st.error(str(e))

    # ── Licensed States & Carrier Appointments ──────────────────────────────────
    with st.container(border=True):
        h1, h2 = st.columns([3, 2])
        with h1:
            st.markdown(_sec_head("pin", "Licensed States & Carrier Appointments",
                                  "Select the states you are licensed in and manage your carrier appointments."),
                        unsafe_allow_html=True)
        with h2:
            cc1, cc2 = st.columns(2)
            cc1.markdown(_chip("pin", len(appts), "Active States"), unsafe_allow_html=True)
            cc2.markdown(_chip("shield", sum(len(v) for v in appts.values()), "Carrier Appointments"),
                         unsafe_allow_html=True)

        edit = st.session_state.get("appt_edit")
        if edit not in appts:
            edit = (sorted(appts, key=lambda s: _STATE_NAMES.get(s, s))[0] if appts else None)

        left, right = st.columns([2, 3], gap="large")

        # ---- Left: licensed states list ----
        with left, st.container(key="statelist"):
            st.markdown("**Your Licensed States**")
            st.markdown('<div class="set-sub" style="margin:0 0 8px">Click a state to manage its carriers</div>',
                        unsafe_allow_html=True)
            remaining = [s for s in _US_STATES if s not in appts]
            with st.popover("➕  Add State", use_container_width=True):
                add_s = st.selectbox("State", remaining, format_func=lambda s: _STATE_NAMES.get(s, s),
                                     key="appt_add") if remaining else None
                if add_s and st.button("Add", type="primary", use_container_width=True, key="appt_add_btn"):
                    settings.save(agent_id, {**cfg, "appointments": {**appts, add_s: []}})
                    st.session_state["appt_edit"] = add_s
                    st.rerun()
            if not appts:
                st.caption("No states yet — add the states you write business in.")
            for s in sorted(appts, key=lambda x: _STATE_NAMES.get(x, x)):
                n = len(appts.get(s) or [])
                label = f"{_STATE_NAMES.get(s, s)}\n{n} carrier{'s' if n != 1 else ''}"
                if st.button(label, key=f"pick_{s}", use_container_width=True,
                             type=("primary" if s == edit else "secondary")):
                    st.session_state["appt_edit"] = s
                    st.rerun()

        # ---- Right: carrier picker for the selected state ----
        with right:
            if not edit:
                st.info("Add a state on the left, then pick the carriers you're appointed with there.")
            else:
                name = _STATE_NAMES.get(edit, edit)
                hr1, hr2 = st.columns([3, 1])
                hr1.markdown(f"**📍 {name}**  \n<span class='set-sub'>Select all the carriers you are "
                             f"appointed with in this state.</span>", unsafe_allow_html=True)
                if hr2.button("🗑  Remove State", key="rm_state", use_container_width=True):
                    settings.save(agent_id, {**cfg, "appointments": {k: v for k, v in appts.items() if k != edit}})
                    st.session_state.pop("appt_edit", None)
                    st.rerun()

                q = st.text_input("Search carriers", placeholder="🔎  Search carriers…",
                                  key=f"csearch_{edit}", label_visibility="collapsed").lower().strip()
                opts = carrier_names.brand_options(roster, extra=appts.get(edit))
                shown = [c for c in opts if q in c.lower()] if q else opts
                selected = set(appts.get(edit, []))

                def _toggle(state, brand, key):
                    cfg2 = settings.get(agent_id)
                    cur = set(cfg2.get("appointments", {}).get(state, []))
                    cur.add(brand) if st.session_state.get(key) else cur.discard(brand)
                    settings.save(agent_id, {**cfg2, "appointments": {
                        **cfg2.get("appointments", {}), state: sorted(cur)}})

                with st.container(key="carriergrid"):
                    grid = st.columns(3)
                    for i, brand in enumerate(shown):
                        key = f"cb_{edit}_{brand}"
                        st.session_state[key] = brand in selected  # sync from saved before widget
                        grid[i % 3].checkbox(brand, key=key, on_change=_toggle, args=(edit, brand, key))
                    if not shown:
                        st.caption("No carriers match your search.")

                names = ", ".join(sorted(selected)) if selected else "none yet"
                st.markdown(
                    f'<div class="set-footer"><span>✓ <b>{len(selected)}</b> carrier'
                    f'{"" if len(selected) == 1 else "s"} selected</span>'
                    f'<span style="color:var(--text2)">{names}</span></div>', unsafe_allow_html=True)

    # ── Save bar (profile) ──────────────────────────────────────────────────────
    sb1, sb2 = st.columns([3, 1])
    sb1.markdown('<div style="display:flex;align-items:center;gap:8px;color:#4ade80;font-weight:600;">'
                 '✓ All changes saved <span style="color:var(--text3);font-weight:400;">· '
                 'Carrier changes save instantly.</span></div>', unsafe_allow_html=True)
    with sb2, st.container(key="savebar"):
        _save_clicked = st.button("💾  Save Changes", type="primary", use_container_width=True)
    if _save_clicked:
        errs = []
        new_npn = st.session_state.get("set_npn", "").strip()
        if new_npn != tenant.get("npn", ""):
            tenants.update_npn(st.session_state.tenant["username"], new_npn)
            st.session_state.tenant["npn"] = new_npn
        new_un = st.session_state.get("set_username", "").strip()
        if new_un and new_un.lower() != tenant.get("username", "").lower():
            try:
                st.session_state.tenant.update(tenants.rename(st.session_state.tenant["username"], new_un))
            except ValueError as e:
                errs.append(str(e))
        if errs:
            st.error(" · ".join(errs))
        else:
            st.success("Saved.")
            st.rerun()


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
            ui.styled_table(hht, bare=True)
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
            d2["effective_date"] = pd.to_datetime(d2["effective_date"], errors="coerce").dt.strftime("%b %d, %Y")
            d2.columns = [c.replace("_", " ").title() for c in d2.columns]
            ui.styled_table(d2, height=360)
    st.markdown("<br>", unsafe_allow_html=True)

    # ── Client roster table ─────────────────────────────────────────────────────
    display_cols = ["first_name", "last_name", "carrier", "state", "status_display",
                    "effective_date", "term_date", "months_on_book", "applicant_count", "net_premium"]
    disp = df[[c for c in display_cols if c in df.columns]].rename(columns={"status_display": "status"}).copy()
    for _dc in ("effective_date", "term_date"):
        if _dc in disp.columns:
            disp[_dc] = pd.to_datetime(disp[_dc], errors="coerce").dt.strftime("%b %-d, %Y")
    if "net_premium" in disp.columns:
        disp["net_premium"] = pd.to_numeric(disp["net_premium"], errors="coerce").map(
            lambda v: f"${v:,.2f}" if pd.notna(v) else "—")
    disp = disp.rename(columns={
        "first_name": "First Name", "last_name": "Last Name", "carrier": "Carrier",
        "state": "State", "status": "Status", "effective_date": "Effective Date",
        "term_date": "Term Date", "months_on_book": "Mo. on Book",
        "applicant_count": "Members", "net_premium": "Net Premium"})
    with st.container(border=True):
        st.markdown(ui.chart_head("Client Roster", f"{len(df):,} policies in current view", "book"),
                    unsafe_allow_html=True)
        ui.styled_table(disp, height=600, bare=True)


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
    ui.styled_table(show, height=min(120 + len(show) * 34, 620))


def page_aor(tenant: dict, roster) -> None:
    st.title("AOR at Risk")
    st.caption("Clients another agent filed an Agent-of-Record change on — call them, most don't "
               "know they were switched. Newest steals first — the freshest are the most winnable.")
    st.markdown('<div class="section-divider"></div>', unsafe_allow_html=True)
    if roster is None:
        _need_book(); return

    taken = views.aor_taken(roster, tenant.get("npn", ""), tenant.get("name", "")).copy()
    members = pd.to_numeric(taken.get("applicant_count"), errors="coerce").fillna(1).clip(lower=1)

    _cards([
        ui.stat_card("Taken by Another Agent", f"{len(taken):,}", "minus", ui.RED),
        ui.stat_card("Members at Risk", f"{int(members.sum()):,}", "users", ui.ELEC),
    ])
    st.markdown("<br>", unsafe_allow_html=True)

    with st.container(border=True):
        if taken.empty:
            st.success("None taken — you hold every client's AOR. 🛡️")
        else:
            t = taken.copy()
            t["_mem"] = members.values
            # The HealthSherpa export doesn't say WHEN an AOR change happened, so we
            # can't show a true "days gone". Instead we count from when the agent
            # first flagged the steal (first upload = "New"). That's honest and makes
            # the freshest-at-top order meaningful — stale, un-called steals rise.
            t["_nk"] = ["".join(ch for ch in f"{f}{l}".lower() if ch.isalnum())
                        for f, l in zip(t.get("first_name", ""), t.get("last_name", ""))]
            _days = aor_track.days_gone(tenant["agent_id"], list(t["_nk"]))
            t["_days"] = t["_nk"].map(_days).fillna(0).astype(int)
            t = t.sort_values("_days", ascending=True)
            if bool((t["_days"] == 0).all()):  # no aging yet — first upload / all fresh
                st.info("First upload, so every steal below is marked **New** — the export doesn't "
                        "include the date each AOR change happened. Keep uploading and we'll show how "
                        "long each has been flagged, so stale un-called steals float to the top.",
                        icon="🆕")
            show = pd.DataFrame({
                "Client": (t["first_name"].fillna("") + " " + t["last_name"].fillna("")).str.strip().str.title(),
                "Taken By": t.get("taken_by", ""),
                "Flagged": t["_days"].map(lambda d: "New" if d == 0 else f"{d}d ago"),
                "Carrier": t.get("carrier", ""),
                "State": t.get("state", ""),
                "Members": t["_mem"].astype(int),
                "Phone": t.get("phone", ""),
            })
            ui.styled_table(show, height=min(46 + 35 * max(len(show), 1), 560), bare=True)
            st.caption("**Flagged** = when you first saw the steal in your book — the export has no "
                       "AOR-change date. Freshest at the top (most winnable); it fills in as you keep "
                       "uploading.")


def page_verifications(tenant: dict, roster) -> None:
    st.title("Documents Due")
    st.caption("Verification documents your clients still owe HealthSherpa. **DMI** = income/coverage match; "
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
    ui.styled_table(fd, height=min(120 + len(fd) * 34, 620))
    st.caption("**Open** items are still savable — reach out before they expire. **Expired** items have "
               "lost the subsidy and move to Cancelled → Re-Engage.")


def page_pastdue(tenant: dict, roster) -> None:
    st.title("Past Due Premium")
    st.caption("Behind-on-payment clients from your Ambetter & Oscar carrier books.")
    pd_df = views.past_due(tenant["agent_id"])
    if pd_df is None:
        st.info("Upload your Ambetter and/or Oscar carrier books on the **Upload** page to "
                "see who's behind on payment.", icon="📥")
        return
    _stat(ui.stat_card("Past due", f"{len(pd_df):,}", "clock", ui.RED))
    ui.styled_table(pd_df, empty="Nothing past due.")


# ── Shell ───────────────────────────────────────────────────────────────────
# Nav order matters — the section labels + bottom divider are painted by CSS
# (nth-of-type), so keep group starts at positions 1 / 4 / 7 / 9 and the
# Upload+Settings pair last (13, 14).
_NAV = ["Dashboard", "Book Updates",                                    # OVERVIEW
        "AOR at Risk", "Re-Engage", "Past Due Premium", "Documents Due", "OEP Tracker",  # WORK LISTS
        "Book", "Client Lookup",                                        # MY BOOK
        "Daily Tracker", "Goals", "Monthly Trends", "Commissions",      # PERFORMANCE & PAY
        "Upload", "Settings"]                                           # ADMIN

_PAGES = {
    "Dashboard": page_dashboard, "Book Updates": page_updates, "Daily Tracker": page_daily,
    "Goals": page_goals, "Client Lookup": page_client_lookup, "Book": page_book,
    "Monthly Trends": page_trends, "Commissions": page_commissions, "Past Due Premium": page_pastdue,
    "AOR at Risk": page_aor, "Documents Due": page_verifications,
    "Re-Engage": page_losses, "OEP Tracker": page_aep, "Settings": page_settings,
}
_NO_ROSTER = {"Upload", "Settings", "Book Updates"}


# Per-nav-item icons (in _NAV order). Rendered as CSS masks tinted by the theme
# so they follow --sidebar-nav / --sidebar-sel (active) automatically.
_NAV_ICON_PATHS = {
    "grid": ("<rect x='3' y='3' width='7' height='7' rx='1'/><rect x='14' y='3' width='7' height='7' rx='1'/>"
             "<rect x='14' y='14' width='7' height='7' rx='1'/><rect x='3' y='14' width='7' height='7' rx='1'/>"),
    "upload": ("<path d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'/>"
               "<polyline points='17 8 12 3 7 8'/><line x1='12' y1='3' x2='12' y2='15'/>"),
}
# One icon per _NAV item, IN _NAV ORDER (positional — keep in sync with _NAV).
_NAV_ICONS = ["grid", "file",                                  # Dashboard, Book Updates
              "shield", "refresh", "clock", "bell", "calendar",  # AOR, Re-Engage, Past Due, Verifications, AEP
              "book", "users",                                 # Book, Client Lookup
              "calendar", "target", "trend", "dollar",         # Daily Tracker, Goals, Monthly Trends, Commissions
              "upload", "gear"]                                # Upload, Settings


def _nav_icon_uri(key: str) -> str:
    import urllib.parse
    inner = _NAV_ICON_PATHS.get(key)
    if inner is None:
        s = ui.ICONS.get(key, "")
        inner = s.split(">", 1)[1].rsplit("</svg>", 1)[0] if s else ""
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' "
           "stroke-width='2' stroke-linecap='round' stroke-linejoin='round'>" + inner + "</svg>")
    return "data:image/svg+xml," + urllib.parse.quote(svg)


def _nav_css() -> None:
    sb = 'section[data-testid="stSidebar"] div[role="radiogroup"] > label'
    css = [
        f'{sb}::before{{content:"";width:20px;height:20px;flex:0 0 auto;display:inline-block;'
        f'background:var(--sidebar-nav);opacity:.9;-webkit-mask-repeat:no-repeat;mask-repeat:no-repeat;'
        f'-webkit-mask-position:center;mask-position:center;-webkit-mask-size:contain;mask-size:contain;}}',
        f'{sb}:has(input:checked)::before{{background:var(--sidebar-sel);opacity:1;}}',
    ]
    for i, key in enumerate(_NAV_ICONS, start=1):
        u = _nav_icon_uri(key)
        css.append(f'{sb}:nth-of-type({i})::before{{-webkit-mask-image:url("{u}");mask-image:url("{u}");}}')
    for i, title in [(1, "OVERVIEW"), (3, "WORK LISTS"), (8, "MY BOOK"), (10, "PERFORMANCE & PAY")]:
        css.append(f'{sb}:nth-of-type({i}){{margin-top:{12 if i == 1 else 22}px;position:relative;overflow:visible;}}')
        css.append(f'{sb}:nth-of-type({i})::after{{content:"{title}";position:absolute;top:-15px;left:10px;'
                   f'font-size:.64rem;letter-spacing:.13em;color:var(--nav-label);font-weight:700;}}')
    css.append(f'{sb}:nth-of-type(14){{margin-top:26px;border-top:1px solid rgba(96,165,250,0.18);padding-top:12px;}}')
    st.markdown(f"<style>{''.join(css)}</style>", unsafe_allow_html=True)


def _footer_css() -> None:
    """Settings footer: a header + three cards (theme toggle, Refresh, Log out).

    Icons are CSS masks tinted with theme vars so they track light/dark. The
    interactive widgets are real Streamlit widgets wrapped in keyed containers
    (.st-key-sb_theme / sb_refresh / sb_logout) that we repaint as cards.
    """
    ss = 'section[data-testid="stSidebar"]'
    sun = _nav_icon_uri("sun")
    refresh, logout = _nav_icon_uri("refresh"), _nav_icon_uri("logout")
    st.markdown(f"""<style>
    /* thin divider separating the nav from the settings cards */
    {ss} .sb-set-sep{{border-top:1px solid var(--divider);margin:12px 2px 14px;}}
    /* shared card frame */
    {ss} .st-key-sb_theme,
    {ss} .st-key-sb_refresh button,
    {ss} .st-key-sb_logout button{{
      background:var(--panel-solid) !important;border:1.5px solid var(--border) !important;
      border-radius:14px !important;box-shadow:var(--card-shadow) !important;}}
    /* theme toggle: sun icon + label on the left, switch on the right */
    {ss} .st-key-sb_theme{{padding:11px 14px !important;margin-bottom:11px;}}
    {ss} .st-key-sb_theme label{{flex-direction:row-reverse !important;
      justify-content:space-between !important;width:100% !important;align-items:center !important;gap:10px;}}
    {ss} .st-key-sb_theme label p{{color:var(--text) !important;font-weight:600 !important;
      font-size:.95rem !important;display:flex;align-items:center;gap:10px;}}
    {ss} .st-key-sb_theme label p::before{{content:"";width:18px;height:18px;flex:0 0 auto;
      background:var(--text2);-webkit-mask:url("{sun}") center/contain no-repeat;
      mask:url("{sun}") center/contain no-repeat;}}
    /* Refresh + Log out buttons as cards */
    {ss} .st-key-sb_refresh button,
    {ss} .st-key-sb_logout button{{padding:12px 14px !important;font-weight:700 !important;
      justify-content:center !important;gap:9px;min-height:0 !important;}}
    {ss} .st-key-sb_refresh{{margin-bottom:11px;}}
    {ss} .st-key-sb_refresh button::before,
    {ss} .st-key-sb_logout button::before{{content:"";width:18px;height:18px;flex:0 0 auto;}}
    {ss} .st-key-sb_refresh button{{color:var(--accent-blue) !important;border-color:var(--accent-blue) !important;}}
    {ss} .st-key-sb_refresh button p{{color:var(--accent-blue) !important;font-weight:700 !important;}}
    {ss} .st-key-sb_refresh button::before{{background:var(--accent-blue);
      -webkit-mask:url("{refresh}") center/contain no-repeat;mask:url("{refresh}") center/contain no-repeat;}}
    {ss} .st-key-sb_logout button p{{color:var(--text) !important;font-weight:700 !important;}}
    {ss} .st-key-sb_logout button::before{{background:var(--text2);
      -webkit-mask:url("{logout}") center/contain no-repeat;mask:url("{logout}") center/contain no-repeat;}}
    </style>""", unsafe_allow_html=True)


def workspace() -> None:
    tenant = st.session_state.tenant
    agent_id = tenant["agent_id"]
    with st.sidebar:
        st.markdown(
            f'<div style="padding:2px 2px 0;" aria-label="{APP_NAME}">'
            f'{ui.brand_lockup(icon_px=44, text_rem=1.74, gap=12)}</div>',
            unsafe_allow_html=True)
        st.caption(tenant.get("name") or tenant.get("username"))
        _nav_css()
        # Apply a pending redirect BEFORE the radio is drawn — Streamlit won't let
        # us change a widget's state after it's instantiated.
        if "_pending_nav" in st.session_state:
            st.session_state["nav"] = st.session_state.pop("_pending_nav")
        page = st.radio("Go to", _NAV, key="nav", label_visibility="collapsed")
        _footer_css()
        st.markdown('<div class="sb-set-sep"></div>', unsafe_allow_html=True)
        with st.container(key="sb_theme"):
            _light = st.toggle("Light mode", value=st.session_state.get("agent_theme", "light") == "light",
                               key="theme_toggle")
        _want = "light" if _light else "dark"
        if _want != st.session_state.get("agent_theme", "light"):
            st.session_state["agent_theme"] = _want
            st.rerun()
        with st.container(key="sb_refresh"):
            if st.button("Refresh data", use_container_width=True,
                         help="Re-pull your latest data and redraw — without signing out."):
                from core import store
                if store.using_db():
                    store.hydrate(agent_id, paths.tenant_root(agent_id))
                st.cache_data.clear()
                st.toast("Data refreshed.")
                st.rerun()
        with st.container(key="sb_logout"):
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
