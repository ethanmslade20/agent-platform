"""Design system ported from Ethan's commission-tracker so the product matches
his look — midnight fintech theme, metric cards, section headers, sparklines."""
import html as _html
import re as _re

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

NAVY  = "#0f1c34"
LNAV  = "#1b2c4d"
BLUE  = "#3b82f6"
ELEC  = "#60a5fa"
PURPLE= "#7c3aed"
CYAN  = "#22d3ee"
GREEN = "#22c55e"
RED   = "#ef4444"
GOLD  = "#f59e0b"
# Theme is driven by CSS variables (see _PALETTES / theme_root_css) so a single
# toggle flips the whole app. T maps the old token names onto those variables so
# every existing rule keeps working.
T = dict(
    page_bg      = "var(--bg)",
    sidebar_bg   = "var(--sidebar2)",
    kpi_bg       = "var(--panel)",
    kpi_border   = "var(--border2)",
    kpi_val      = "var(--text)",
    kpi_lbl      = "var(--text2)",
    kpi_sub      = "var(--text3)",
    divider      = "var(--divider)",
    progress_bg  = "var(--progress-bg)",
    goal_val     = "var(--accent-blue)",
    goal_green   = "#22c55e",
    goal_gold    = "#f59e0b",
    goal_red     = "#ef4444",
    text_primary = "var(--text)",
)

# Dark + light palettes. Accent hues (green/red/gold/purple) are shared; only the
# neutrals (backgrounds, panels, text, borders) flip.
_PALETTES = {
    "dark": {
        "--bg": "#070f22", "--tint1": "rgba(124,58,237,.13)", "--tint2": "rgba(59,130,246,.13)",
        "--panel-grad": "linear-gradient(160deg,rgba(20,34,62,.9),rgba(11,21,42,.85))",
        "--panel": "rgba(15,28,52,.82)", "--panel-solid": "#0c1424",
        "--sidebar1": "#0b1830", "--sidebar2": "#081426", "--sidebar-text": "#e8edf5",
        "--sidebar-nav": "#cbd5e1", "--sidebar-sel": "#dbe7ff",
        "--sidebar-sel-bg": "rgba(30,48,92,.45)", "--sidebar-ring": "rgba(96,165,250,.75)",
        "--sidebar-tile": "#131f3a", "--nav-label": "#6b84ad", "--sec-head": "#94a3b8",
        "--nav-active-shadow": "inset 0 0 0 1.5px rgba(96,165,250,.75),0 0 0 1px rgba(139,92,246,.45),0 0 18px rgba(96,165,250,.22)",
        "--title-grad": "linear-gradient(96deg,#ffffff 0%,#d6e4ff 45%,#8fb3ec 100%)",
        "--text": "#f8fafc", "--text2": "#94a3b8", "--text3": "#6b84ad",
        "--border": "rgba(96,165,250,.22)", "--border2": "rgba(96,165,250,.25)",
        "--divider": "rgba(96,165,250,.18)", "--hover": "rgba(96,165,250,.07)",
        "--input-bg": "rgba(15,23,42,.6)", "--progress-bg": "#0a1326", "--accent-blue": "#60a5fa",
        "--hl-grad": "linear-gradient(160deg,rgba(38,29,74,.92),rgba(16,20,52,.9))",
        "--hl-green-grad": "linear-gradient(160deg,rgba(20,60,40,.92),rgba(14,30,28,.9))",
        "--dt-bg": "#0b1322", "--dt-head": "#0e1830", "--dt-text": "#dbe4f0",
        "--dt-head-text": "#8aa2c4", "--dt-row": "rgba(96,165,250,.07)",
        "--dt-hover": "rgba(96,165,250,.06)", "--dt-muted": "#7b91b3",
        "--pill-bg": "rgba(59,130,246,.16)", "--pill-text": "#93c5fd", "--pill-bd": "rgba(59,130,246,.30)",
        "--pos": "#4ade80", "--neg": "#f87171",
        # icon boxes — pos/neg equal info in dark so dark stays unchanged
        "--icon-info-bg": "linear-gradient(145deg,rgba(59,130,246,.18),rgba(124,58,237,.13))",
        "--icon-info": "#60a5fa",
        "--icon-pos-bg": "linear-gradient(145deg,rgba(59,130,246,.18),rgba(124,58,237,.13))",
        "--icon-pos": "#60a5fa",
        "--icon-neg-bg": "linear-gradient(145deg,rgba(59,130,246,.18),rgba(124,58,237,.13))",
        "--icon-neg": "#60a5fa",
        "--card-shadow": "inset 0 1px 0 rgba(255,255,255,.03),0 10px 30px rgba(0,0,0,.25)",
        "--card-shadow-hover": "0 0 0 1px rgba(96,165,250,.25),0 16px 42px rgba(8,20,46,.6),0 0 32px rgba(59,130,246,.16)",
    },
    "light": {
        "--bg": "#f8fafc", "--tint1": "rgba(22,119,255,.04)", "--tint2": "rgba(22,119,255,.05)",
        "--panel-grad": "#ffffff",
        "--panel": "#ffffff", "--panel-solid": "#ffffff",
        "--sidebar1": "#ffffff", "--sidebar2": "#ffffff", "--sidebar-text": "#0f172a",
        "--sidebar-nav": "#0f172a", "--sidebar-sel": "#1677ff",
        "--sidebar-sel-bg": "linear-gradient(90deg,#f5f9ff 0%,#edf5ff 100%)",
        "--sidebar-ring": "#74a9ff", "--sidebar-tile": "#eef4fb",
        "--nav-label": "#1677ff", "--sec-head": "#1268d6",
        "--nav-active-shadow": "inset 0 0 0 1.5px #74a9ff,0 3px 12px rgba(22,119,255,.10)",
        "--title-grad": "linear-gradient(96deg,#071224 0%,#0b2c66 55%,#1268d6 100%)",
        "--text": "#0f172a", "--text2": "#62728d", "--text3": "#7c8ba1",
        "--border": "#dce4ee", "--border2": "#dce4ee",
        "--divider": "#e5ebf2", "--hover": "#f5f8fc",
        "--input-bg": "#ffffff", "--progress-bg": "#e8eef6", "--accent-blue": "#1677ff",
        "--hl-grad": "linear-gradient(160deg,#eaf3ff,#f5f9ff)",
        "--hl-green-grad": "linear-gradient(160deg,#e7f8ed,#f2fcf5)",
        "--dt-bg": "#ffffff", "--dt-head": "#f8fafc", "--dt-text": "#0f172a",
        "--dt-head-text": "#62728d", "--dt-row": "#e8edf3",
        "--dt-hover": "#f5f8fc", "--dt-muted": "#7c8ba1",
        "--pill-bg": "#eaf3ff", "--pill-text": "#1268d6", "--pill-bd": "#74a9ff",
        "--pos": "#16b84e", "--neg": "#ff323c",
        "--icon-info-bg": "#eaf3ff", "--icon-info": "#1677ff",
        "--icon-pos-bg": "#e7f8ed", "--icon-pos": "#16b84e",
        "--icon-neg-bg": "#ffebed", "--icon-neg": "#ff323c",
        "--card-shadow": "0 1px 2px rgba(15,23,42,.03),0 8px 22px rgba(15,23,42,.055)",
        "--card-shadow-hover": "0 2px 6px rgba(15,23,42,.06),0 14px 30px rgba(15,23,42,.10)",
    },
}


def theme_root_css(theme: str) -> str:
    """The :root variable block for the active theme + a light-mode readability net."""
    p = _PALETTES.get(theme, _PALETTES["dark"])
    root = ";".join(f"{k}:{v}" for k, v in p.items())
    fix = ""
    if theme == "light":
        # Catch text that hardcodes a light color inline so it stays readable on white.
        fix = ("[data-testid='stAppViewContainer'],[data-testid='stMarkdownContainer']{color:var(--text);}"
               "[data-testid='stAppViewContainer'] p{color:var(--text2);}"
               "[data-baseweb='select'] *{color:var(--text) !important;}"
               "[data-baseweb='popover'] li{color:var(--text) !important;}")
    return f"<style>:root{{{root}}}{fix}</style>"

ICONS = {
    "shield":   '<svg viewBox="0 0 24 24"><path d="M12 2l8 4v6c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6l8-4z"/></svg>',
    "users":    '<svg viewBox="0 0 24 24"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    "home":     '<svg viewBox="0 0 24 24"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><path d="M9 22V12h6v10"/></svg>',
    "plus":     '<svg viewBox="0 0 24 24"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>',
    "minus":    '<svg viewBox="0 0 24 24"><line x1="5" y1="12" x2="19" y2="12"/></svg>',
    "trend":    '<svg viewBox="0 0 24 24"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>',
    "dollar":   '<svg viewBox="0 0 24 24"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>',
    "calendar": '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>',
    "file":     '<svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>',
    "book":     '<svg viewBox="0 0 24 24"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>',
    "search":   '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
    "bell":     '<svg viewBox="0 0 24 24"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>',
    "clock":    '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
    "info":     '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    "pie":      '<svg viewBox="0 0 24 24"><path d="M21.21 15.89A10 10 0 1 1 8 2.83"/><path d="M22 12A10 10 0 0 0 12 2v10z"/></svg>',
    "pin":      '<svg viewBox="0 0 24 24"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>',
    "bars":     '<svg viewBox="0 0 24 24"><line x1="6" y1="20" x2="6" y2="14"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="18" y1="20" x2="18" y2="10"/></svg>',
    "target":   '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>',
    "refresh":  '<svg viewBox="0 0 24 24"><polyline points="23 4 23 10 17 10"/><polyline points="1 20 1 14 7 14"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/></svg>',
    "gear":     '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
}

def inject_css():
    # Palette first (dark/light) so every var() below resolves for the active theme.
    st.markdown(theme_root_css(st.session_state.get("agent_theme", "dark")), unsafe_allow_html=True)
    st.markdown(f"""
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
    
      html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"],
      .stMarkdown, .stButton, input, textarea, select, [class*="css"] {{
        font-family: 'Inter', ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }}
    
      /* Page background with radial lighting */
      [data-testid="stAppViewContainer"] {{
        background:
          radial-gradient(1100px 560px at 82% -8%, var(--tint1), transparent 60%),
          radial-gradient(900px 520px at 8% -4%, var(--tint2), transparent 55%),
          {T['page_bg']};
      }}
      [data-testid="stHeader"] {{ background: transparent; }}
      .main .block-container {{
        background: transparent;
        max-width: 1320px;
        padding-top: 2.2rem;
      }}
      h1, h2, h3, h4, p, label, .stMarkdown {{ color: {T['text_primary']}; }}
      [data-testid="stMarkdownContainer"] h1, .stApp h1 {{ color: {T['text_primary']} !important; }}
    
      /* ── Sidebar — dark blue gradient, rounded, bordered ── */
      [data-testid="stSidebar"] {{
        background: linear-gradient(185deg, var(--sidebar1) 0%, var(--sidebar2) 100%);
        border-right: 1px solid {T['divider']};
      }}
      [data-testid="stSidebar"] > div:first-child {{
        padding-top: 10px;
        border-radius: 0 22px 22px 0;
      }}
      [data-testid="stSidebar"] * {{ color: var(--sidebar-text); }}
      [data-testid="stSidebar"] h2 {{
        font-size: 1.15rem; font-weight: 800; letter-spacing: -0.01em;
        padding: 6px 4px 2px;
      }}
      /* Nav items (radio styled as menu) */
      section[data-testid="stSidebar"] div[role="radiogroup"] {{ gap: 6px; }}
      section[data-testid="stSidebar"] div[role="radiogroup"] > label {{
        display: flex; align-items: center; gap: 14px; width: 100%;
        padding: 13px 16px; border-radius: 14px; margin: 2px 0;
        transition: background .15s ease, box-shadow .15s ease;
        cursor: pointer;
      }}
      /* per-item icon slot (icon image set per nth-of-type below) */
      section[data-testid="stSidebar"] div[role="radiogroup"] > label::before {{
        content: ""; flex: 0 0 auto; width: 20px; height: 20px;
        background-repeat: no-repeat; background-position: center; background-size: contain;
        opacity: 0.85;
      }}
      section[data-testid="stSidebar"] div[role="radiogroup"] > label:hover {{
        background: rgba(96,165,250,0.07);
      }}
      /* selected page: dark pill with a blue→purple ring, soft glow, red dot */
      section[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) {{
        background: var(--sidebar-sel-bg);
        box-shadow: var(--nav-active-shadow);
      }}
      section[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked)::before {{
        opacity: 1;
      }}
      section[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) p {{
        font-weight: 700; color: var(--sidebar-sel);
      }}
      section[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) > div:last-child,
      section[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) [data-testid="stMarkdownContainer"] {{
        flex: 1; width: 100%;
      }}
      /* hide the radio dot so it reads as a clean nav item (streamlit is PINNED
         to 1.50.0 in requirements.txt — an unpinned cloud version rendered a
         different DOM where this rule missed and the dot showed) */
      section[data-testid="stSidebar"] div[role="radiogroup"] > label > div:first-child,
      section[data-testid="stSidebar"] div[role="radiogroup"] > label > span:first-child {{
        display: none !important;
      }}
      section[data-testid="stSidebar"] div[role="radiogroup"] label p {{
        font-size: 0.97rem; font-weight: 500; color: var(--sidebar-nav);
        display: flex; align-items: center; width: 100%;
      }}
      /* sidebar footer info rows (snapshot / client count) */
      .sb-foot {{ display: flex; align-items: center; gap: 11px; margin: 7px 2px; }}
      .sb-foot .tile {{
        flex: 0 0 auto; width: 32px; height: 32px; border-radius: 9px;
        background: var(--sidebar-tile); box-shadow: inset 0 0 0 1px rgba(96,165,250,0.14);
        display: flex; align-items: center; justify-content: center; font-size: .85rem;
      }}
      .sb-foot .txt {{ font-size: .88rem; color: var(--sidebar-nav); }}
      .sb-foot .txt b {{ color: var(--sidebar-text); }}
      /* Brand logo row */
      .brand-row {{ display: flex; align-items: center; gap: 11px; padding: 8px 4px 2px; }}
      .brand-row .brand-logo {{
        width: 34px; height: 34px; border-radius: 10px; display: flex; align-items: center; justify-content: center;
        background: linear-gradient(145deg, {BLUE}, {PURPLE}); box-shadow: 0 6px 16px rgba(124,58,237,0.35);
      }}
      .brand-row .brand-logo svg {{ width: 18px; height: 18px; stroke: #fff; fill: none; stroke-width: 2.2; }}
      .brand-row .brand-text {{ font-size: 1.12rem; font-weight: 800; letter-spacing: -0.01em; color: var(--sidebar-text); }}
      /* Sidebar buttons */
      [data-testid="stSidebar"] .stButton > button {{
        background: linear-gradient(90deg, {BLUE}, {PURPLE});
        color: #fff; border: none; border-radius: 12px; font-weight: 600;
        box-shadow: 0 8px 22px rgba(59,130,246,0.28);
        transition: filter .15s ease, transform .15s ease;
      }}
      [data-testid="stSidebar"] .stButton > button:hover {{
        filter: brightness(1.08); transform: translateY(-1px);
      }}
      [data-testid="stSidebar"] [data-testid="stDownloadButton"] > button {{
        background: rgba(15,28,52,0.6); color: #cbd5e1;
        border: 1px solid rgba(96,165,250,0.32); border-radius: 12px; font-weight: 600;
        box-shadow: none;
      }}
      [data-testid="stSidebar"] [data-testid="stDownloadButton"] > button:hover {{
        border-color: rgba(96,165,250,0.6); color: #fff;
      }}
    
      /* ── Dashboard header + topbar ── */
      .dash-header {{
        display: flex; align-items: flex-start; justify-content: space-between;
        margin: 2px 0 4px;
      }}
      /* Sleek hero header */
      .dash-hero {{
        display: flex; align-items: center; justify-content: space-between; gap: 16px;
        margin: 2px 0 8px; padding-bottom: 16px;
        border-bottom: 1px solid transparent;
        border-image: linear-gradient(90deg, rgba(96,165,250,0.5), rgba(124,58,237,0.28), rgba(96,165,250,0)) 1;
      }}
      .dash-hero-left {{ display: flex; align-items: center; gap: 17px; }}
      .dash-accent {{ width: 6px; height: 56px; border-radius: 6px; flex: 0 0 auto;
        background: linear-gradient(180deg, #60a5fa, #7c3aed);
        box-shadow: 0 0 20px rgba(96,165,250,0.55); }}
      .dash-title {{ font-size: 2.8rem; font-weight: 800; letter-spacing: -0.03em; line-height: 1;
        background: var(--title-grad);
        -webkit-background-clip: text; background-clip: text;
        -webkit-text-fill-color: transparent; color: transparent; }}
      .dash-sub {{ color: {T['kpi_lbl']}; font-size: 0.92rem; margin-top: 9px;
        display: flex; align-items: center; gap: 8px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600; }}
      .dash-sub .live-dot {{ width: 8px; height: 8px; border-radius: 50%; background: #22c55e;
        box-shadow: 0 0 0 4px rgba(34,197,94,0.16); display: inline-block; }}
      .date-badge {{ display: inline-flex; align-items: center; gap: 8px; flex: 0 0 auto; white-space: nowrap;
        background: linear-gradient(160deg, rgba(96,165,250,0.14), rgba(124,58,237,0.10));
        border: 1px solid rgba(96,165,250,0.32); border-radius: 999px; padding: 10px 18px;
        color: var(--text); font-weight: 700; font-size: 0.84rem; letter-spacing: 0.02em;
        box-shadow: 0 8px 24px rgba(8,20,46,0.45); }}
      .date-badge svg {{ width: 15px; height: 15px; stroke: #8fb3ec; fill: none; stroke-width: 2; }}
      .legend-pill {{ display: inline-flex; align-items: center; gap: 7px; padding: 5px 12px; margin-right: 9px;
        background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.06); border-radius: 999px; }}
      .topbar {{ display: flex; align-items: center; gap: 12px; }}
      .topbar .tb-icon {{
        width: 38px; height: 38px; border-radius: 11px; display: flex; align-items: center; justify-content: center;
        background: rgba(15,28,52,0.7); border: 1px solid rgba(96,165,250,0.2);
      }}
      .topbar .tb-icon svg {{ width: 18px; height: 18px; stroke: {T['kpi_lbl']}; fill: none; stroke-width: 2; }}
      .avatar {{
        width: 40px; height: 40px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
        font-weight: 700; font-size: 0.85rem; color: #fff;
        background: linear-gradient(145deg, {BLUE}, {PURPLE});
        box-shadow: 0 6px 18px rgba(124,58,237,0.35);
      }}
    
      /* ── Section headers ── */
      .section-head {{ display: flex; align-items: center; gap: 11px; margin: 30px 0 16px; }}
      .section-head .sh-icon svg {{ width: 16px; height: 16px; stroke: {ELEC}; fill: none; stroke-width: 2; }}
      .section-head .sh-title {{
        font-size: 0.78rem; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase;
        color: var(--sec-head); white-space: nowrap;
      }}
      .section-head .sh-line {{ flex: 1; height: 1px; background: linear-gradient(90deg, rgba(96,165,250,0.28), rgba(96,165,250,0.02)); }}
    
      /* ── Metric cards (glassy) ── */
      .metric-card {{
        position: relative; overflow: hidden;
        background: var(--panel-grad);
        border: 1px solid {T['kpi_border']};
        border-radius: 18px; padding: 22px 22px 18px;
        box-shadow: var(--card-shadow);
        transition: transform .2s ease, border-color .2s ease, box-shadow .2s ease;
        height: 100%;
      }}
      .metric-card:hover {{
        transform: translateY(-3px);
        border-color: rgba(96,165,250,0.55);
        box-shadow: var(--card-shadow-hover);
      }}
      .metric-card.highlight {{
        border-color: rgba(124,58,237,0.6);
        background: var(--hl-grad);
        box-shadow: 0 0 0 1px rgba(124,58,237,0.42), 0 0 42px rgba(124,58,237,0.28);
      }}
      .metric-card.highlight:hover {{ box-shadow: 0 0 0 1px rgba(124,58,237,0.6), 0 0 54px rgba(124,58,237,0.4); }}
      .metric-card.highlight.green {{
        border-color: rgba(34,197,94,0.6);
        background: var(--hl-green-grad);
        box-shadow: 0 0 0 1px rgba(34,197,94,0.42), 0 0 42px rgba(34,197,94,0.28);
      }}
      .metric-card.highlight.green:hover {{ box-shadow: 0 0 0 1px rgba(34,197,94,0.6), 0 0 54px rgba(34,197,94,0.4); }}
      .metric-card.highlight.green .mc-icon svg {{ stroke: {GREEN}; }}
      .mc-icon {{
        width: 42px; height: 42px; border-radius: 12px; display: flex; align-items: center; justify-content: center;
        background: var(--icon-info-bg);
        border: 1px solid rgba(96,165,250,0.22);
      }}
      .mc-icon svg {{ width: 20px; height: 20px; stroke: var(--icon-info); fill: none; stroke-width: 2; }}
      .mc-icon.mc-plus {{ background: var(--icon-pos-bg); }}
      .mc-icon.mc-plus svg {{ stroke: var(--icon-pos); }}
      .mc-icon.mc-minus {{ background: var(--icon-neg-bg); }}
      .mc-icon.mc-minus svg {{ stroke: var(--icon-neg); }}
      .metric-card.highlight .mc-icon svg {{ stroke: #c4b5fd; }}
      .mc-value {{ font-size: 2.5rem; font-weight: 800; color: {T['kpi_val']}; line-height: 1.04; margin-top: 16px; letter-spacing: -0.02em; }}
      .mc-label {{ font-size: 0.72rem; color: {T['kpi_lbl']}; text-transform: uppercase; letter-spacing: 0.08em; margin-top: 5px; font-weight: 600; }}
      .mc-sub {{ font-size: 0.72rem; color: {T['kpi_sub']}; margin-top: 9px; }}
      .mc-spark {{ position: absolute; top: 20px; right: 20px; opacity: 0.95; }}
    
      /* ── Legacy KPI boxes (other pages) restyled to match ── */
      .kpi-box {{
        background: var(--panel-grad);
        border-radius: 16px; padding: 20px 16px 16px; text-align: center;
        border: 1px solid {T['kpi_border']};
        transition: transform .2s ease, border-color .2s ease;
      }}
      .kpi-box:hover {{ transform: translateY(-2px); border-color: rgba(96,165,250,0.5); }}
      .kpi-value {{ font-size: 2.1rem; font-weight: 800; color: {T['kpi_val']}; line-height: 1.1; }}
      .kpi-label {{ font-size: 0.72rem; color: {T['kpi_lbl']}; margin-top: 6px; text-transform: uppercase; letter-spacing: 0.06em; }}
      .section-divider {{ margin: 8px 0 20px; border-top: 1px solid {T['divider']}; }}
    
      .goal-kpi-box {{
        background: var(--panel-grad);
        border-radius: 16px; padding: 24px 16px 20px; text-align: center;
        border: 1px solid {T['kpi_border']}; position: relative;
        transition: transform .2s ease, border-color .2s ease;
      }}
      .goal-kpi-box:hover {{ transform: translateY(-2px); border-color: rgba(96,165,250,0.5); }}
      .goal-kpi-value {{ font-size: 2.6rem; font-weight: 800; color: {T['goal_val']}; line-height: 1.1; }}
      .goal-kpi-value.green  {{ color: {T['goal_green']}; }}
      .goal-kpi-value.gold   {{ color: {T['goal_gold']}; }}
      .goal-kpi-value.red    {{ color: {T['goal_red']}; }}
      .goal-kpi-label {{ font-size: 0.72rem; color: {T['kpi_lbl']}; margin-top: 6px; text-transform: uppercase; letter-spacing: 0.06em; }}
      .goal-kpi-sub {{ font-size: 0.82rem; color: {T['kpi_lbl']}; margin-top: 4px; }}
      .progress-wrap {{ background: {T['progress_bg']}; border-radius: 999px; height: 22px; overflow: hidden; margin: 10px 0 6px; }}
      .progress-bar {{ height: 100%; border-radius: 999px; background: linear-gradient(90deg, {BLUE}, {PURPLE}); transition: width 0.6s ease; }}
    
      /* ── Glass panels (st.container(border=True)) ── */
      [data-testid="stVerticalBlockBorderWrapper"] {{
        background: var(--panel-grad);
        border: 1px solid rgba(96,165,250,0.22) !important;
        border-radius: 20px !important;
        padding: 8px 14px 10px;
        box-shadow: var(--card-shadow);
        transition: border-color .2s ease, box-shadow .2s ease;
      }}
      [data-testid="stVerticalBlockBorderWrapper"]:hover {{
        border-color: rgba(96,165,250,0.45) !important;
        box-shadow: var(--card-shadow-hover);
      }}
      /* Chart card header */
      .chart-head {{ display: flex; align-items: flex-start; gap: 12px; padding: 12px 6px 6px; }}
      .chart-head .ch-icon {{
        width: 34px; height: 34px; border-radius: 10px; display: flex; align-items: center; justify-content: center;
        background: linear-gradient(145deg, rgba(59,130,246,0.18), rgba(124,58,237,0.13)); border: 1px solid rgba(96,165,250,0.22);
      }}
      .chart-head .ch-icon svg {{ width: 17px; height: 17px; stroke: {ELEC}; fill: none; stroke-width: 2; }}
      .chart-head .ch-title {{ font-size: 1.05rem; font-weight: 700; color: {T['text_primary']}; line-height: 1.15; }}
      .chart-head .ch-sub {{ font-size: 0.76rem; color: {T['kpi_lbl']}; margin-top: 2px; }}
      .chart-head .ch-dots {{ margin-left: auto; color: #64748b; font-size: 1.4rem; line-height: 1; }}
      /* Book-age cards */
      .ba-card {{
        position: relative; overflow: hidden; height: 100%;
        background: var(--panel-grad);
        border: 1px solid rgba(96,165,250,0.22); border-radius: 16px; padding: 16px 16px 14px;
        transition: transform .2s ease, border-color .2s ease, box-shadow .2s ease;
      }}
      .ba-card:hover {{ transform: translateY(-3px); border-color: rgba(96,165,250,0.5);
        box-shadow: 0 12px 32px rgba(8,20,46,0.5); }}
      .ba-card .ba-bar {{ position: absolute; top: 0; left: 0; right: 0; height: 3px; }}
      .ba-icon {{ width: 38px; height: 38px; border-radius: 11px; display: flex; align-items: center; justify-content: center; }}
      .ba-icon svg {{ width: 18px; height: 18px; fill: none; stroke-width: 2; }}
      .ba-val {{ font-size: 1.95rem; font-weight: 800; color: {T['kpi_val']}; line-height: 1; margin-top: 12px; }}
      .ba-lbl {{ font-size: 0.72rem; color: {T['kpi_lbl']}; text-transform: uppercase; letter-spacing: 0.06em; margin-top: 5px; }}
      .ba-pct {{ font-size: 0.98rem; font-weight: 700; margin-top: 6px; }}
      /* Insight callout */
      .insight {{
        display: flex; align-items: flex-start; gap: 14px; margin: 16px 6px 6px;
        background: linear-gradient(90deg, rgba(59,130,246,0.13), rgba(59,130,246,0.04));
        border: 1px solid rgba(96,165,250,0.3); border-radius: 14px; padding: 14px 18px;
      }}
      .insight .in-icon {{
        flex: 0 0 auto; width: 34px; height: 34px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
        background: rgba(59,130,246,0.18); border: 1px solid rgba(96,165,250,0.4);
      }}
      .insight .in-icon svg {{ width: 18px; height: 18px; stroke: {ELEC}; fill: none; stroke-width: 2; }}
      .insight .in-main {{ font-size: 0.95rem; font-weight: 700; color: var(--text); }}
      .insight .in-sub {{ font-size: 0.82rem; color: {T['kpi_lbl']}; margin-top: 3px; }}
    
      /* ── Stat cards (icon-left layout) ── */
      .stat-card {{
        display: flex; align-items: center; gap: 16px; height: 100%;
        background: var(--panel-grad);
        border: 1px solid rgba(96,165,250,0.22); border-radius: 18px; padding: 20px 20px;
        transition: transform .2s ease, border-color .2s ease, box-shadow .2s ease;
      }}
      .stat-card:hover {{ transform: translateY(-3px); border-color: rgba(96,165,250,0.5);
        box-shadow: 0 12px 32px rgba(8,20,46,0.5), 0 0 28px rgba(59,130,246,0.12); }}
      .stat-card .sc-icon {{ flex: 0 0 auto; width: 50px; height: 50px; border-radius: 14px;
        display: flex; align-items: center; justify-content: center; }}
      .stat-card .sc-icon svg {{ width: 23px; height: 23px; fill: none; stroke-width: 2; }}
      .stat-card .sc-val {{ font-size: 2rem; font-weight: 800; color: {T['kpi_val']}; line-height: 1; }}
      .stat-card .sc-lbl {{ font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.06em;
        color: {T['kpi_lbl']}; margin-top: 7px; font-weight: 600; }}
      /* ── Hover tooltip on the Dashboard action cards ── */
      [data-testid="stHorizontalBlock"], [data-testid="column"], [data-testid="stVerticalBlock"],
      [data-testid="stMarkdownContainer"], .element-container, .stMarkdown {{ overflow: visible !important; }}
      .tip-wrap {{ position: relative; display: block; }}
      .tip-pop {{
        position: absolute; top: calc(100% + 10px); left: 50%; transform: translateX(-50%) translateY(6px);
        z-index: 1000; width: 340px; max-width: 88vw; text-align: left;
        background: linear-gradient(160deg, rgba(27,44,77,0.99), rgba(13,23,42,0.99));
        border: 1px solid rgba(96,165,250,0.45); border-radius: 16px; padding: 18px 20px;
        color: #e8f0ff; font-size: 1.02rem; line-height: 1.5; font-weight: 500; letter-spacing: .1px;
        box-shadow: 0 22px 60px rgba(0,0,0,0.6), 0 0 34px rgba(59,130,246,0.18);
        opacity: 0; visibility: hidden; pointer-events: none;
        transition: opacity .18s ease, transform .18s ease;
      }}
      .tip-pop::before {{
        content: ""; position: absolute; bottom: 100%; left: 50%; transform: translateX(-50%);
        border: 8px solid transparent; border-bottom-color: rgba(96,165,250,0.45);
      }}
      .tip-pop .tip-title {{ display: block; font-size: 0.74rem; font-weight: 800; text-transform: uppercase;
        letter-spacing: 0.08em; color: #8fb3ec; margin-bottom: 8px; }}
      .tip-wrap:hover .tip-pop, .tip-wrap.tip-show .tip-pop {{ opacity: 1; visibility: visible; transform: translateX(-50%) translateY(0); }}
      /* ── Target progress bar ── */
      .tp-head {{ display: flex; align-items: center; gap: 9px; margin: 6px 2px 2px; }}
      .tp-head .tp-title {{ font-size: 1.15rem; font-weight: 700; color: {T['text_primary']}; }}
      .tp-head .tp-info svg {{ width: 16px; height: 16px; stroke: {T['kpi_lbl']}; fill: none; stroke-width: 2; vertical-align: middle; }}
      .target-track {{ background: rgba(10,19,38,0.9); border: 1px solid rgba(96,165,250,0.18);
        border-radius: 999px; height: 14px; overflow: hidden; margin: 10px 2px 6px; }}
      .target-fill {{ height: 100%; border-radius: 999px;
        background: linear-gradient(90deg, #f43f5e, #fb7185);
        box-shadow: 0 0 18px rgba(244,63,94,0.5); transition: width .6s ease; }}
    
      /* ── Form inputs (number / date / text / select) — cohesive dark fields ── */
      [data-testid="stNumberInput"] div[data-baseweb="input"],
      [data-testid="stDateInput"] div[data-baseweb="input"] {{
        background: var(--input-bg) !important;
        border: 1px solid rgba(96,165,250,0.22) !important;
        border-radius: 12px !important;
        overflow: hidden;
      }}
      [data-testid="stNumberInput"] input,
      [data-testid="stDateInput"] input {{
        background: transparent !important; color: {T['text_primary']} !important;
      }}
      [data-testid="stNumberInput"] div[data-baseweb="input"]:focus-within,
      [data-testid="stDateInput"] div[data-baseweb="input"]:focus-within {{
        border-color: rgba(96,165,250,0.6) !important;
        box-shadow: 0 0 0 1px rgba(96,165,250,0.22) !important;
      }}
      /* number-input stepper (− / +) buttons blended into the field */
      [data-testid="stNumberInput"] button {{
        background: transparent !important; border: none !important;
        border-left: 1px solid rgba(96,165,250,0.15) !important;
        color: {T['kpi_lbl']} !important; border-radius: 0 !important;
      }}
      [data-testid="stNumberInput"] button:hover {{
        background: rgba(59,130,246,0.18) !important; color: #fff !important;
      }}
      /* selectbox dropdowns */
      [data-testid="stSelectbox"] div[data-baseweb="select"] > div {{
        background: var(--input-bg) !important;
        border: 1px solid rgba(96,165,250,0.22) !important;
        border-radius: 12px !important;
      }}
    
      /* ── Mobile / tablet ── */
      @media (max-width: 768px) {{
        .dash-title {{ font-size: 1.9rem; }}
        .topbar {{ gap: 8px; }}
        .kpi-box {{ padding: 16px 12px 12px; margin-bottom: 8px; }}
        .kpi-value {{ font-size: 1.8rem; }}
        .kpi-label {{ font-size: 0.65rem; }}
        .metric-card {{ padding: 18px 16px 14px; margin-bottom: 8px; }}
        .mc-value {{ font-size: 2rem; }}
        .goal-kpi-box {{ padding: 18px 12px 14px; margin-bottom: 8px; }}
        .goal-kpi-value {{ font-size: 2rem; }}
        /* compact stat-cards (money + action rows) so 4-across stacks cleanly on phones */
        .stat-card {{ padding: 14px 14px; gap: 12px; margin-bottom: 8px; }}
        .stat-card .sc-icon {{ width: 40px; height: 40px; }}
        .stat-card .sc-icon svg {{ width: 19px; height: 19px; }}
        .stat-card .sc-val {{ font-size: 1.5rem; }}
        .stat-card .sc-lbl {{ font-size: 0.6rem; }}
        .stat-card .sc-delta {{ font-size: 0.66rem; }}
        .ch-title {{ font-size: 1rem; }}
        .block-container {{ padding-left: 1rem !important; padding-right: 1rem !important; padding-top: 1rem !important; }}
        [data-testid="stDataFrame"] {{ overflow-x: auto; }}
        [data-testid="stDataFrame"] [role="progressbar"] > div {{ background-color: {GREEN} !important; }}
        h1 {{ font-size: 1.6rem !important; }}
        h2 {{ font-size: 1.2rem !important; }}
        h3 {{ font-size: 1rem !important; }}
        .progress-wrap {{ height: 26px; }}
      }}
    </style>
    """, unsafe_allow_html=True)

def _spark_vals(series, n=10):
    """Last n numeric values from a mom_df column, as a clean float list."""
    try:
        v = pd.to_numeric(series, errors="coerce").dropna().tail(n).tolist()
        return [float(x) for x in v]
    except Exception:
        return []


def sparkline(values, color=ELEC, w=86, h=30):
    """Inline SVG sparkline with a soft gradient fill."""
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    n = len(vals)
    pts = []
    for i, v in enumerate(vals):
        x = i / (n - 1) * w
        y = h - (v - lo) / rng * (h - 6) - 3
        pts.append(f"{x:.1f},{y:.1f}")
    poly = " ".join(pts)
    area = f"0,{h} " + poly + f" {w},{h}"
    gid = f"sg{abs(hash(poly)) % 999999}"
    return (
        f'<svg class="mc-spark" width="{w}" height="{h}" viewBox="0 0 {w} {h}" fill="none">'
        f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{color}" stop-opacity="0.35"/>'
        f'<stop offset="1" stop-color="{color}" stop-opacity="0"/></linearGradient></defs>'
        f'<polygon points="{area}" fill="url(#{gid})"/>'
        f'<polyline points="{poly}" stroke="{color}" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )


def section_header(title, icon_key):
    return (
        f'<div class="section-head"><span class="sh-icon">{ICONS.get(icon_key, "")}</span>'
        f'<span class="sh-title">{title}</span><span class="sh-line"></span></div>'
    )


def metric_card(label, value, sub="", icon_key="", spark="", highlight=False):
    # highlight=True -> purple accent; highlight="green" (or any class string) ->
    # that color variant.
    if highlight:
        cls = "metric-card highlight" + (f" {highlight}" if isinstance(highlight, str) else "")
    else:
        cls = "metric-card"
    icon_html = f'<div class="mc-icon mc-{icon_key}">{ICONS.get(icon_key, "")}</div>' if icon_key else ""
    sub_html = f'<div class="mc-sub">{sub}</div>' if sub else ""
    return (
        f'<div class="{cls}">{icon_html}{spark}'
        f'<div class="mc-value">{value}</div>'
        f'<div class="mc-label">{label}</div>{sub_html}</div>'
    )



def stat_card(label, value, icon_key, color, delta=None, delta_good=True):
    """Icon-left KPI card (tinted circular icon + value + label).
    Optional `delta` renders a small trend line under the value (e.g. "▲ 9% vs
    last month"); colored green when delta_good else red."""
    icon = ICONS.get(icon_key, "").replace("<svg ", f'<svg stroke="{color}" ', 1)
    delta_html = ""
    if delta:
        dc = GREEN if delta_good else RED
        delta_html = (f'<div class="sc-delta" style="color:{dc};font-size:0.72rem;'
                      f'font-weight:700;margin-top:3px;letter-spacing:.2px;">{delta}</div>')
    return (
        f'<div class="stat-card">'
        f'<div class="sc-icon" style="background:{color}22;border:1px solid {color}55;">{icon}</div>'
        f'<div><div class="sc-val">{value}</div><div class="sc-lbl">{label}</div>{delta_html}</div>'
        f'</div>'
    )


# Color language (consistent across the app):
#   green = money / good · red = risk / loss · gold = needs attention
#   electric/cyan = neutral info · purple = time / coverage
GOOD, RISK, ATTN, INFO = GREEN, RED, GOLD, ELEC



# ── Plotly chart helpers (ported) ──────────────────────────────────────────
def chart_head(title, sub, icon_key):
    return (
        f'<div class="chart-head"><div class="ch-icon">{ICONS.get(icon_key, "")}</div>'
        f'<div><div class="ch-title">{title}</div><div class="ch-sub">{sub}</div></div>'
        f'<div class="ch-dots">⋮</div></div>'
    )



_DT_CSS = """<style>
.dt-wrap{border:1px solid var(--border);border-radius:16px;background:var(--dt-bg);
  overflow:hidden;margin:4px 0 6px;}
.dt-scroll{overflow:auto;}
table.dt{border-collapse:collapse;width:100%;font-size:.86rem;color:var(--dt-text);}
table.dt thead th{position:sticky;top:0;z-index:1;background:var(--dt-head);color:var(--dt-head-text);
  font-weight:600;font-size:.7rem;letter-spacing:.045em;text-transform:uppercase;text-align:left;
  padding:12px 16px;border-bottom:1px solid var(--border);white-space:nowrap;}
table.dt th.r{text-align:right;} table.dt th.c{text-align:center;}
table.dt tbody td{padding:11px 16px;border-bottom:1px solid var(--dt-row);white-space:nowrap;}
table.dt tbody tr:last-child td{border-bottom:none;}
table.dt tbody tr:hover td{background:var(--dt-hover);}
.dt-pill{display:inline-block;padding:2px 10px;border-radius:999px;font-size:.76rem;font-weight:600;
  background:var(--pill-bg);color:var(--pill-text);border:1px solid var(--pill-bd);}
.dt-state{display:inline-block;padding:1px 8px;border-radius:6px;font-size:.72rem;font-weight:700;
  background:var(--pill-bg);color:var(--pill-text);border:1px solid var(--pill-bd);}
.dt-status{display:inline-flex;align-items:center;gap:6px;padding:2px 11px;border-radius:999px;
  font-size:.75rem;font-weight:600;}
.dt-status::before{content:"";width:6px;height:6px;border-radius:50%;background:currentColor;flex:0 0 auto;}
.dt-money{font-weight:700;color:var(--text);text-align:right;font-variant-numeric:tabular-nums;}
.dt-num{color:var(--dt-text);text-align:right;font-variant-numeric:tabular-nums;}
.dt-up{color:var(--pos);font-weight:700;text-align:right;font-variant-numeric:tabular-nums;}
.dt-down{color:var(--neg);font-weight:700;text-align:right;font-variant-numeric:tabular-nums;}
.dt-days{font-weight:700;color:var(--neg);font-variant-numeric:tabular-nums;}
.dt-days.new{color:var(--pos);}
.dt-prod{display:inline-flex;align-items:center;gap:7px;}
.dt-prod svg{width:15px;height:15px;stroke:var(--dt-head-text);fill:none;stroke-width:1.8;}
.dt-muted{color:var(--dt-muted);}
.dt-foot{display:flex;justify-content:space-between;align-items:center;padding:10px 16px;
  font-size:.78rem;color:var(--dt-muted);border-top:1px solid var(--border);}
.dt-empty{padding:22px 16px;color:var(--dt-head-text);font-size:.9rem;}
</style>"""

_DT_EMOJI = _re.compile(r"[\U0001F534\U0001F7E1\U0001F7E0\U0001F7E2⚪\U0001F535]")
_SHIELD = ('<svg viewBox="0 0 24 24"><path d="M12 2l8 4v6c0 5-3.5 8.5-8 10-4.5-1.5-8-5-8-10V6z"/></svg>')


def _dt_pill_color(v):
    s = str(v).lower()
    if "\U0001F534" in s or any(k in s for k in ("cancel", "lapse", "taken", "expired", "terminat",
            "overdue", "past due", "inactive", "never paid", "stopped", "<30", "at risk")):
        return "#f87171", "rgba(239,68,68,.13)", "rgba(239,68,68,.30)"
    if any(e in s for e in ("\U0001F7E1", "\U0001F7E0")) or any(k in s for k in ("pending", "open",
            "follow", "binder", "grace", "disconnect", "30–60", "60–90", "30-60", "60-90", "due")):
        return "#fbbf24", "rgba(245,158,11,.13)", "rgba(245,158,11,.30)"
    if any(k in s for k in ("paid", "active", "effectuat", "enrolled", "current", "matches", "reconnect")):
        return "#4ade80", "rgba(34,197,94,.13)", "rgba(34,197,94,.30)"
    if "⚪" in s or "90+" in s or "unknown" in s:
        return "#94a3b8", "rgba(148,163,184,.12)", "rgba(148,163,184,.26)"
    return "#93c5fd", "rgba(59,130,246,.13)", "rgba(59,130,246,.28)"


_NUMRE = _re.compile(r"^-?[\d,]+(\.\d+)?%?$")


def _dt_kind(col, series):
    n = str(col).lower().strip()
    if "carrier" in n:
        return "carrier"
    if n in ("state", "st"):
        return "state"
    if n == "product":
        return "product"
    if any(k in n for k in ("net change", "% growth", "growth", "net members", "net")):
        return "delta"
    if any(k in n for k in ("status", "urgency", "why ended", "type", "handled")):
        return "status"
    if "days" in n:
        return "days"
    if "phone" in n:
        return "muted"
    first = next((str(x) for x in series.tolist()
                  if str(x).strip().lower() not in ("", "nan", "none", "nat")), "")
    if n == "balance" or first.strip().startswith("$"):
        return "money"
    # Pure-number columns (Members, Policies, counts, %) right-align.
    try:
        if pd.api.types.is_numeric_dtype(series):
            return "num"
    except Exception:
        pass
    if first and _NUMRE.match(first.replace(" ", "")):
        return "num"
    return "text"


def styled_table(df, empty="No rows.", height=520, max_rows=None, bare=False):
    """Render a DataFrame as the product data-table: rounded dark container, sticky
    header, hover rows, and auto-styled cells — carrier/state pills, colored status
    pills, red 'days' values, right-aligned money/numbers, green/red deltas. Column
    types auto-detect by name/value; pass a pre-shaped DataFrame with the columns you
    want shown. bare=True drops the outer border+footer for use inside a titled card."""
    if df is None or getattr(df, "empty", True):
        msg = f'<div class="dt-empty">{_html.escape(empty)}</div>'
        st.markdown(_DT_CSS + (msg if bare else f'<div class="dt-wrap">{msg}</div>'),
                    unsafe_allow_html=True)
        return
    total = len(df)
    if max_rows and total > max_rows:
        df = df.head(max_rows)
    cols = list(df.columns)
    kinds = {c: _dt_kind(c, df[c]) for c in cols}
    hcls = {c: ("r" if kinds[c] == "money" else ("c" if kinds[c] == "num" else "")) for c in cols}
    head = "".join(f'<th class="{hcls[c]}">{_html.escape(str(c))}</th>' for c in cols)

    rows = []
    for _, row in df.iterrows():
        tds = []
        for c in cols:
            v = row[c]
            sv = "" if v is None else str(v)
            if sv.strip().lower() in ("nan", "none", "nat"):
                sv = ""
            k = kinds[c]
            if not sv:
                tds.append('<td class="dt-muted">—</td>')
                continue
            e = _html.escape(sv)
            if k == "carrier":
                tds.append(f'<td><span class="dt-pill">{e}</span></td>')
            elif k == "state":
                tds.append(f'<td><span class="dt-state">{e}</span></td>')
            elif k == "product":
                tds.append(f'<td><span class="dt-prod">{_SHIELD}{e}</span></td>')
            elif k == "status":
                fg, bg, bd = _dt_pill_color(sv)
                txt = _html.escape(_DT_EMOJI.sub("", sv).strip())
                tds.append(f'<td><span class="dt-status" style="color:{fg};background:{bg};'
                           f'border:1px solid {bd};">{txt}</span></td>')
            elif k == "days":
                cls = "dt-days new" if sv.strip().lower() in ("new", "0", "today", "0d") else "dt-days"
                tds.append(f'<td class="{cls}">{e}</td>')
            elif k == "money":
                tds.append(f'<td class="dt-money">{e}</td>')
            elif k == "delta":
                d = sv.strip()
                cls = "dt-up" if d.startswith("+") else ("dt-down" if d.startswith("-") else "dt-num")
                tds.append(f'<td class="{cls}">{e}</td>')
            elif k == "num":
                tds.append(f'<td class="dt-num">{e}</td>')
            elif k == "muted":
                tds.append(f'<td class="dt-muted">{e}</td>')
            else:
                tds.append(f'<td>{e}</td>')
        rows.append("<tr>" + "".join(tds) + "</tr>")

    table_html = ('<div class="dt-scroll" style="max-height:' + str(height) + 'px;">'
                  '<table class="dt"><thead><tr>' + head + '</tr></thead><tbody>'
                  + "".join(rows) + '</tbody></table></div>')
    if bare:
        st.markdown(_DT_CSS + table_html, unsafe_allow_html=True)
    else:
        foot = f'<div class="dt-foot"><span>Showing {len(df):,} of {total:,}</span></div>'
        st.markdown(_DT_CSS + '<div class="dt-wrap">' + table_html + foot + '</div>',
                    unsafe_allow_html=True)


def show_chart(fig):
    """Render a Plotly chart: keep hover tooltips, but disable the floating
    toolbar and all zoom/pan/drag so it's display-only."""
    fig.update_xaxes(fixedrange=True)
    fig.update_yaxes(fixedrange=True)
    fig.update_layout(dragmode=False)
    st.plotly_chart(
        fig,
        use_container_width=True,
        config={"displayModeBar": False, "scrollZoom": False, "doubleClick": False},
    )



def _chart_layout(**extra) -> dict:
    base = dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#cbd5e1", size=12, family="Inter, sans-serif"),
        margin=dict(t=30, b=40, l=10, r=10),
        xaxis=dict(gridcolor="rgba(96,165,250,0.12)", showgrid=True, zeroline=False),
        yaxis=dict(gridcolor="rgba(96,165,250,0.12)", showgrid=True, zeroline=False),
        hoverlabel=dict(bgcolor="#0f1c34", bordercolor="rgba(96,165,250,0.4)",
                        font=dict(color="#f8fafc", family="Inter, sans-serif")),
    )
    base.update(extra)
    return base


