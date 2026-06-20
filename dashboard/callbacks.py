import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from dash import Input, Output, dash_table
from dash.exceptions import PreventUpdate

from data.store import load
from data.teams import TEAM_COLORS, TEAM_NAMES

GOLD = "#f5a623"
BLUE = "#4a90d9"
GRAY = "#aaaaaa"

STAT_LABELS = {
    "PTS": "Points per Game",
    "TRB": "Rebounds per Game",
    "AST": "Assists per Game",
    "STL": "Steals per Game",
    "BLK": "Blocks per Game",
    "TOV": "Turnovers per Game",
    "MP": "Minutes per Game",
    "FG%": "Field Goal %",
    "3P%": "3-Point %",
    "FT%": "Free Throw %",
}

PCT_STATS = {"FG%", "3P%", "FT%"}

STAT_COLS = list(STAT_LABELS.keys())


def _load_per_game() -> pd.DataFrame:
    df = load("player_per_game")
    if df.empty:
        return df
    for col in STAT_COLS + ["G", "GS"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


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
        df = _load_per_game()
        if df.empty:
            return _empty_fig("No data yet — run the nightly refresh."), ""

        df = df[df["G"] >= min_gp].copy()
        df = df.sort_values(sort_col, ascending=True, na_position="first").tail(50)

        fig = _bar_chart(df, sort_col)
        table = _summary_table(df)
        return fig, table

    # ── Player view ───────────────────────────────────────────────────────────
    @app.callback(
        Output("player-ts-chart", "figure"),
        Output("player-usage-chart", "figure"),
        Output("player-trend-chart", "figure"),
        Output("player-split-summary", "children"),
        Input("player-select", "value"),
        Input("player-split", "value"),
    )
    def update_player(player_key, split):
        if not player_key:
            raise PreventUpdate
        name, team = player_key.split("|", 1)
        pg = _load_per_game()
        if pg.empty:
            raise PreventUpdate

        player_row = pg[(pg["Player"] == name) & (pg["Team"] == team)]
        league = pg[pg["G"] >= 5]

        # Load game logs and apply split filter
        gamelogs = load("player_gamelogs")
        player_logs = _filter_gamelogs(gamelogs, name, split)

        bar_fig = _player_bar(player_row, player_logs, name, team, split)
        shooting_fig = _player_shooting(player_row, name, league)
        context_fig = _player_context(player_row, name, league)
        summary = _split_summary(player_row, player_logs, name, split)
        return bar_fig, shooting_fig, context_fig, summary

    # ── Team view ─────────────────────────────────────────────────────────────
    @app.callback(Output("team-onoff-chart", "figure"), Input("team-select", "value"))
    def update_team(team):
        if not team:
            raise PreventUpdate
        df = _load_per_game()
        if df.empty:
            return _empty_fig("No data available.")

        roster = df[(df["Team"] == team) & (df["G"] >= 3)].copy()
        roster = roster.sort_values("MP", ascending=True)
        return _team_chart(roster, team)


# ── Chart builders ────────────────────────────────────────────────────────────

def _empty_fig(msg: str) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=msg, xref="paper", yref="paper", x=0.5, y=0.5,
                       showarrow=False, font=dict(size=16))
    fig.update_layout(template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)")
    return fig


def _fmt(col: str, val: float) -> str:
    if col in PCT_STATS:
        return f"{val:.1%}"
    return f"{val:.1f}"


def _bar_chart(df: pd.DataFrame, col: str) -> go.Figure:
    label = STAT_LABELS.get(col, col)
    colors = [TEAM_COLORS.get(t, BLUE) for t in df["Team"]]
    hovers = [
        f"<b>{row['Player']}</b> · {row['Team']}<br>{int(row['G'])} GP · {label}: {_fmt(col, row[col])}"
        for _, row in df.iterrows()
    ]
    tick_fmt = ".0%" if col in PCT_STATS else ""
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df[col], y=df["Player"], orientation="h",
        marker_color=colors,
        hovertext=hovers,
        hovertemplate="%{hovertext}<extra></extra>",
    ))
    fig.update_layout(
        title=f"Top 50 — {label}",
        xaxis_title=label,
        xaxis_tickformat=tick_fmt,
        template="plotly_dark", height=900, margin=dict(l=160),
    )
    return fig


def _team_win_pcts() -> dict[str, float]:
    """Returns {team_abbrev: win_pct} from standings, or empty dict if not available."""
    standings = load("team_standings")
    if standings.empty:
        return {}
    result = {}
    for _, row in standings.iterrows():
        team = str(row.get("Tm", row.get("Team", ""))).strip()
        w = pd.to_numeric(row.get("W"), errors="coerce")
        l = pd.to_numeric(row.get("L"), errors="coerce")
        if pd.notna(w) and pd.notna(l) and (w + l) > 0:
            result[team] = w / (w + l)
    return result


def _filter_gamelogs(gamelogs: pd.DataFrame, player_name: str, split: str) -> pd.DataFrame:
    """Returns game log rows for this player, filtered by split."""
    if gamelogs.empty:
        return pd.DataFrame()

    df = gamelogs[gamelogs["Player"] == player_name].copy()
    if df.empty:
        return df

    for col in ["PTS", "TRB", "AST", "STL", "BLK", "TOV", "MP", "FG%", "3P%", "FT%"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if split == "home":
        df = df[df.get("HomeAway", pd.Series(["Home"] * len(df))) == "Home"]
    elif split == "away":
        df = df[df.get("HomeAway", pd.Series(["Away"] * len(df))) == "Away"]
    elif split in ("above500", "below500"):
        win_pcts = _team_win_pcts()
        if win_pcts and "Opp" in df.columns:
            df["opp_wpct"] = df["Opp"].map(win_pcts)
            if split == "above500":
                df = df[df["opp_wpct"] > 0.5]
            else:
                df = df[df["opp_wpct"] <= 0.5]

    return df


def _split_label(split: str) -> str:
    return {
        "all": "All games",
        "above500": "vs. teams above .500",
        "below500": "vs. teams below .500",
        "home": "Home games",
        "away": "Away games",
    }.get(split, split)


def _split_summary(player_row: pd.DataFrame, player_logs: pd.DataFrame,
                   name: str, split: str) -> object:
    """Stat summary card comparing overall averages vs. the selected split."""
    from dash import html
    import dash_bootstrap_components as dbc

    if player_row.empty:
        return ""

    overall = player_row.iloc[0]
    cols = ["PTS", "TRB", "AST", "STL", "BLK", "TOV"]

    if player_logs.empty or split == "all":
        return ""

    n = len(player_logs)
    rows = []
    for col in cols:
        overall_val = pd.to_numeric(overall.get(col), errors="coerce")
        split_val = player_logs[col].mean() if col in player_logs.columns else float("nan")
        if pd.isna(overall_val) or pd.isna(split_val):
            continue
        diff = split_val - overall_val
        color = "success" if (col != "TOV" and diff > 0) or (col == "TOV" and diff < 0) else "danger"
        rows.append(
            dbc.Col([
                html.Div(col, className="text-muted small"),
                html.Div(f"{split_val:.1f}", className="fs-5 fw-bold"),
                html.Div(f"{'▲' if diff > 0 else '▼'} {abs(diff):.1f} vs. season avg",
                         className=f"text-{color} small"),
            ], className="text-center border-end pe-3 me-3")
        )

    if not rows:
        return ""

    return dbc.Card(dbc.CardBody([
        html.Div(f"{name} — {_split_label(split)} ({n} games)", className="fw-bold mb-2"),
        dbc.Row(rows),
    ]), className="mb-3 bg-dark border-secondary")


def _player_bar(player_row: pd.DataFrame, player_logs: pd.DataFrame,
                name: str, team: str, split: str = "all") -> go.Figure:
    if player_row.empty:
        return _empty_fig("No data for this player.")
    row = player_row.iloc[0]
    counting = ["PTS", "TRB", "AST", "STL", "BLK", "TOV", "MP"]
    season_vals = [float(pd.to_numeric(row.get(c), errors="coerce") or 0) for c in counting]
    color = TEAM_COLORS.get(team, BLUE)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Season avg", x=counting, y=season_vals,
        marker_color=color, opacity=0.5 if (split != "all" and not player_logs.empty) else 1.0,
        hovertemplate="%{x}: %{y:.1f}<extra>Season avg</extra>",
    ))

    if split != "all" and not player_logs.empty:
        split_vals = [player_logs[c].mean() if c in player_logs.columns else 0 for c in counting]
        fig.add_trace(go.Bar(
            name=_split_label(split), x=counting, y=split_vals,
            marker_color=color,
            hovertemplate="%{x}: %{y:.1f}<extra>" + _split_label(split) + "</extra>",
        ))

    title = f"{name} — Per-Game Stats"
    if split != "all" and not player_logs.empty:
        title += f" ({_split_label(split)}, n={len(player_logs)})"

    fig.update_layout(
        title=title, barmode="group",
        template="plotly_dark", height=320,
    )
    return fig


def _player_shooting(player_row: pd.DataFrame, name: str, league: pd.DataFrame) -> go.Figure:
    """Player shooting splits vs league averages."""
    if player_row.empty:
        return _empty_fig("No data.")
    row = player_row.iloc[0]
    cats = ["FG%", "3P%", "FT%"]
    player_vals = [float(pd.to_numeric(row.get(c), errors="coerce") or 0) for c in cats]
    league_vals = [league[c].mean() for c in cats]

    fig = go.Figure()
    fig.add_trace(go.Bar(name=name, x=cats, y=player_vals,
                         marker_color=TEAM_COLORS.get(str(row.get("Team", "")), BLUE),
                         hovertemplate="%{x}: %{y:.1%}<extra></extra>"))
    fig.add_trace(go.Bar(name="League avg", x=cats, y=league_vals,
                         marker_color=GRAY,
                         hovertemplate="%{x}: %{y:.1%}<extra></extra>"))
    fig.update_layout(
        title=f"{name} — Shooting Splits vs League Average",
        barmode="group", yaxis_tickformat=".0%",
        template="plotly_dark", height=300,
    )
    return fig


def _player_context(player_row: pd.DataFrame, name: str, league: pd.DataFrame) -> go.Figure:
    """Where the player ranks in the league for each counting stat."""
    if player_row.empty:
        return _empty_fig("No data.")
    row = player_row.iloc[0]
    cats = ["PTS", "TRB", "AST", "STL", "BLK"]
    pcts = []
    for c in cats:
        val = pd.to_numeric(row.get(c), errors="coerce")
        if pd.isna(val):
            pcts.append(0.0)
        else:
            pcts.append(float((league[c] <= val).mean()))

    color = TEAM_COLORS.get(str(row.get("Team", "")), BLUE)
    fig = go.Figure(go.Bar(
        x=cats, y=pcts,
        marker_color=color,
        hovertemplate="%{x}: %{y:.0%} percentile<extra></extra>",
    ))
    fig.add_hline(y=0.5, line_dash="dash", line_color=GOLD, annotation_text="Median")
    fig.update_layout(
        title=f"{name} — League Percentile Rank",
        yaxis_tickformat=".0%", yaxis_range=[0, 1],
        template="plotly_dark", height=300,
    )
    return fig


def _team_chart(roster: pd.DataFrame, team: str) -> go.Figure:
    color = TEAM_COLORS.get(team, BLUE)
    hovers = [
        f"<b>{row['Player']}</b><br>{int(row['G'])} GP · {row['MP']:.1f} MPG<br>PTS: {row['PTS']:.1f} · REB: {row['TRB']:.1f} · AST: {row['AST']:.1f}"
        for _, row in roster.iterrows()
    ]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=roster["PTS"], y=roster["Player"], orientation="h",
        marker_color=color,
        hovertext=hovers,
        hovertemplate="%{hovertext}<extra></extra>",
    ))
    fig.update_layout(
        title=f"{team} — Points per Game by Player",
        xaxis_title="Points per Game",
        template="plotly_dark", height=500, margin=dict(l=160),
    )
    return fig


def _summary_table(df: pd.DataFrame):
    cols = ["Player", "Team", "G", "MP", "PTS", "TRB", "AST", "STL", "BLK", "TOV", "FG%", "3P%", "FT%"]
    display = df[[c for c in cols if c in df.columns]].copy()
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
