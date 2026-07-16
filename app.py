"""Agent Platform — multi-tenant shell (Phase 1).

Sign-in gate + tenant-scoped workspace. Once an agent logs in, everything is
scoped to their own `tenants/<agent_id>/` folder — the isolation boundary that
lets many agents share one app without ever seeing each other's book.

Phase 2 adds the in-app upload that feeds `tracker/`; Phase 3 ports the real pages.
"""
import streamlit as st

from core import paths, tenants

# The product name your agents see. Placeholder — change it here anytime.
APP_NAME = "Agent Book"

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
            paths.ensure_dirs(tenant["agent_id"])  # create their private workspace
            st.session_state.tenant = tenant
            st.rerun()
        else:
            st.error("Wrong username or password.")
    st.markdown("</div>", unsafe_allow_html=True)


def workspace() -> None:
    tenant = st.session_state.tenant
    with st.sidebar:
        st.markdown(f"### {tenant['name'] or tenant['username']}")
        if tenant.get("npn"):
            st.caption(f"NPN {tenant['npn']}")
        st.divider()
        if st.button("Log out", use_container_width=True):
            st.session_state.tenant = None
            st.rerun()

    st.title(f"{tenant['name'] or 'Your'} Book")
    st.markdown(
        f'<p class="ws">Private workspace · <code>tenants/{tenant["agent_id"]}/</code></p>',
        unsafe_allow_html=True,
    )

    n = paths.snapshot_count(tenant["agent_id"])
    if n == 0:
        st.info(
            "No data yet. Next step: drag in your HealthSherpa export and your book "
            "builds itself here — that's what we wire up in Phase 2.",
            icon="📥",
        )
    else:
        st.success(f"{n} snapshot(s) loaded in your workspace.", icon="✅")


if st.session_state.tenant:
    workspace()
else:
    login_screen()
