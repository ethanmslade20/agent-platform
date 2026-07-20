"""Plotly figures for the product, styled to match Ethan's dashboard."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from core import ui

RED, GOLD, BLUE, PURPLE, GREEN, ELEC, CYAN = (
    ui.RED, ui.GOLD, ui.BLUE, ui.PURPLE, ui.GREEN, ui.ELEC, ui.CYAN)
BUCKET_COLORS = [RED, GOLD, BLUE, PURPLE, GREEN]


def book_age_buckets(active_df: pd.DataFrame, today=None) -> dict:
    today = pd.Timestamp(today) if today is not None else pd.Timestamp.today().normalize()
    mob = None
    if "months_on_book" in active_df.columns:
        mob = pd.to_numeric(active_df["months_on_book"], errors="coerce")
    if (mob is None or mob.isna().all()) and "effective_date" in active_df.columns:
        eff = pd.to_datetime(active_df["effective_date"], errors="coerce")
        mob = ((today - eff).dt.days / 30.44).round(1)
    mob = (mob if mob is not None else pd.Series(0.0, index=active_df.index)).fillna(0)
    return {
        "< 3 MO": int((mob < 3).sum()),
        "3–6 MO": int(((mob >= 3) & (mob < 6)).sum()),
        "6–12 MO": int(((mob >= 6) & (mob < 12)).sum()),
        "12–18 MO": int(((mob >= 12) & (mob < 18)).sum()),
        "18 MO+": int((mob >= 18).sum()),
    }


def book_age_fig(buckets: dict):
    df = pd.DataFrame({"Bucket": list(buckets), "Policies": list(buckets.values())})
    fig = px.bar(df, x="Bucket", y="Policies", text="Policies")
    fig.update_traces(marker_color=BUCKET_COLORS, marker_cornerradius=8,
                      textposition="outside", textfont=dict(size=13, color="#e2e8f0"),
                      hovertemplate="%{x}: %{y} policies<extra></extra>")
    mx = max(buckets.values()) if any(buckets.values()) else 1
    fig.update_layout(**ui._chart_layout(
        showlegend=False,
        xaxis=dict(showgrid=False, zeroline=False, tickfont=dict(size=12)),
        yaxis=dict(title="Policies", gridcolor="rgba(96,165,250,0.10)", range=[0, mx * 1.2]),
        margin=dict(t=16, b=20, l=10, r=10), height=300, bargap=0.45))
    return fig


def carrier_fig(carrier_df: pd.DataFrame):
    fig = px.pie(carrier_df, names="Carrier", values="Policies", hole=0.55,
                 color_discrete_sequence=[BLUE, ELEC, "#2d5fa6", GREEN, GOLD, CYAN,
                                          "#f97316", PURPLE, "#e84393", "#94a3b8"])
    fig.update_traces(textposition="inside", textinfo="percent",
                      insidetextorientation="horizontal", textfont_size=12,
                      marker=dict(line=dict(color="#0a1326", width=2)),
                      hovertemplate="%{label}: %{value} (%{percent})<extra></extra>")
    fig.update_layout(**ui._chart_layout(
        uniformtext_minsize=11, uniformtext_mode="hide",
        legend=dict(orientation="h", yanchor="top", y=-0.03, xanchor="center", x=0.5, font=dict(size=11)),
        margin=dict(t=10, b=10, l=10, r=10), height=440))
    return fig


def state_fig(state_df: pd.DataFrame):
    top = state_df.sort_values("Policies", ascending=False).head(15)
    fig = px.bar(top.sort_values("Policies"), x="Policies", y="State", orientation="h",
                 color="Policies", color_continuous_scale=[[0, "#1b2c4d"], [1, BLUE]], text="Policies")
    fig.update_traces(marker_cornerradius=5, textposition="outside",
                      textfont=dict(size=11, color="#cbd5e1"),
                      hovertemplate="%{y}: %{x} policies<extra></extra>")
    fig.update_layout(**ui._chart_layout(
        coloraxis_showscale=False,
        xaxis=dict(title="Policies", gridcolor="rgba(96,165,250,0.10)"),
        yaxis=dict(tickfont=dict(size=11)),
        margin=dict(t=6, b=20, l=50, r=44), height=370))
    return fig


def trends_fig(mom_df):
    if mom_df is None or getattr(mom_df, "empty", True):
        return None
    m = mom_df.copy()
    label = "Month Label" if "Month Label" in m.columns else m.columns[0]
    f = go.Figure()
    if "New Policies" in m.columns:
        f.add_trace(go.Bar(x=m[label], y=m["New Policies"], name="Added", marker_color=GREEN))
    if "Policies Lost" in m.columns:
        f.add_trace(go.Bar(x=m[label], y=m["Policies Lost"], name="Lost", marker_color=RED))
    f.update_traces(marker_cornerradius=5)
    f.update_layout(**ui._chart_layout(
        barmode="group", legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5),
        margin=dict(t=16, b=30, l=10, r=10), height=360))
    return f


def daily_month_fig(daily_df: pd.DataFrame):
    """Submissions-by-day bar for one month — best day highlighted gold."""
    df = daily_df.copy()
    df["Day"] = df["Date"].dt.strftime("%b %d")
    mx = max(int(df["Policies"].max()), 1)
    order = df["Day"].tolist()
    colors = [GOLD if int(p) == mx else GREEN for p in df["Policies"]]
    fig = px.bar(df, x="Day", y="Policies", text="Policies")
    fig.update_traces(marker_color=colors, marker_cornerradius=4, textposition="outside",
                      textfont_size=9, hovertemplate="%{x}: %{y} policies<extra></extra>")
    fig.update_layout(**ui._chart_layout(
        showlegend=False, height=430,
        xaxis=dict(showgrid=False, tickangle=-45, tickfont=dict(size=9),
                   categoryorder="array", categoryarray=order),
        yaxis=dict(title="Policies", gridcolor="rgba(96,165,250,0.10)"),
        margin=dict(t=14, b=10, l=10, r=10)))
    return fig


def members_over_time_fig(mom_plot):
    """Cumulative active members by month — spline area chart."""
    n = len(mom_plot)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=mom_plot["Month Label"], y=mom_plot["Total Members"],
        mode="lines+markers+text", text=mom_plot["Total Members"], textposition="top center",
        textfont=dict(size=11, color="#e2e8f0"),
        line=dict(color=ELEC, width=3, shape="spline"),
        marker=dict(size=8, color=BLUE, line=dict(width=2, color="#dbeafe")),
        fill="tozeroy", fillcolor="rgba(59,130,246,0.15)",
        hovertemplate="%{x}: %{y} members<extra></extra>"))
    fig.update_layout(**ui._chart_layout(
        showlegend=False, height=360,
        xaxis=dict(showgrid=False, zeroline=False, range=[-0.6, n - 0.2], automargin=True),
        yaxis=dict(title="Members", gridcolor="rgba(96,165,250,0.10)", showgrid=True,
                   zeroline=False, automargin=True),
        margin=dict(t=24, b=30, l=10, r=70)))
    return fig


def new_vs_lost_fig(mom_plot, added_col, lost_col):
    """Grouped Added (green) vs Lost (red) bars, month over month."""
    f = go.Figure()
    f.add_trace(go.Bar(x=mom_plot["Month Label"], y=mom_plot[added_col], name="Added", marker_color=GREEN))
    f.add_trace(go.Bar(x=mom_plot["Month Label"], y=mom_plot[lost_col], name="Lost", marker_color=RED))
    f.update_traces(marker_cornerradius=3, hovertemplate="%{x}: %{y}<extra></extra>")
    f.update_layout(**ui._chart_layout(
        barmode="group", bargap=0.3,
        legend=dict(orientation="h", yanchor="bottom", y=1.03, x=0, bgcolor="rgba(0,0,0,0)", font=dict(size=12)),
        height=360, margin=dict(t=34, b=44, l=10, r=10),
        xaxis=dict(showgrid=False, zeroline=False, tickangle=-45, tickfont=dict(size=10), automargin=True),
        yaxis=dict(gridcolor="rgba(96,165,250,0.10)", showgrid=True, zeroline=False, automargin=True)))
    return f


def goal_growth_figs(hist, pace_df, goal, goal_arr, today):
    """(members_fig, revenue_fig) — actual vs required-pace lines toward a goal."""
    today_iso = pd.Timestamp(today).isoformat()

    fm = go.Figure()
    fm.add_trace(go.Scatter(x=hist["month"], y=hist["active"], mode="lines+markers",
                            name="Actual", line=dict(color=BLUE, width=3), marker=dict(size=7)))
    fm.add_trace(go.Scatter(x=pace_df["month"], y=pace_df["required"], mode="lines",
                            name="Required pace", line=dict(color=GOLD, width=2, dash="dash")))
    fm.add_hline(y=goal, line_color=GREEN, line_dash="dot", line_width=1.5,
                 annotation_text=f"Goal: {goal:,}", annotation_position="top left",
                 annotation_font_color=GREEN)
    fm.add_vline(x=today_iso, line_color="#94a3b8", line_dash="dot", line_width=1,
                 annotation_text="Today", annotation_position="top right", annotation_font_color="#94a3b8")
    fm.update_layout(**ui._chart_layout(
        xaxis=dict(showgrid=False, title=""),
        yaxis=dict(showgrid=True, gridcolor="rgba(96,165,250,0.10)", title="Active members"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=0, r=0, t=30, b=0), height=360))

    fr = go.Figure()
    fr.add_trace(go.Scatter(x=hist["month"], y=hist["arr"], mode="lines+markers",
                            name="Actual ARR", line=dict(color=GREEN, width=3), marker=dict(size=7)))
    fr.add_trace(go.Scatter(x=pace_df["month"], y=pace_df["required_arr"], mode="lines",
                            name="Required pace", line=dict(color=GOLD, width=2, dash="dash")))
    fr.add_hline(y=goal_arr, line_color=GREEN, line_dash="dot", line_width=1.5,
                 annotation_text=f"Goal ARR: ${goal_arr:,.0f}", annotation_position="top left",
                 annotation_font_color=GREEN)
    fr.add_vline(x=today_iso, line_color="#94a3b8", line_dash="dot", line_width=1,
                 annotation_text="Today", annotation_position="top right", annotation_font_color="#94a3b8")
    fr.update_layout(**ui._chart_layout(
        xaxis=dict(showgrid=False, title=""),
        yaxis=dict(showgrid=True, gridcolor="rgba(96,165,250,0.10)", title="Annual Revenue ($)",
                   tickprefix="$", tickformat=",.0f"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=0, r=0, t=30, b=0), height=360))
    return fm, fr


def paid_by_month_fig(bm: pd.DataFrame):
    """Commission received per month — green bars. Plotly (not st.bar_chart) so the
    app never imports altair, which breaks on bleeding-edge Python on the host."""
    df = bm.copy()
    # 'Month' arrives as 'YYYY-MM' (e.g. '2026-06'). Render a human label AND force a
    # categorical x-axis — otherwise Plotly reads the ISO string as a datetime and
    # spreads the bars across a continuous date axis with bi-weekly ticks.
    def _lbl(m):
        try:
            return pd.to_datetime(f"{m}-01").strftime("%b %Y")
        except Exception:
            return str(m)
    df["MonthLabel"] = df["Month"].astype(str).map(_lbl)
    order = df["MonthLabel"].tolist()
    _p = pd.to_numeric(df["Paid"], errors="coerce").fillna(0)
    _lo = min(0.0, float(_p.min()))
    _hi = (float(_p.max()) * 1.18) or 1.0     # headroom so the top $ label isn't clipped
    fig = px.bar(df, x="MonthLabel", y="Paid", text="Paid")
    fig.update_traces(marker_color=GREEN, marker_cornerradius=6, textposition="outside",
                      texttemplate="$%{y:,.0f}", textfont=dict(size=11, color="#cbd5e1"),
                      hovertemplate="%{x}: $%{y:,.2f}<extra></extra>")
    fig.update_layout(**ui._chart_layout(
        showlegend=False, height=300,
        xaxis=dict(title="", showgrid=False, type="category",
                   categoryorder="array", categoryarray=order,
                   tickangle=-45 if len(df) > 6 else 0, tickfont=dict(size=11)),
        yaxis=dict(title="", gridcolor="rgba(96,165,250,0.10)", tickprefix="$", tickformat=",.0f",
                   range=[_lo, _hi]),
        margin=dict(t=20, b=44, l=10, r=10)))
    return fig


def daily_new_fig(roster: pd.DataFrame):
    col = "submission_date" if "submission_date" in roster.columns else "effective_date"
    if col not in roster.columns:
        return None
    d = pd.to_datetime(roster[col], errors="coerce").dropna()
    if d.empty:
        return None
    daily = d.dt.date.value_counts().sort_index().tail(60)
    df = pd.DataFrame({"Day": [str(x) for x in daily.index], "Policies": daily.values})
    fig = px.bar(df, x="Day", y="Policies", text="Policies")
    fig.update_traces(marker_color=BLUE, marker_cornerradius=4, textposition="outside",
                      textfont=dict(size=11, color="#cbd5e1"))
    fig.update_layout(**ui._chart_layout(
        showlegend=False, xaxis=dict(title="", showgrid=False),
        yaxis=dict(title="Policies", gridcolor="rgba(96,165,250,0.10)"),
        margin=dict(t=16, b=60, l=10, r=10), height=340))
    return fig
