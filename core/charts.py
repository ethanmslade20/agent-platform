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
