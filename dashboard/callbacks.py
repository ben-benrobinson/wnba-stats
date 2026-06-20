import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from dash import Input, Output, dash_table
from dash.exceptions import PreventUpdate

from data.store import load
from data.teams import TEAM_LOGOS
from stats.bayesian import shrink_shooting

GOLD = "#f5a623"
BLUE = "#4a90d9"
GRAY = "#aaaaaa"

LEAGUE_AVG_TS = 0.545


def _load_advanced() -> pd.DataFrame:
    df = load("player_advanced")
    if df.empty:
        return df
    for col in ["G", "MP", "PER", "OWS", "DWS", "WS", "WS/40", "USG%", "ORtg", "DRtg"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _load_totals() -> pd.DataFrame:
    df = load("player_totals")
    if df.empty:
        return df
    for col in ["G", "MP", "PTS", "FGA", "FTA", "FGM", "FTM", "AST", "TOV", "TRB"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _load_per_game() -> pd.DataFrame:
    return load("player_per_game")


def register_callbacks(app) -> None:

    from dashboard.layout import league_layout, player_layout, team_layout

    @app.callback(Output("page-content", "children"), Input("url", "pathname"))
    def render_page(pathname):
        if pathname == "/player":
            return player_layout()
        if pathname == "/team":
            return team_layout()
        return league_layout()

    # ── League view ───────────────────────────────────────────────────────────
    @app.callback(
        Output("league-chart", "figure"),
        Output("league-table", "children"),
        Input("league-sort", "value"),
        Input("league-min-gp", "value"),
    )
    def update_league(sort_col, min_gp):
        adv = _load_advanced()
        tot = _load_totals()

        if adv.empty:
            return _empty_fig("No data yet — run the nightly refresh."), ""

        df = adv[adv["G"] >= min_gp].copy()

        # Compute NET_RTG
        df["NET_RTG"] = (
            pd.to_numeric(df["ORtg"], errors="coerce") -
            pd.to_numeric(df["DRtg"], errors="coerce")
        )

        # Bayesian TS% using season totals
        if not tot.empty:
            merged = df.merge(tot[["Player", "Team", "PTS", "FGA", "FTA"]], on=["Player", "Team"], how="left")
            fga = pd.to_numeric(merged.get("FGA"), errors="coerce").fillna(0)
            fta = pd.to_numeric(merged.get("FTA"), errors="coerce").fillna(0)
            pts = pd.to_numeric(merged.get("PTS"), errors="coerce").fillna(0)
            attempts = 2 * (fga + 0.44 * fta)
            makes = pts / 2
            ts_bayes = shrink_shooting(makes, attempts / 2, league_mean=LEAGUE_AVG_TS / 2)
            df["TS_POSTERIOR"] = (ts_bayes["posterior_mean"] * 2).values
            df["TS_CI_LOW"] = (ts_bayes["ci_low_90"] * 2).values
            df["TS_CI_HIGH"] = (ts_bayes["ci_high_90"] * 2).values
        else:
            df["TS_POSTERIOR"] = pd.to_numeric(df.get("TS%"), errors="coerce")
            df["TS_CI_LOW"] = df["TS_POSTERIOR"]
            df["TS_CI_HIGH"] = df["TS_POSTERIOR"]

        sort_actual = "NET_RTG" if sort_col == "NET_RTG" else sort_col
        df = df.sort_values(sort_actual, ascending=False, na_position="last").head(50)

        if sort_col == "WS":
            fig = _win_shares_chart(df)
        elif sort_col == "TS_POSTERIOR":
            fig = _ts_chart(df)
        elif sort_col in ("USG%",):
            fig = _usage_efficiency_chart(df)
        else:
            fig = _generic_bar_chart(df, sort_actual)

        table = _summary_table(df)
        return fig, table

    # ── Player view ───────────────────────────────────────────────────────────
    @app.callback(
        Output("player-ts-chart", "figure"),
        Output("player-usage-chart", "figure"),
        Output("player-trend-chart", "figure"),
        Input("player-select", "value"),
    )
    def update_player(player_key):
        if not player_key:
            raise PreventUpdate
        name, team = player_key.split("|", 1)

        adv = _load_advanced()
        tot = _load_totals()

        if adv.empty:
            raise PreventUpdate

        player_adv = adv[(adv["Player"] == name) & (adv["Team"] == team)]
        player_tot = tot[(tot["Player"] == name) & (tot["Team"] == team)] if not tot.empty else pd.DataFrame()

        ts_fig = _player_ts_gauge(player_adv, name)
        usage_fig = _player_usage_chart(player_adv, name, adv)
        profile_fig = _player_profile_chart(player_adv, player_tot, name)
        return ts_fig, usage_fig, profile_fig

    # ── Team view ─────────────────────────────────────────────────────────────
    @app.callback(Output("team-onoff-chart", "figure"), Input("team-select", "value"))
    def update_team(team):
        if not team:
            raise PreventUpdate
        adv = _load_advanced()
        if adv.empty:
            return _empty_fig("No data available.")

        df = adv[(adv["Team"] == team) & (adv["G"] >= 3)].copy()
        df = df.sort_values("WS", ascending=True)

        # On/Off differential: ORtg - DRtg = net rating; compare to team average
        df["NET_RTG"] = pd.to_numeric(df["ORtg"], errors="coerce") - pd.to_numeric(df["DRtg"], errors="coerce")
        team_avg_net = df["NET_RTG"].mean()
        df["NET_VS_TEAM"] = df["NET_RTG"] - team_avg_net

        return _net_rtg_chart(df, team)


# ── Chart builders ────────────────────────────────────────────────────────────

def _add_team_logos(fig: go.Figure, df: pd.DataFrame) -> go.Figure:
    """
    Place a small team logo to the left of each player name on the y-axis.
    Works for both horizontal bar and scatter charts with categorical y-axis.
    Players in df must be in the same order as plotted (top-to-bottom = last-to-first in df).
    """
    n = len(df)
    for i, (_, row) in enumerate(df.iterrows()):
        logo_url = TEAM_LOGOS.get(row.get("Team", ""))
        if not logo_url:
            continue
        # Plotly categorical y: df.iloc[0] renders at the bottom (y=0),
        # df.iloc[n-1] renders at the top (y=n-1). We flip so best player is at top.
        y_pos = n - 1 - i
        fig.add_layout_image(
            source=logo_url,
            x=-0.005,
            y=y_pos,
            xref="paper",
            yref="y",
            sizex=0.045,
            sizey=0.7,
            xanchor="right",
            yanchor="middle",
            layer="above",
        )
    fig.update_layout(margin=dict(l=200))
    return fig


def _empty_fig(msg: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=msg, xref="paper", yref="paper", x=0.5, y=0.5,
                       showarrow=False, font=dict(size=16))
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)")
    return fig


def _win_shares_chart(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df["WS"], y=df["Player"], orientation="h",
        marker_color=BLUE,
        customdata=df[["Team", "G"]],
        hovertemplate="<b>%{y}</b><br>%{customdata[0]} · %{customdata[1]} GP<br>Win Shares: %{x:.1f}<extra></extra>",
    ))
    fig.update_layout(
        title="Win Shares — Top 50",
        xaxis_title="Win Shares",
        template="plotly_dark", height=900, margin=dict(l=160),
    )
    _add_team_logos(fig, df)
    return fig


def _ts_chart(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["TS_POSTERIOR"], y=df["Player"],
        mode="markers",
        marker=dict(color=BLUE, size=10),
        error_x=dict(
            type="data", symmetric=False,
            array=(df["TS_CI_HIGH"] - df["TS_POSTERIOR"]).values,
            arrayminus=(df["TS_POSTERIOR"] - df["TS_CI_LOW"]).values,
            color=GRAY,
        ),
        hovertemplate="<b>%{y}</b><br>Posterior TS%: %{x:.1%}<extra></extra>",
    ))
    fig.add_vline(x=LEAGUE_AVG_TS, line_dash="dash", line_color=GOLD,
                  annotation_text="League avg", annotation_position="top right")
    fig.update_layout(
        title="True Shooting % — Bayesian Posterior with 90% CI",
        xaxis_title="TS%", xaxis_tickformat=".0%",
        template="plotly_dark", height=900, margin=dict(l=160),
    )
    _add_team_logos(fig, df)
    return fig


def _generic_bar_chart(df: pd.DataFrame, col: str) -> go.Figure:
    labels = {
        "WS/40": "Win Shares per 40 min",
        "PER": "Player Efficiency Rating",
        "ORtg": "Offensive Rating (pts/100 poss)",
        "NET_RTG": "Net Rating (ORtg − DRtg)",
    }
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df[col], y=df["Player"], orientation="h",
        marker_color=BLUE,
        customdata=df[["Team", "G"]],
        hovertemplate="<b>%{y}</b><br>%{customdata[0]} · %{customdata[1]} GP<br>" + labels.get(col, col) + ": %{x:.2f}<extra></extra>",
    ))
    fig.update_layout(
        title=f"Top 50 — {labels.get(col, col)}",
        xaxis_title=labels.get(col, col),
        template="plotly_dark", height=900, margin=dict(l=160),
    )
    _add_team_logos(fig, df)
    return fig


def _usage_efficiency_chart(df: pd.DataFrame) -> go.Figure:
    fig = px.scatter(
        df, x="USG%", y="TS_POSTERIOR",
        text="Player", color="WS",
        color_continuous_scale="Blues",
        labels={"USG%": "Usage Rate %", "TS_POSTERIOR": "True Shooting %", "WS": "Win Shares"},
        title="Usage vs Efficiency (size = Win Shares)",
        size="WS", size_max=20,
        hover_data=["Team", "G", "WS"],
    )
    fig.add_hline(y=LEAGUE_AVG_TS, line_dash="dash", line_color=GOLD)
    fig.update_traces(textposition="top center", textfont_size=9)
    fig.update_layout(template="plotly_dark", height=600, yaxis_tickformat=".0%")
    return fig


def _net_rtg_chart(df: pd.DataFrame, team: str) -> go.Figure:
    colors = [GOLD if v > 0 else BLUE for v in df["NET_VS_TEAM"]]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df["NET_VS_TEAM"], y=df["Player"], orientation="h",
        marker_color=colors,
        customdata=df[["NET_RTG", "WS", "USG%"]],
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Net Rtg: %{customdata[0]:+.1f}<br>"
            "vs Team avg: %{x:+.1f}<br>"
            "Win Shares: %{customdata[1]:.1f} · USG%: %{customdata[2]:.1f}<extra></extra>"
        ),
    ))
    fig.add_vline(x=0, line_color=GRAY, line_dash="dot")
    fig.update_layout(
        title=f"{team} — Net Rating vs Team Average (gold = above average)",
        xaxis_title="Net Rating vs Team Avg (pts/100 poss)",
        template="plotly_dark", height=500, margin=dict(l=160),
    )
    _add_team_logos(fig, df)
    return fig


def _player_ts_gauge(player_adv: pd.DataFrame, name: str) -> go.Figure:
    if player_adv.empty:
        return _empty_fig("No data for this player.")
    ts = float(pd.to_numeric(player_adv["TS%"].iloc[0], errors="coerce") or 0)
    g = int(pd.to_numeric(player_adv["G"].iloc[0], errors="coerce") or 0)

    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=ts * 100,
        delta={"reference": LEAGUE_AVG_TS * 100, "suffix": "%"},
        title={"text": f"{name}<br><sup>True Shooting % ({g} GP)</sup>"},
        gauge={
            "axis": {"range": [30, 80]},
            "bar": {"color": BLUE},
            "threshold": {
                "line": {"color": GOLD, "width": 3},
                "thickness": 0.75,
                "value": LEAGUE_AVG_TS * 100,
            },
        },
        number={"suffix": "%"},
    ))
    fig.update_layout(template="plotly_dark", height=300)
    return fig


def _player_usage_chart(player_adv: pd.DataFrame, name: str, all_adv: pd.DataFrame) -> go.Figure:
    """Player's usage vs efficiency relative to the full league."""
    fig = px.scatter(
        all_adv[all_adv["G"] >= 5], x="USG%", y="TS%",
        opacity=0.3, color_discrete_sequence=[GRAY],
        labels={"USG%": "Usage %", "TS%": "True Shooting %"},
        title=f"{name} — Usage vs Efficiency (vs league)",
    )
    if not player_adv.empty:
        fig.add_trace(go.Scatter(
            x=pd.to_numeric(player_adv["USG%"], errors="coerce"),
            y=pd.to_numeric(player_adv["TS%"], errors="coerce"),
            mode="markers+text",
            marker=dict(color=GOLD, size=16, symbol="star"),
            text=[name], textposition="top center",
            name=name,
        ))
    fig.update_layout(template="plotly_dark", yaxis_tickformat=".0%")
    return fig


def _player_profile_chart(player_adv: pd.DataFrame, player_tot: pd.DataFrame, name: str) -> go.Figure:
    """Radar-style bar chart of key advanced metrics, percentile-ranked in league."""
    if player_adv.empty:
        return _empty_fig("No data.")

    row = player_adv.iloc[0]
    metrics = {
        "PER": ("PER", 15),
        "TS%": ("TS%", LEAGUE_AVG_TS),
        "USG%": ("USG%", 20),
        "Win Shares": ("WS", 1),
        "WS/40": ("WS/40", 0.05),
    }

    names, values, baselines = [], [], []
    for label, (col, baseline) in metrics.items():
        v = pd.to_numeric(row.get(col), errors="coerce")
        if pd.notna(v):
            names.append(label)
            values.append(float(v))
            baselines.append(baseline)

    colors = [GOLD if v >= b else BLUE for v, b in zip(values, baselines)]
    fig = go.Figure(go.Bar(
        x=names, y=values, marker_color=colors,
        hovertemplate="%{x}: %{y:.3f}<extra></extra>",
    ))
    fig.update_layout(
        title=f"{name} — Key Metrics (gold = above baseline)",
        template="plotly_dark", height=350,
    )
    return fig


def _summary_table(df: pd.DataFrame):
    cols = ["Player", "Team", "G", "WS", "WS/40", "TS_POSTERIOR", "USG%", "PER", "ORtg", "DRtg", "NET_RTG", "OWS", "DWS"]
    display = df[[c for c in cols if c in df.columns]].copy()
    display = display.rename(columns={
        "TS_POSTERIOR": "TS% (Bayes)",
        "NET_RTG": "Net Rtg",
        "WS/40": "WS/40",
    })
    for c in display.select_dtypes("float").columns:
        display[c] = display[c].round(3)

    return dash_table.DataTable(
        data=display.to_dict("records"),
        columns=[{"name": c, "id": c} for c in display.columns],
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_header={"backgroundColor": "#1e2130", "color": "white", "fontWeight": "bold"},
        style_data={"backgroundColor": "#13161f", "color": "white"},
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": "#181b28"}
        ],
        page_size=20,
    )
