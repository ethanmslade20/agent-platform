"""Agent Platform — multi-tenant app.

Phase 1: sign-in gate + per-tenant isolation.
Phase 2: in-app upload (HealthSherpa builds the book; carriers stored for reconciliation)
         and a first look at the agent's book, all scoped to their own workspace.
"""
import pandas as pd
import streamlit as st

from core import ingest_service, paths, tenants, views

# The product name your agents see. Placeholder — change it here anytime.
APP_NAME = "Agent Book"

_ACTIVE = ("Effectuated", "PendingEffectuation", "PendingFollowups")

st.set_page_config(page_title=APP_NAME, page_icon="📘", layout="wide")

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


def page_book(tenant: dict, roster) -> None:
    st.title("My Book")
    if roster is None:
        _need_book(); return
    a = views.active(roster)
    members = pd.to_numeric(a.get("applicant_count"), errors="coerce").fillna(1).clip(lower=1).sum()
    c1, c2, c3 = st.columns(3)
    c1.metric("Active clients", f"{len(a):,}")
    c2.metric("Members", f"{int(members):,}")
    c3.metric("Total on file", f"{len(roster):,}")
    st.divider()
    _table(a, ["first_name", "last_name", "carrier", "state", "status", "effective_date"], "")


def page_losses(tenant: dict, roster) -> None:
    st.title("Losses  ·  Re-Engage")
    st.caption("Clients who cancelled or terminated — your win-back list.")
    if roster is None:
        _need_book(); return
    lost = views.losses(roster)
    st.metric("Cancelled / terminated", f"{len(lost):,}")
    st.divider()
    _table(lost, ["first_name", "last_name", "carrier", "state", "status", "term_date"],
           "No losses — everyone's still active. 🎉")


def page_aor(tenant: dict, roster) -> None:
    st.title("AOR Defense")
    st.caption("Clients another agent is now the agent of record on — your recovery list.")
    if roster is None:
        _need_book(); return
    taken = views.aor_taken(roster, tenant.get("npn", ""), tenant.get("name", ""))
    st.metric("Taken by another agent", f"{len(taken):,}")
    st.divider()
    _table(taken, ["first_name", "last_name", "state", "taken_by", "carrier"],
           "None taken — you hold every client's AOR. 🛡️")


def page_verifications(tenant: dict, roster) -> None:
    st.title("Verifications")
    st.caption("Active clients with an expired document check — coverage at risk unless docs go in.")
    if roster is None:
        _need_book(); return
    v = views.verifications(roster)
    st.metric("Docs expired", f"{len(v):,}")
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
    st.metric("Past due", f"{len(pd_df):,}")
    st.divider()
    st.dataframe(pd_df, use_container_width=True, hide_index=True)


# ── Shell ───────────────────────────────────────────────────────────────────
def workspace() -> None:
    tenant = st.session_state.tenant
    agent_id = tenant["agent_id"]
    with st.sidebar:
        st.markdown(f"### {tenant['name'] or tenant['username']}")
        if tenant.get("npn"):
            st.caption(f"NPN {tenant['npn']}")
        st.divider()
        page = st.radio(
            "Go to",
            ["Upload", "My Book", "Past Due", "AOR Defense", "Verifications", "Losses"],
            key="nav", label_visibility="collapsed",
        )
        st.divider()
        st.caption(f"Workspace · tenants/{agent_id}/")
        if st.button("Log out", use_container_width=True):
            st.session_state.tenant = None
            st.rerun()

    if page == "Upload":
        page_upload(tenant)
        return

    # Every analytics page reads the same roster — build it once.
    roster = ingest_service.build_book(agent_id)
    {
        "My Book": page_book,
        "Past Due": page_pastdue,
        "AOR Defense": page_aor,
        "Verifications": page_verifications,
        "Losses": page_losses,
    }[page](tenant, roster)


if st.session_state.tenant:
    workspace()
else:
    login_screen()
