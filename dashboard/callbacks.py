import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from dash import Input, Output, callback, dash_table
from dash.exceptions import PreventUpdate

from data.store import load
from stats.bayesian import shrink_ts
from stats.on_off import compute_on_off_deltas

GOLD = "#f5a623"
BLUE = "#4a90d9"
GRAY = "#aaaaaa"


def _load_player_agg() -> pd.DataFrame:
    return load("player_agg")


def _load_on_off() -> pd.DataFrame:
    raw = load("on_off_raw")
    if raw.empty:
        return pd.DataFrame()
    return compute_on_off_deltas(raw)


def _load_win_shares() -> pd.DataFrame:
    return load("win_shares")


def _load_game_logs() -> pd.DataFrame:
    return load("player_game_logs")


def register_callbacks(app) -> None:

    # ── Routing ──────────────────────────────────────────────────────────────
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
        ws = _load_win_shares()
        agg = _load_player_agg()
        on_off = _load_on_off()

        if ws.empty or agg.empty:
            return _empty_fig("No data yet — run the nightly refresh."), ""

        # Merge win shares with on/off delta
        df = ws.merge(agg[["PLAYER_ID", "GP", "FGA", "FTA", "PTS", "TOV"]], on="PLAYER_ID", how="left")
        if not on_off.empty:
            df = df.merge(on_off[["PLAYER_ID", "DELTA", "DELTA_CI_LOW", "DELTA_CI_HIGH"]],
                          on="PLAYER_ID", how="left")

        # Bayesian TS%
        ts = shrink_ts(df["PTS"], df["FGA"], df["FTA"])
        df["TS_POSTERIOR"] = ts["posterior_mean"]
        df["TS_CI_LOW"] = ts["ci_low_90"]
        df["TS_CI_HIGH"] = ts["ci_high_90"]

        df = df[df["GP"] >= min_gp].sort_values(sort_col, ascending=False).head(30)

        if sort_col == "WIN_SHARES":
            fig = _win_shares_chart(df)
        elif sort_col == "TS_POSTERIOR":
            fig = _ts_chart(df)
        else:
            fig = _on_off_league_chart(df)

        table = _summary_table(df)
        return fig, table

    # ── Player view ───────────────────────────────────────────────────────────
    @app.callback(Output("player-select", "options"), Input("url", "pathname"))
    def populate_player_dropdown(_):
        agg = _load_player_agg()
        if agg.empty:
            return []
        return [{"label": f"{r['PLAYER_NAME']} ({r['TEAM_ABBREVIATION']})",
                 "value": r["PLAYER_ID"]}
                for _, r in agg.iterrows()]

    @app.callback(
        Output("player-ts-chart", "figure"),
        Output("player-usage-chart", "figure"),
        Output("player-trend-chart", "figure"),
        Input("player-select", "value"),
    )
    def update_player(player_id):
        if not player_id:
            raise PreventUpdate
        logs = _load_game_logs()
        if logs.empty:
            raise PreventUpdate

        player_logs = logs[logs["PLAYER_ID"] == player_id].copy()
        player_logs = player_logs.sort_values("GAME_DATE")
        name = player_logs["PLAYER_NAME"].iloc[0] if len(player_logs) else "Player"

        # Cumulative Bayesian TS% with shrinking CI
        ts_fig = _cumulative_ts_chart(player_logs, name)
        usage_fig = _usage_scatter(player_logs, name)
        trend_fig = _pts_trend(player_logs, name)
        return ts_fig, usage_fig, trend_fig

    # ── Team view ─────────────────────────────────────────────────────────────
    @app.callback(Output("team-select", "options"), Input("url", "pathname"))
    def populate_team_dropdown(_):
        on_off = _load_on_off()
        if on_off.empty:
            return []
        teams = sorted(on_off["TEAM_ABBREVIATION"].dropna().unique())
        return [{"label": t, "value": t} for t in teams]

    @app.callback(Output("team-onoff-chart", "figure"), Input("team-select", "value"))
    def update_team(team):
        if not team:
            raise PreventUpdate
        on_off = _load_on_off()
        if on_off.empty:
            return _empty_fig("No on/off data available.")
        df = on_off[on_off["TEAM_ABBREVIATION"] == team].sort_values("DELTA", ascending=True)
        return _on_off_team_chart(df, team)


# ── Chart builders ────────────────────────────────────────────────────────────

def _empty_fig(msg: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=msg, xref="paper", yref="paper", x=0.5, y=0.5,
                       showarrow=False, font=dict(size=16))
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)")
    return fig


def _win_shares_chart(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df["WIN_SHARES"], y=df["PLAYER_NAME"], orientation="h",
        marker_color=BLUE,
        customdata=df[["TEAM_ABBREVIATION", "GP"]],
        hovertemplate="<b>%{y}</b><br>%{customdata[0]} · %{customdata[1]} GP<br>Win Shares: %{x:.2f}<extra></extra>",
    ))
    fig.update_layout(
        title="Win Shares (Top 30)",
        xaxis_title="Win Shares",
        template="plotly_dark",
        height=700,
        margin=dict(l=160),
    )
    return fig


def _ts_chart(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["TS_POSTERIOR"], y=df["PLAYER_NAME"],
        mode="markers",
        marker=dict(color=BLUE, size=10),
        error_x=dict(
            type="data",
            symmetric=False,
            array=(df["TS_CI_HIGH"] - df["TS_POSTERIOR"]).values,
            arrayminus=(df["TS_POSTERIOR"] - df["TS_CI_LOW"]).values,
            color=GRAY,
        ),
        hovertemplate="<b>%{y}</b><br>Posterior TS%: %{x:.1%}<extra></extra>",
    ))
    fig.add_vline(x=0.545, line_dash="dash", line_color=GOLD,
                  annotation_text="League avg", annotation_position="top right")
    fig.update_layout(
        title="True Shooting % — Bayesian Posterior with 90% CI",
        xaxis_title="TS% (posterior mean)",
        xaxis_tickformat=".0%",
        template="plotly_dark",
        height=700,
        margin=dict(l=160),
    )
    return fig


def _on_off_league_chart(df: pd.DataFrame) -> go.Figure:
    colors = [GOLD if s else BLUE for s in df.get("SIGNAL", [False] * len(df))]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df["DELTA"], y=df["PLAYER_NAME"], orientation="h",
        marker_color=colors,
        error_x=dict(
            type="data", symmetric=False,
            array=(df["DELTA_CI_HIGH"] - df["DELTA"]).values,
            arrayminus=(df["DELTA"] - df["DELTA_CI_LOW"]).values,
            color=GRAY,
        ),
        hovertemplate="<b>%{y}</b><br>On/Off Delta: %{x:+.1f}<extra></extra>",
    ))
    fig.add_vline(x=0, line_color=GRAY, line_dash="dot")
    fig.update_layout(
        title="On/Off Net Rating Delta with 90% CI (gold = statistically meaningful)",
        xaxis_title="Net Rating Delta (pts/100 poss)",
        template="plotly_dark", height=700, margin=dict(l=160),
    )
    return fig


def _on_off_team_chart(df: pd.DataFrame, team: str) -> go.Figure:
    colors = [GOLD if s else BLUE for s in df.get("SIGNAL", [False] * len(df))]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df["DELTA"], y=df["PLAYER_NAME"], orientation="h",
        marker_color=colors,
        error_x=dict(
            type="data", symmetric=False,
            array=(df["DELTA_CI_HIGH"] - df["DELTA"]).values,
            arrayminus=(df["DELTA"] - df["DELTA_CI_LOW"]).values,
            color=GRAY,
        ),
        hovertemplate="<b>%{y}</b><br>On: %{customdata[0]:+.1f} · Off: %{customdata[1]:+.1f}<br>Delta: %{x:+.1f}<extra></extra>",
        customdata=df[["NET_ON", "NET_OFF"]].values,
    ))
    fig.add_vline(x=0, line_color=GRAY, line_dash="dot")
    fig.update_layout(
        title=f"{team} — On/Off Net Rating Delta",
        xaxis_title="Net Rating Delta (pts/100 poss)",
        template="plotly_dark", height=500, margin=dict(l=160),
    )
    return fig


def _cumulative_ts_chart(logs: pd.DataFrame, name: str) -> go.Figure:
    """Rolling cumulative Bayesian TS% as the season progresses."""
    pts = pd.to_numeric(logs["PTS"], errors="coerce").fillna(0).cumsum()
    fga = pd.to_numeric(logs["FGA"], errors="coerce").fillna(0).cumsum()
    fta = pd.to_numeric(logs["FTA"], errors="coerce").fillna(0).cumsum()

    from stats.bayesian import shrink_ts
    ts = shrink_ts(pts, fga, fta)

    dates = logs["GAME_DATE"].values
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dates, y=ts["posterior_mean"], name="Posterior TS%",
                             line=dict(color=BLUE)))
    fig.add_trace(go.Scatter(x=dates, y=ts["ci_high_90"], name="90% CI high",
                             line=dict(color=GRAY, dash="dot"), showlegend=False))
    fig.add_trace(go.Scatter(x=dates, y=ts["ci_low_90"], name="90% CI",
                             fill="tonexty", fillcolor="rgba(74,144,217,0.15)",
                             line=dict(color=GRAY, dash="dot")))
    fig.add_hline(y=0.545, line_dash="dash", line_color=GOLD,
                  annotation_text="League avg")
    fig.update_layout(title=f"{name} — Cumulative TS% (Bayesian)",
                      yaxis_title="TS%", yaxis_tickformat=".0%",
                      template="plotly_dark")
    return fig


def _usage_scatter(logs: pd.DataFrame, name: str) -> go.Figure:
    logs = logs.copy()
    for c in ["PTS", "FGA", "FTA", "MIN", "TOV"]:
        logs[c] = pd.to_numeric(logs[c], errors="coerce").fillna(0)
    from stats.efficiency import true_shooting_pct
    logs["TS"] = true_shooting_pct(logs["PTS"], logs["FGA"], logs["FTA"])
    logs["PLAYS"] = logs["FGA"] + 0.44 * logs["FTA"] + logs["TOV"]
    fig = px.scatter(logs, x="PLAYS", y="TS", hover_data=["GAME_DATE"],
                     color_discrete_sequence=[BLUE],
                     labels={"PLAYS": "Plays Used", "TS": "True Shooting %"},
                     title=f"{name} — Usage vs Efficiency per game")
    fig.update_layout(template="plotly_dark", yaxis_tickformat=".0%")
    return fig


def _pts_trend(logs: pd.DataFrame, name: str) -> go.Figure:
    logs = logs.copy()
    logs["PTS"] = pd.to_numeric(logs["PTS"], errors="coerce").fillna(0)
    logs["ROLLING_PTS"] = logs["PTS"].rolling(5, min_periods=1).mean()
    fig = go.Figure()
    fig.add_trace(go.Bar(x=logs["GAME_DATE"], y=logs["PTS"], name="Points",
                         marker_color=GRAY))
    fig.add_trace(go.Scatter(x=logs["GAME_DATE"], y=logs["ROLLING_PTS"],
                             name="5-game avg", line=dict(color=GOLD, width=2)))
    fig.update_layout(title=f"{name} — Points per game", template="plotly_dark")
    return fig


def _summary_table(df: pd.DataFrame):
    from dash import dash_table
    cols = ["PLAYER_NAME", "TEAM_ABBREVIATION", "GP", "WIN_SHARES"]
    if "TS_POSTERIOR" in df.columns:
        cols += ["TS_POSTERIOR"]
    if "DELTA" in df.columns:
        cols += ["DELTA"]
    display = df[cols].copy()
    display.columns = [c.replace("_", " ").title() for c in cols]
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
