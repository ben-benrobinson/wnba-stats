import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import dash_bootstrap_components as dbc
from dash import Input, Output, dash_table, html
from dash.exceptions import PreventUpdate

from data.store import load
from data.teams import TEAM_COLORS, TEAM_LOGOS, TEAM_NAMES, clean_team_name, team_abbrev

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

    from dashboard.layout import standings_layout, playoffs_layout, league_layout, player_layout, team_layout, scatter_layout, game_scatter_layout, durability_layout

    @app.callback(Output("page-content", "children"), Input("url", "pathname"))
    def render_page(pathname):
        if pathname == "/playoffs":
            return playoffs_layout()
        if pathname == "/league":
            return league_layout()
        if pathname == "/player":
            return player_layout()
        if pathname == "/team":
            return team_layout()
        if pathname == "/scatter":
            return scatter_layout()
        if pathname == "/gamelog":
            return game_scatter_layout()
        if pathname == "/durability":
            return durability_layout()
        return standings_layout()

    # ── Data quality badge ────────────────────────────────────────────────────
    @app.callback(
        Output("data-quality-badge", "children"),
        Input("url", "pathname"),
    )
    def update_data_quality_badge(_pathname):
        from data.store import load_data_quality
        rec = load_data_quality()
        if rec is None:
            return ""
        ts = rec.get("run_timestamp", "")
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(ts).astimezone(timezone.utc)
            ts_fmt = dt.strftime("%-I:%M %p UTC, %b %-d")
        except Exception:
            ts_fmt = ts[:16]

        fatal = bool(rec.get("fatal"))
        issue_count = int(rec.get("issue_count", 0))
        action = rec.get("action_taken", "")

        if fatal:
            color, icon, msg = "danger", "⚠", f"Backup restored — serving previous data · Last attempted {ts_fmt}"
        elif issue_count:
            issues = rec.get("issues", [])
            tooltip = " · ".join(issues[:3]) + (" · …" if len(issues) > 3 else "")
            color, icon, msg = "warning", "⚠", f"{issue_count} data warning(s) · Last updated {ts_fmt}"
            return html.Small([
                dbc.Badge(f"{icon} {issue_count} data warning(s)", color=color, className="me-2"),
                html.Span(f"Last updated {ts_fmt}", className="text-muted"),
                html.Br(),
                html.Span(tooltip, className="text-muted", style={"fontSize": "0.8em"}),
            ])
        else:
            color, icon, msg = "success", "✓", f"All checks passed · Last updated {ts_fmt}"

        return html.Small([
            dbc.Badge(f"{icon} {msg}", color=color, className="me-2"),
        ])

    # ── Standings view ────────────────────────────────────────────────────────
    @app.callback(
        Output("standings-chart", "figure"),
        Output("standings-table", "children"),
        Output("standings-banner", "children"),
        Input("url", "pathname"),
    )
    def update_standings(pathname):
        if pathname not in ("/", None):
            raise PreventUpdate
        standings = load("team_standings")
        if standings.empty:
            empty = _empty_fig("No standings data yet — run the nightly refresh.")
            return empty, "", ""
        gamelogs = load("player_gamelogs")
        last10 = _compute_last10(gamelogs)
        series = load("playoff_series")
        chart = _standings_chart(standings)
        table = _standings_table(standings, last10, _postseason_status(series))
        banner = ""
        if _season_complete(standings):
            banner = dbc.Alert(
                ["Regular season complete — final standings. ",
                 html.A("See the playoff bracket →", href="/playoffs", className="alert-link")],
                color="info", className="py-2",
            )
        return chart, table, banner

    @app.callback(
        Output("standings-winpct-chart", "figure"),
        Input("url", "pathname"),
        Input("standings-team-filter", "value"),
    )
    def update_winpct_chart(pathname, selected_teams):
        if pathname not in ("/", None):
            raise PreventUpdate
        gamelogs = load("player_gamelogs")
        if gamelogs.empty:
            return _empty_fig("No game log data yet — run the nightly refresh.")
        return _winpct_trend_chart(gamelogs, selected_teams or [])

    # ── Playoffs view ─────────────────────────────────────────────────────────
    @app.callback(
        Output("playoffs-bracket", "children"),
        Output("playoffs-summary", "children"),
        Input("url", "pathname"),
    )
    def update_playoffs_bracket(pathname):
        if pathname != "/playoffs":
            raise PreventUpdate
        series = load("playoff_series")
        if series.empty:
            return dbc.Alert("No playoff data yet — the bracket appears once the postseason starts.",
                             color="secondary"), ""
        games = load("playoff_games")
        seeds = _playoff_seeds(load("team_standings"))
        summary = [html.Div(_playoff_summary(series)),
                   html.Small(_refresh_note(), style={"fontSize": "0.8em"})]
        return _playoff_bracket(series, games, seeds), summary

    @app.callback(
        Output("playoffs-leaders-chart", "figure"),
        Output("playoffs-leaders-table", "children"),
        Input("url", "pathname"),
        Input("playoffs-stat", "value"),
        Input("playoffs-alive-only", "value"),
    )
    def update_playoff_leaders(pathname, stat, alive_only):
        if pathname != "/playoffs":
            raise PreventUpdate
        logs = load("player_playoff_gamelogs")
        if logs.empty:
            return _empty_fig("No playoff game logs yet."), ""
        agg = _playoff_player_averages(logs)
        if alive_only:
            alive = _teams_alive(load("playoff_series"))
            if alive:
                agg = agg[agg["Team"].isin(alive)]
        stat = stat or "PTS"
        return _playoff_leaders_chart(agg, stat), _playoff_leaders_table(agg, stat)

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
        Output("player-ts-chart", "children"),
        Output("player-usage-chart", "figure"),
        Output("player-trend-chart", "figure"),
        Output("player-split-summary", "children"),
        Input("player-select", "value"),
        Input("player-split", "value"),
        Input("player-min-mp", "value"),
    )
    def update_player(player_key, split, min_mp):
        if not player_key:
            raise PreventUpdate
        name, team = player_key.split("|", 1)
        pg = _load_per_game()
        if pg.empty:
            raise PreventUpdate

        player_row = pg[(pg["Player"] == name) & (pg["Team"] == team)]
        league = pg[pg["G"] >= 5]
        percentile_pool = pg[pg["MP"] >= (min_mp or 0)]

        # Load game logs and apply split filter
        gamelogs = load("player_gamelogs")
        player_logs = _filter_gamelogs(gamelogs, name, split)

        bar_fig = _player_bar(player_row, player_logs, name, team, split)
        shooting_fig = _player_shooting(player_row, name, league)
        context_fig = _player_context(player_row, name, percentile_pool, min_mp or 0)
        summary = _split_summary(player_row, player_logs, name, split)
        return bar_fig, shooting_fig, context_fig, summary

    # ── Game log scatter ──────────────────────────────────────────────────────
    @app.callback(
        Output("gs-chart", "figure"),
        Input("gs-player", "value"),
        Input("gs-x", "value"),
        Input("gs-y", "value"),
    )
    def update_game_scatter(player_key, x_col, y_col):
        if not player_key or not x_col or not y_col:
            raise PreventUpdate
        name, team = player_key.split("|", 1)
        gamelogs = load("player_gamelogs")
        if gamelogs.empty:
            return _empty_fig("No game log data yet — run the nightly refresh.")
        df = gamelogs[gamelogs["Player"] == name].copy()
        if df.empty:
            return _empty_fig(f"No game log data found for {name}.")
        for col in STAT_COLS + ["Result"]:
            if col in df.columns and col != "Result":
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=[x_col, y_col, "Result"])
        if df.empty:
            return _empty_fig(f"No complete game records for {name} with {x_col} and {y_col}.")
        return _game_scatter_chart(df, name, team, x_col, y_col)

    # ── Scatter view ──────────────────────────────────────────────────────────
    @app.callback(
        Output("scatter-chart", "figure"),
        Input("scatter-x", "value"),
        Input("scatter-y", "value"),
        Input("scatter-quality-filter", "value"),
        Input("scatter-opp-select", "value"),
        Input("scatter-date-from", "date"),
        Input("scatter-min-gp", "value"),
        Input("scatter-team-filter", "value"),
    )
    def update_scatter(x_col, y_col, quality_filter, specific_opps, date_from, min_gp, team_filter):
        if not x_col or not y_col:
            raise PreventUpdate

        gamelogs = load("player_gamelogs")
        pg = _load_per_game()

        # If any game-log filter is active, aggregate from game logs
        use_gamelogs = (
            not gamelogs.empty
            and (specific_opps or (quality_filter and quality_filter != "all") or date_from)
        )

        if use_gamelogs:
            for col in STAT_COLS:
                if col in gamelogs.columns:
                    gamelogs[col] = pd.to_numeric(gamelogs[col], errors="coerce")

            filtered = gamelogs.copy()

            if specific_opps:
                filtered = filtered[filtered["Opp"].isin(specific_opps)]
            elif quality_filter and quality_filter != "all":
                if quality_filter in ("above500", "below500"):
                    win_pcts = _team_win_pcts()
                    if win_pcts and "Opp" in filtered.columns:
                        filtered["opp_wpct"] = filtered["Opp"].map(win_pcts)
                        filtered = filtered[filtered["opp_wpct"] > 0.5] if quality_filter == "above500" \
                            else filtered[filtered["opp_wpct"] <= 0.5]
                elif quality_filter == "home":
                    filtered = filtered[filtered.get("HomeAway", pd.Series()) == "Home"]
                elif quality_filter == "away":
                    filtered = filtered[filtered.get("HomeAway", pd.Series()) == "Away"]

            if date_from and "Date" in filtered.columns:
                filtered["_date"] = pd.to_datetime(filtered["Date"], errors="coerce")
                filtered = filtered[filtered["_date"] >= pd.to_datetime(date_from)]

            avg_cols = [c for c in STAT_COLS if c in filtered.columns]
            if filtered.empty or x_col not in avg_cols or y_col not in avg_cols:
                return _empty_fig("No data for this filter combination.")

            agg = filtered.groupby("Player")[avg_cols].mean().reset_index()
            # Attach team from per_game (take first non-TOT occurrence)
            team_map = (
                pg[pg["Team"] != "TOT"]
                .drop_duplicates("Player")[["Player", "Team"]]
            )
            agg = agg.merge(team_map, on="Player", how="left")
            # Game count filter
            gp = filtered.groupby("Player")["Date"].nunique().reset_index().rename(columns={"Date": "GP"})
            agg = agg.merge(gp, on="Player")
            agg = agg[agg["GP"] >= (min_gp or 1)]
            subtitle = _scatter_subtitle(quality_filter, specific_opps, date_from)
        else:
            # Use season averages
            if pg.empty:
                return _empty_fig("No data yet.")
            agg = pg[pg["Team"] != "TOT"].copy()
            if "G" in agg.columns:
                agg = agg[agg["G"] >= (min_gp or 1)]
            agg = agg.rename(columns={"G": "GP"})
            subtitle = "Season averages"

        if x_col not in agg.columns or y_col not in agg.columns:
            return _empty_fig(f"Missing column(s): {x_col}, {y_col}")

        if team_filter:
            agg = agg[agg["Team"].isin(team_filter)]
            if agg.empty:
                return _empty_fig(f"No data for selected team(s).")

        return _scatter_chart(agg, x_col, y_col, subtitle)

    # ── Team view ─────────────────────────────────────────────────────────────
    @app.callback(
        Output("team-opp-select", "options"),
        Input("team-select", "value"),
    )
    def populate_opp_options(team):
        if not team:
            return []
        gamelogs = load("player_gamelogs")
        if gamelogs.empty or "Opp" not in gamelogs.columns:
            return []
        opps = sorted(gamelogs[gamelogs["Tm"] == team]["Opp"].dropna().unique())
        return [{"label": o, "value": o} for o in opps]

    @app.callback(
        Output("team-onoff-chart", "figure"),
        Output("team-filter-summary", "children"),
        Input("team-select", "value"),
        Input("team-quality-filter", "value"),
        Input("team-opp-select", "value"),
        Input("team-date-from", "date"),
        Input("team-stat-select", "value"),
    )
    def update_team(team, quality_filter, specific_opps, date_from, stat_col):
        if not team:
            raise PreventUpdate
        stat_col = stat_col or "PTS"

        gamelogs = load("player_gamelogs")
        pg = _load_per_game()

        # Try game-log-based view first
        if not gamelogs.empty and "Tm" in gamelogs.columns:
            team_logs = gamelogs[gamelogs["Tm"] == team].copy()
            for col in ["PTS", "TRB", "AST", "STL", "BLK", "TOV", "MP", "FG%", "3P%", "FT%"]:
                if col in team_logs.columns:
                    team_logs[col] = pd.to_numeric(team_logs[col], errors="coerce")

            # Apply opponent filter — specific opponents take priority
            filtered = team_logs
            filter_parts = []
            if specific_opps:
                filtered = team_logs[team_logs["Opp"].isin(specific_opps)]
                filter_parts.append(f"vs. {', '.join(specific_opps)}")
            elif quality_filter and quality_filter != "all":
                if quality_filter in ("above500", "below500"):
                    win_pcts = _team_win_pcts()
                    if win_pcts and "Opp" in filtered.columns:
                        filtered = filtered.copy()
                        filtered["opp_wpct"] = filtered["Opp"].map(win_pcts)
                        filtered = filtered[filtered["opp_wpct"] > 0.5] if quality_filter == "above500" \
                            else filtered[filtered["opp_wpct"] <= 0.5]
                        filter_parts.append("vs. teams above .500" if quality_filter == "above500"
                                            else "vs. teams below .500")
                elif quality_filter == "home":
                    filtered = team_logs[team_logs.get("HomeAway", pd.Series()) == "Home"]
                    filter_parts.append("Home games")
                elif quality_filter == "away":
                    filtered = team_logs[team_logs.get("HomeAway", pd.Series()) == "Away"]
                    filter_parts.append("Away games")

            # Apply date filter
            if date_from and "Date" in filtered.columns:
                filtered = filtered.copy()
                filtered["_date"] = pd.to_datetime(filtered["Date"], errors="coerce")
                filtered = filtered[filtered["_date"] >= pd.to_datetime(date_from)]
                filter_parts.append(f"since {date_from}")

            filter_label = " · ".join(filter_parts) if filter_parts else "All games"
            n_games = filtered["Date"].nunique() if "Date" in filtered.columns else len(filtered) // 10
            record = _team_record(filtered, team)
            summary = _team_filter_summary(team, filter_label, n_games, quality_filter, specific_opps, record)

            if not filtered.empty:
                # Average per-game stats per player across filtered games
                avg_cols = [c for c in ["PTS", "TRB", "AST", "STL", "BLK", "TOV", "MP", "FG%", "3P%", "FT%"]
                           if c in filtered.columns]
                avg = filtered.groupby("Player")[avg_cols].mean().reset_index()
                # Add game count per player
                if "Date" in filtered.columns:
                    gp = filtered.groupby("Player")["Date"].nunique().reset_index()\
                        .rename(columns={"Date": "GP"})
                    avg = avg.merge(gp, on="Player")
                avg["Team"] = team

                # Fill in any roster players missing from gamelogs using per_game season averages
                if not pg.empty:
                    missing = pg[
                        (pg["Team"] == team) &
                        (~pg["Player"].isin(avg["Player"])) &
                        (pg["G"] >= 3)
                    ].copy()
                    if not missing.empty:
                        missing_avg = missing[["Player"] + [c for c in avg_cols if c in missing.columns]].copy()
                        missing_avg["GP"] = pd.to_numeric(missing["G"], errors="coerce")
                        missing_avg["Team"] = team
                        avg = pd.concat([avg, missing_avg], ignore_index=True)

                if stat_col in avg.columns:
                    avg = avg.sort_values(stat_col, ascending=True)
                    return _team_chart(avg, team, stat_col, filter_label), summary
                return _empty_fig(f"No {stat_col} data for this filter."), summary

        # Fallback: season averages from per_game table
        if pg.empty:
            return _empty_fig("No data available."), ""
        roster = pg[(pg["Team"] == team) & (pg["G"] >= 3)].copy()
        if stat_col not in roster.columns:
            return _empty_fig(f"No {stat_col} data available."), ""
        roster = roster.sort_values(stat_col, ascending=True)
        summary = html.Small("Game log data not yet available — showing season averages.",
                             className="text-muted")
        return _team_chart(roster, team, stat_col, "Season averages"), summary

    # ── Durability view ───────────────────────────────────────────────────────
    @app.callback(
        Output("dur-availability-chart", "figure"),
        Output("dur-impact-chart", "figure"),
        Input("dur-team-select", "value"),
    )
    def update_durability(team):
        if not team:
            raise PreventUpdate

        pg = _load_per_game()
        gamelogs = load("player_gamelogs")

        if pg.empty:
            empty = _empty_fig("No data yet — run the nightly refresh.")
            return empty, empty

        roster = pg[(pg["Team"] == team) & (pg["Team"] != "TOT")].copy()
        if roster.empty:
            empty = _empty_fig(f"No players found for {team}.")
            return empty, empty

        # Total team games = max G on the roster (most played player sets the ceiling)
        roster["G"] = pd.to_numeric(roster["G"], errors="coerce")
        team_games = int(roster["G"].max()) if not roster["G"].isna().all() else 0
        if team_games == 0:
            empty = _empty_fig("Insufficient games data.")
            return empty, empty

        roster["avail_pct"] = roster["G"] / team_games
        roster = roster.sort_values("avail_pct", ascending=True)

        avail_fig = _durability_availability_chart(roster, team, team_games)

        if gamelogs.empty or "Tm" not in gamelogs.columns:
            impact_fig = _empty_fig("Game log data not yet available — run the nightly refresh.")
            return avail_fig, impact_fig

        impact_fig = _durability_impact_chart(gamelogs, roster, team, team_games)
        return avail_fig, impact_fig


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
    # Standings uses full names; gamelogs use abbreviations
    result = {}
    for _, row in standings.iterrows():
        full_name = clean_team_name(row.get("Team", row.get("Tm", "")))
        abbrev = team_abbrev(full_name, full_name)
        wpct = pd.to_numeric(row.get("W/L%"), errors="coerce")
        if pd.isna(wpct):
            w = pd.to_numeric(row.get("W"), errors="coerce")
            l = pd.to_numeric(row.get("L"), errors="coerce")
            wpct = w / (w + l) if pd.notna(w) and pd.notna(l) and (w + l) > 0 else None
        if wpct is not None:
            result[abbrev] = float(wpct)
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
                name: str, team: str, split: str = "all") -> object:
    """Per-game stats table: season average, and the selected split if any."""
    if player_row.empty:
        return html.Div("No data for this player.", className="text-muted")

    row = player_row.iloc[0]
    counting = ["PTS", "TRB", "AST", "STL", "BLK", "TOV", "MP"]
    season_vals = {c: pd.to_numeric(row.get(c), errors="coerce") for c in counting}

    show_split = split != "all" and not player_logs.empty
    split_vals = {c: player_logs[c].mean() if c in player_logs.columns else float("nan")
                  for c in counting} if show_split else {}

    header_cells = [html.Th("Stat"), html.Th("Season Avg")]
    if show_split:
        header_cells.append(html.Th(_split_label(split)))

    rows = []
    for c in counting:
        cells = [html.Td(c), html.Td(f"{season_vals[c]:.1f}" if pd.notna(season_vals[c]) else "—")]
        if show_split:
            sv = split_vals.get(c)
            diff = sv - season_vals[c] if pd.notna(sv) and pd.notna(season_vals[c]) else None
            cell_content = f"{sv:.1f}" if pd.notna(sv) else "—"
            if diff is not None:
                color = "limegreen" if (c != "TOV" and diff > 0) or (c == "TOV" and diff < 0) else "tomato"
                arrow = "▲" if diff > 0 else "▼"
                cell_content = html.Span([
                    cell_content + " ",
                    html.Span(f"{arrow}{abs(diff):.1f}", style={"color": color, "fontSize": "0.85em"}),
                ])
            cells.append(html.Td(cell_content))
        rows.append(html.Tr(cells))

    title = f"{name} — Per-Game Stats"
    if show_split:
        title += f" ({_split_label(split)}, n={len(player_logs)})"

    table = dbc.Table(
        [html.Thead(html.Tr(header_cells)), html.Tbody(rows)],
        bordered=False, hover=True, dark=True, responsive=True, className="mt-2",
    )
    return html.Div([html.H5(title, className="mt-2"), table])


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


def _player_context(player_row: pd.DataFrame, name: str, league: pd.DataFrame, min_mp: float = 0) -> go.Figure:
    """Where the player ranks among the filtered league pool for each counting stat."""
    if player_row.empty:
        return _empty_fig("No data.")
    if league.empty:
        return _empty_fig(f"No players average {min_mp}+ minutes per game.")
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
    title = f"{name} — League Percentile Rank"
    if min_mp:
        title += f"<br><sup>vs. players averaging {min_mp}+ MPG (n={len(league)})</sup>"
    fig.update_layout(
        title=title,
        yaxis_tickformat=".0%", yaxis_range=[0, 1],
        template="plotly_dark", height=320,
    )
    return fig


def _team_record(filtered: pd.DataFrame, team: str) -> str | None:
    """W-L record for the team across the filtered games (one row per game per player)."""
    if filtered.empty or "Date" not in filtered.columns or "Result" not in filtered.columns:
        return None
    games = filtered.drop_duplicates(subset=["Date"])
    wins = int((games["Result"] == "W").sum())
    losses = int((games["Result"] == "L").sum())
    if wins + losses == 0:
        return None
    return f"{wins}-{losses}"


def _team_filter_summary(team: str, filter_label: str, n_games: int,
                          quality_filter: str, specific_opps: list, record: str | None = None) -> object:
    from dash import html
    import dash_bootstrap_components as dbc
    if filter_label == "All games":
        return ""
    games_text = f"{n_games} game{'s' if n_games != 1 else ''}"
    if record:
        games_text += f" ({record})"
    return dbc.Card(dbc.CardBody(
        html.Span([
            html.B(f"{TEAM_NAMES.get(team, team)}"),
            f" — {filter_label} · {games_text}",
        ])
    ), className="mb-2 bg-dark border-secondary")


def _team_chart(roster: pd.DataFrame, team: str, stat_col: str = "PTS", subtitle: str = "") -> go.Figure:
    color = TEAM_COLORS.get(team, BLUE)
    label = STAT_LABELS.get(stat_col, stat_col)
    gp_col = "GP" if "GP" in roster.columns else "G"
    hovers = []
    for _, row in roster.iterrows():
        gp = int(row[gp_col]) if gp_col in row and pd.notna(row[gp_col]) else "?"
        mp = f"{row['MP']:.1f}" if "MP" in row and pd.notna(row.get("MP")) else "—"
        stat_val = _fmt(stat_col, row[stat_col]) if pd.notna(row.get(stat_col)) else "—"
        hovers.append(
            f"<b>{row['Player']}</b><br>{gp} GP · {mp} MPG"
            f"<br>{label}: {stat_val}"
        )

    title = f"{TEAM_NAMES.get(team, team)} — {label} by Player"
    if subtitle and subtitle != "Season averages":
        title += f"<br><sup>{subtitle}</sup>"

    tick_fmt = ".0%" if stat_col in PCT_STATS else ""
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=roster[stat_col], y=roster["Player"], orientation="h",
        marker_color=color,
        hovertext=hovers,
        hovertemplate="%{hovertext}<extra></extra>",
    ))
    fig.update_layout(
        title=title,
        xaxis_title=label,
        xaxis_tickformat=tick_fmt,
        template="plotly_dark", height=500, margin=dict(l=160),
    )
    return fig


def _game_scatter_chart(df: pd.DataFrame, name: str, team: str, x_col: str, y_col: str) -> go.Figure:
    x_label = STAT_LABELS.get(x_col, x_col)
    y_label = STAT_LABELS.get(y_col, y_col)
    team_color = TEAM_COLORS.get(team, BLUE)

    wins = df[df["Result"] == "W"]
    losses = df[df["Result"] == "L"]

    def hover(row):
        date = row.get("Date", "")
        opp = row.get("Opp", "")
        home_away = row.get("HomeAway", "")
        loc = f"{'vs.' if home_away == 'Home' else '@'} {opp}" if opp else ""
        return (
            f"<b>{date} {loc}</b><br>"
            f"{x_label}: {_fmt(x_col, row[x_col])}<br>"
            f"{y_label}: {_fmt(y_col, row[y_col])}<br>"
            f"{'Win' if row['Result'] == 'W' else 'Loss'}"
        )

    fig = go.Figure()
    for result_df, label, color, symbol in [
        (wins, "Win", "#2ecc71", "circle"),
        (losses, "Loss", "#e74c3c", "circle"),
    ]:
        if result_df.empty:
            continue
        fig.add_trace(go.Scatter(
            x=result_df[x_col],
            y=result_df[y_col],
            mode="markers",
            name=label,
            marker=dict(
                color=color, size=12, opacity=0.85,
                line=dict(width=1, color="rgba(255,255,255,0.4)"),
                symbol=symbol,
            ),
            hovertext=[hover(row) for _, row in result_df.iterrows()],
            hovertemplate="%{hovertext}<extra></extra>",
        ))

    n_wins = len(wins)
    n_losses = len(losses)
    fig.update_layout(
        title=(
            f"{name} — {x_label} vs. {y_label} by Game"
            f"<br><sup style='color:{team_color}'>{team}</sup>"
            f"<sup>  ·  {n_wins}W – {n_losses}L in games with data</sup>"
        ),
        xaxis_title=x_label,
        yaxis_title=y_label,
        xaxis_tickformat=".0%" if x_col in PCT_STATS else "",
        yaxis_tickformat=".0%" if y_col in PCT_STATS else "",
        template="plotly_dark",
        height=560,
        legend=dict(title="Result", orientation="v"),
    )
    return fig


def _scatter_subtitle(quality_filter: str, specific_opps: list, date_from: str | None) -> str:
    parts = []
    if specific_opps:
        parts.append(f"vs. {', '.join(specific_opps)}")
    elif quality_filter and quality_filter != "all":
        parts.append({
            "above500": "vs. teams above .500",
            "below500": "vs. teams below .500",
            "home": "Home games",
            "away": "Away games",
        }.get(quality_filter, quality_filter))
    if date_from:
        parts.append(f"since {date_from}")
    return " · ".join(parts) if parts else "Filtered averages"


def _scatter_chart(df: pd.DataFrame, x_col: str, y_col: str, subtitle: str = "") -> go.Figure:
    x_label = STAT_LABELS.get(x_col, x_col)
    y_label = STAT_LABELS.get(y_col, y_col)
    x_fmt = ".0%" if x_col in PCT_STATS else ".1f"
    y_fmt = ".0%" if y_col in PCT_STATS else ".1f"

    fig = go.Figure()
    for team, grp in df.groupby("Team"):
        color = TEAM_COLORS.get(str(team), BLUE)
        hovers = [
            f"<b>{row['Player']}</b> · {team}<br>"
            f"{x_label}: {_fmt(x_col, row[x_col])}<br>"
            f"{y_label}: {_fmt(y_col, row[y_col])}<br>"
            f"{int(row['GP']) if pd.notna(row.get('GP')) else '?'} GP"
            for _, row in grp.iterrows()
        ]
        fig.add_trace(go.Scatter(
            x=grp[x_col],
            y=grp[y_col],
            mode="markers+text",
            name=team,
            marker=dict(color=color, size=10, opacity=0.85,
                        line=dict(width=1, color="rgba(255,255,255,0.3)")),
            text=grp["Player"].apply(lambda n: n.split()[-1]),
            textposition="top center",
            textfont=dict(size=9, color=color),
            hovertext=hovers,
            hovertemplate="%{hovertext}<extra></extra>",
        ))

    title = f"{x_label} vs. {y_label}"
    if subtitle:
        title += f"<br><sup>{subtitle}</sup>"

    fig.update_layout(
        title=title,
        xaxis_title=x_label,
        yaxis_title=y_label,
        xaxis_tickformat=x_fmt if x_col in PCT_STATS else "",
        yaxis_tickformat=y_fmt if y_col in PCT_STATS else "",
        template="plotly_dark",
        height=580,
        showlegend=True,
        legend=dict(title="Team", orientation="v"),
    )
    return fig


def _durability_availability_chart(roster: pd.DataFrame, team: str, team_games: int) -> go.Figure:
    from data.teams import TEAM_COLORS, TEAM_NAMES
    team_color = TEAM_COLORS.get(team, BLUE)

    def _avail_color(pct: float) -> str:
        if pct >= 0.90:
            return "#2ecc71"
        if pct >= 0.75:
            return "#f5a623"
        return "#e74c3c"

    colors = [_avail_color(p) for p in roster["avail_pct"]]
    hovers = [
        f"<b>{row['Player']}</b><br>"
        f"{int(row['G'])} of {team_games} games<br>"
        f"Availability: {row['avail_pct']:.0%}"
        for _, row in roster.iterrows()
    ]

    fig = go.Figure(go.Bar(
        x=roster["avail_pct"],
        y=roster["Player"],
        orientation="h",
        marker_color=colors,
        hovertext=hovers,
        hovertemplate="%{hovertext}<extra></extra>",
    ))
    fig.add_vline(x=1.0, line_dash="dot", line_color="rgba(255,255,255,0.25)")
    fig.update_layout(
        title=f"{TEAM_NAMES.get(team, team)} — Player Availability ({team_games} team games)",
        xaxis_title="Games played ÷ team games",
        xaxis_tickformat=".0%",
        xaxis_range=[0, 1.05],
        template="plotly_dark",
        height=max(300, len(roster) * 36 + 80),
        margin=dict(l=160),
    )
    return fig


def _durability_impact_chart(gamelogs: pd.DataFrame, roster: pd.DataFrame, team: str, team_games: int) -> go.Figure:
    from data.teams import TEAM_COLORS, TEAM_NAMES

    team_logs = gamelogs[gamelogs["Tm"] == team].copy()
    if team_logs.empty or "Date" not in team_logs.columns or "Result" not in team_logs.columns:
        return _empty_fig("No game log data for this team.")

    # Full team schedule: unique (Date, Result) pairs
    team_schedule = team_logs.drop_duplicates("Date")[["Date", "Result"]].set_index("Date")
    total_w = int((team_schedule["Result"] == "W").sum())
    total_l = int((team_schedule["Result"] == "L").sum())
    total_g = total_w + total_l

    if total_g == 0:
        return _empty_fig("No complete game records found.")

    records = []
    for _, row in roster.iterrows():
        player = row["Player"]
        player_dates = set(team_logs[team_logs["Player"] == player]["Date"].dropna())
        without_dates = set(team_schedule.index) - player_dates

        if len(player_dates) == 0:
            continue

        with_results = team_schedule.loc[team_schedule.index.isin(player_dates), "Result"]
        with_w = int((with_results == "W").sum())
        with_g = len(with_results)
        with_pct = with_w / with_g if with_g > 0 else None

        without_results = team_schedule.loc[team_schedule.index.isin(without_dates), "Result"]
        without_w = int((without_results == "W").sum())
        without_g = len(without_results)
        without_pct = without_w / without_g if without_g >= 2 else None

        records.append({
            "Player": player,
            "with_pct": with_pct,
            "with_g": with_g,
            "with_w": with_w,
            "without_pct": without_pct,
            "without_g": without_g,
            "without_w": without_w,
            "avail_pct": row["avail_pct"],
        })

    if not records:
        return _empty_fig("Not enough game log data to compute impact.")

    df = pd.DataFrame(records).sort_values("avail_pct", ascending=False)
    team_color = TEAM_COLORS.get(team, BLUE)

    fig = go.Figure()
    df = df.reset_index(drop=True)

    fig.add_trace(go.Bar(
        name="With player",
        x=df["Player"],
        y=df["with_pct"],
        marker_color=team_color,
        hovertext=[
            f"<b>{r['Player']}</b> — With<br>"
            f"{r['with_w']}-{r['with_g'] - r['with_w']} in {r['with_g']} games "
            f"({r['with_pct']:.0%})"
            if r["with_pct"] is not None else f"<b>{r['Player']}</b> — no data"
            for _, r in df.iterrows()
        ],
        hovertemplate="%{hovertext}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        name="Without player",
        x=df["Player"],
        y=df["without_pct"],
        marker_color=GRAY,
        hovertext=[
            f"<b>{r['Player']}</b> — Without<br>"
            f"{r['without_w']}-{r['without_g'] - r['without_w']} in {r['without_g']} games "
            f"({r['without_pct']:.0%})"
            if r["without_pct"] is not None
            else f"<b>{r['Player']}</b> — fewer than 2 games missed (no sample)"
            for _, r in df.iterrows()
        ],
        hovertemplate="%{hovertext}<extra></extra>",
    ))

    # Overall team win% reference line
    team_wpct = total_w / total_g
    fig.add_hline(
        y=team_wpct,
        line_dash="dash",
        line_color=GOLD,
        annotation_text=f"Team overall {total_w}-{total_l} ({team_wpct:.0%})",
        annotation_position="top left",
        annotation_font_color=GOLD,
    )

    fig.update_layout(
        title=f"{TEAM_NAMES.get(team, team)} — Team Win% With vs. Without Each Player",
        yaxis_title="Win %",
        yaxis_tickformat=".0%",
        yaxis_range=[0, 1.05],
        barmode="group",
        template="plotly_dark",
        height=420,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def _team_schedule(gamelogs: pd.DataFrame) -> pd.DataFrame:
    """Unique (Tm, Date, Result) rows — one row per team per game."""
    if gamelogs.empty or "Tm" not in gamelogs.columns:
        return pd.DataFrame()
    cols = [c for c in ["Tm", "Date", "Result"] if c in gamelogs.columns]
    return gamelogs[cols].drop_duplicates(["Tm", "Date"]).copy()


def _compute_last10(gamelogs: pd.DataFrame) -> dict[str, str]:
    """Returns {team_abbrev: 'W-L'} for each team's last 10 games."""
    sched = _team_schedule(gamelogs)
    if sched.empty:
        return {}
    sched["Date"] = pd.to_datetime(sched["Date"], errors="coerce")
    result = {}
    for tm, grp in sched.groupby("Tm"):
        last10 = grp.sort_values("Date").tail(10)
        w = int((last10["Result"] == "W").sum())
        l = int((last10["Result"] == "L").sum())
        result[tm] = f"{w}-{l}"
    return result


def _winpct_trend_chart(gamelogs: pd.DataFrame, selected_teams: list) -> go.Figure:
    from data.teams import TEAM_COLORS, TEAM_NAMES
    sched = _team_schedule(gamelogs)
    if sched.empty:
        return _empty_fig("No game log data available.")
    sched["Date"] = pd.to_datetime(sched["Date"], errors="coerce")
    sched = sched.dropna(subset=["Date"]).sort_values(["Tm", "Date"])

    all_teams = sorted(sched["Tm"].unique())
    highlight = set(selected_teams) if selected_teams else set()

    fig = go.Figure()
    for tm in all_teams:
        grp = sched[sched["Tm"] == tm].reset_index(drop=True)
        grp["cum_w"] = (grp["Result"] == "W").cumsum()
        grp["game_num"] = range(1, len(grp) + 1)
        grp["wpct"] = grp["cum_w"] / grp["game_num"]

        is_highlighted = not highlight or tm in highlight
        color = TEAM_COLORS.get(tm, BLUE)
        name = TEAM_NAMES.get(tm, tm)

        hovers = [
            f"<b>{name}</b><br>Game {row['game_num']}: {int(row['cum_w'])}-{row['game_num'] - int(row['cum_w'])}<br>Win%: {row['wpct']:.1%}"
            for _, row in grp.iterrows()
        ]

        fig.add_trace(go.Scatter(
            x=grp["game_num"],
            y=grp["wpct"],
            mode="lines",
            name=name,
            line=dict(
                color=color if is_highlighted else "rgba(255,255,255,0.12)",
                width=2.5 if is_highlighted else 1,
            ),
            opacity=1.0 if is_highlighted else 0.4,
            hovertext=hovers,
            hovertemplate="%{hovertext}<extra></extra>",
        ))

    fig.add_hline(y=0.5, line_dash="dash", line_color="rgba(255,255,255,0.25)",
                  annotation_text=".500", annotation_position="right",
                  annotation_font_color="rgba(255,255,255,0.4)")

    fig.update_layout(
        xaxis_title="Game",
        yaxis_title="Win %",
        yaxis_tickformat=".0%",
        yaxis_range=[0, 1],
        template="plotly_dark",
        height=420,
        legend=dict(orientation="v", font=dict(size=11)),
        margin=dict(r=120),
    )
    return fig


TOTAL_SEASON_GAMES = 44  # 2026: 15 teams, 44-game schedule
PLAYOFF_SPOTS = 8
HCA_SPOTS = 4


def _standings_prep(standings: pd.DataFrame):
    """Return standings sorted best→worst with derived columns."""
    from data.teams import TEAM_NAMES, TEAM_COLORS
    df = standings.copy()
    df["W"] = pd.to_numeric(df["W"], errors="coerce")
    df["L"] = pd.to_numeric(df["L"], errors="coerce")
    df = df.dropna(subset=["W", "L"]).reset_index(drop=True)

    # Map full team name → abbreviation (older snapshots still carry bref's playoff '*')
    df["Team"] = df["Team"].map(clean_team_name)
    df["Abbrev"] = df["Team"].map(lambda t: team_abbrev(t, t))
    df["Color"] = df["Abbrev"].map(TEAM_COLORS).fillna(BLUE)

    df["GP"] = df["W"] + df["L"]
    df["Remaining"] = (TOTAL_SEASON_GAMES - df["GP"]).clip(lower=0)
    df["W/L%"] = df["W"] / df["GP"]
    df = df.sort_values("W/L%", ascending=False).reset_index(drop=True)

    # Games behind leader
    leader_W, leader_L = df.iloc[0]["W"], df.iloc[0]["L"]
    df["GB"] = ((leader_W - df["W"]) + (df["L"] - leader_L)) / 2
    df["GB"] = df["GB"].apply(lambda x: "—" if x == 0 else (f"{x:.1f}" if x % 1 else str(int(x))))

    n = len(df)

    def _wins_needed(rank, team_W, team_remaining, rival_W, rival_remaining):
        rival_max = rival_W + rival_remaining
        needed = max(0, int(rival_max - team_W + 1))
        if needed > team_remaining:
            return None  # mathematically impossible to clinch alone
        return needed

    # Wins to clinch playoffs
    playoff_clinch = []
    rival_po = df.iloc[PLAYOFF_SPOTS] if n > PLAYOFF_SPOTS else None  # first team out
    last_in_po = df.iloc[PLAYOFF_SPOTS - 1] if n >= PLAYOFF_SPOTS else None
    for i, row in df.iterrows():
        rank = i + 1
        if rival_po is None:
            playoff_clinch.append(0)
        elif rank <= PLAYOFF_SPOTS:
            playoff_clinch.append(_wins_needed(
                rank, row["W"], row["Remaining"],
                rival_po["W"], rival_po["Remaining"],
            ))
        else:
            # Out of playoffs: wins needed to guarantee passing the last team in
            playoff_clinch.append(_wins_needed(
                rank, row["W"], row["Remaining"],
                last_in_po["W"], last_in_po["Remaining"],
            ))
    df["Clinch Playoffs"] = [
        "Clinched" if v == 0 else ("—" if v is None else str(v))
        for v in playoff_clinch
    ]

    # Wins to clinch home court advantage (top HCA_SPOTS)
    hca_clinch = []
    rival_hca = df.iloc[HCA_SPOTS] if n > HCA_SPOTS else None  # first team without HCA
    last_in_hca = df.iloc[HCA_SPOTS - 1] if n >= HCA_SPOTS else None
    for i, row in df.iterrows():
        rank = i + 1
        if rival_hca is None:
            hca_clinch.append(0)
        elif rank <= HCA_SPOTS:
            hca_clinch.append(_wins_needed(
                rank, row["W"], row["Remaining"],
                rival_hca["W"], rival_hca["Remaining"],
            ))
        else:
            hca_clinch.append(_wins_needed(
                rank, row["W"], row["Remaining"],
                last_in_hca["W"], last_in_hca["Remaining"],
            ))
    df["Clinch HCA"] = [
        "Clinched" if v == 0 else ("—" if v is None else str(v))
        for v in hca_clinch
    ]

    return df


def _season_complete(standings: pd.DataFrame) -> bool:
    df = _standings_prep(standings)
    return not df.empty and bool((df["Remaining"] == 0).all())


def _postseason_status(series: pd.DataFrame) -> dict[str, str]:
    """{abbrev: 'Won Finals' | 'Lost Semifinals' | 'Semifinals (1-2)' …} from playoff_series."""
    if series.empty:
        return {}
    out: dict[str, str] = {}
    # Process earliest round first so later rounds overwrite
    order = {"First Round": 0, "Semifinals": 1, "Finals": 2}
    series = series.assign(_r=series["Round"].map(order).fillna(9)).sort_values("_r")
    for _, r in series.iterrows():
        lead, trail = r["Leader"], r["Trailer"]
        if "TBD" in (lead, trail):
            continue  # future round, matchup not set yet
        lw, tw = int(r.get("LeaderWins", 0) or 0), int(r.get("TrailerWins", 0) or 0)
        rnd = r["Round"]
        if bool(r.get("Complete")):
            out[lead] = "Won Finals 🏆" if rnd == "Finals" else f"Won {rnd}"
            out[trail] = f"Lost {rnd}"
        else:
            out[lead] = f"{rnd} ({lw}-{tw})"
            out[trail] = f"{rnd} ({tw}-{lw})"
    return out


def _standings_chart(standings: pd.DataFrame) -> go.Figure:
    df = _standings_prep(standings)
    n = len(df)
    complete = bool((df["Remaining"] == 0).all())

    # Plotly horizontal bars: sort ascending so best team renders at top
    df_asc = df.iloc[::-1].reset_index(drop=True)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Wins",
        y=df_asc["Team"],
        x=df_asc["W"],
        orientation="h",
        marker_color="#2ecc71",
        hovertemplate="<b>%{y}</b><br>Wins: %{x}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        name="Losses",
        y=df_asc["Team"],
        x=df_asc["L"],
        orientation="h",
        marker_color="rgba(180,60,60,0.6)",
        hovertemplate="<b>%{y}</b><br>Losses: %{x}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        name="Remaining",
        y=df_asc["Team"],
        x=df_asc["Remaining"],
        orientation="h",
        marker_color="rgba(255,255,255,0.08)",
        hovertemplate="<b>%{y}</b><br>Games remaining: %{x}<extra></extra>",
    ))

    # Dotted line between playoff teams and non-playoff teams
    # In ascending sort, playoff cutoff is between index (n-PLAYOFF_SPOTS-1) and (n-PLAYOFF_SPOTS)
    po_y = n - PLAYOFF_SPOTS - 0.5
    hca_y = n - HCA_SPOTS - 0.5

    fig.add_shape(
        type="line", x0=0, x1=1, xref="paper",
        y0=po_y, y1=po_y,
        line=dict(color=GOLD, width=2, dash="dot"),
    )
    fig.add_annotation(
        x=1, xref="paper", y=po_y, yref="y",
        text="Playoff cutoff", showarrow=False,
        xanchor="right", yanchor="bottom",
        font=dict(color=GOLD, size=11),
    )
    if not complete:
        fig.add_shape(
            type="line", x0=0, x1=1, xref="paper",
            y0=hca_y, y1=hca_y,
            line=dict(color="#6ec6e6", width=1.5, dash="dot"),
        )
        fig.add_annotation(
            x=1, xref="paper", y=hca_y, yref="y",
            text="Home court cutoff", showarrow=False,
            xanchor="right", yanchor="bottom",
            font=dict(color="#6ec6e6", size=11),
        )

    fig.update_layout(
        barmode="stack",
        title="2026 WNBA Final Regular-Season Standings" if complete else "2026 WNBA Standings",
        xaxis_title="Games",
        xaxis=dict(range=[0, TOTAL_SEASON_GAMES + 1]),
        template="plotly_dark",
        height=520,
        margin=dict(l=200),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def _standings_table(standings: pd.DataFrame, last10: dict | None = None,
                     postseason: dict | None = None):
    df = _standings_prep(standings)
    complete = bool((df["Remaining"] == 0).all())

    df["Last 10"] = df["Abbrev"].map(last10 or {}).fillna("—")
    if complete:
        # Clinch math is moot once every game is played — show seeds and playoff results
        df["Seed"] = [str(i) if i <= PLAYOFF_SPOTS else "—" for i in range(1, len(df) + 1)]
        df["Postseason"] = [
            (postseason or {}).get(a, "Missed playoffs" if i >= PLAYOFF_SPOTS else "—")
            for i, a in enumerate(df["Abbrev"])
        ]
        extra_cols = ["Seed", "Postseason"]
    else:
        df = df.rename(columns={"Clinch Playoffs": "Wins to Clinch Playoffs", "Clinch HCA": "Wins to Clinch HCA"})
        extra_cols = ["Wins to Clinch Playoffs", "Wins to Clinch HCA"]
    display = df[["Team", "W", "L", "W/L%", "GB", "Last 10"] + extra_cols].copy()
    display.insert(0, "#", range(1, len(df) + 1))
    display["W/L%"] = display["W/L%"].apply(lambda x: f"{x:.3f}" if pd.notna(x) else "—")

    playoff_cutoff_idx = PLAYOFF_SPOTS - 1  # 0-indexed last row IN playoffs

    style_data_conditional = [
        {"if": {"row_index": "odd"}, "backgroundColor": "#181b28"},
        # Gold bottom border on playoff cutoff row
        {
            "if": {"row_index": playoff_cutoff_idx},
            "borderBottom": f"2px dashed {GOLD}",
        },
        # Dim eliminated teams
        *[
            {"if": {"row_index": i}, "color": "#888"}
            for i in range(PLAYOFF_SPOTS, len(df))
        ],
    ]

    return dash_table.DataTable(
        data=display.to_dict("records"),
        columns=[{"name": c, "id": c} for c in display.columns],
        style_table={"overflowX": "auto"},
        style_header={"backgroundColor": "#1e2130", "color": "white", "fontWeight": "bold"},
        style_data={"backgroundColor": "#13161f", "color": "white"},
        style_data_conditional=style_data_conditional,
        style_cell={"textAlign": "left", "padding": "8px 12px"},
        style_cell_conditional=[
            {"if": {"column_id": c}, "textAlign": "center"}
            for c in ["#", "W", "L", "W/L%", "GB", "Last 10", "Seed", "Postseason",
                      "Wins to Clinch Playoffs", "Wins to Clinch HCA"]
        ],
        page_size=20,
    )


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


# ── Playoffs helpers ──────────────────────────────────────────────────────────

PLAYOFF_ROUNDS = ["First Round", "Semifinals", "Finals"]
# Bracket slot for each seed so the tree lines up: (1v8, 4v5) feed one semi, (3v6, 2v7) the other
_SEED_SLOT = {1: 0, 8: 0, 4: 1, 5: 1, 3: 2, 6: 2, 2: 3, 7: 3}


def _playoff_seeds(standings: pd.DataFrame) -> dict[str, int]:
    if standings.empty:
        return {}
    df = _standings_prep(standings)
    return {a: i + 1 for i, a in enumerate(df["Abbrev"].head(PLAYOFF_SPOTS))}


def _teams_alive(series: pd.DataFrame) -> set[str]:
    if series.empty:
        return set()
    teams = set(series["Leader"]) | set(series["Trailer"])
    losers = set(series.loc[series["Complete"].astype(bool), "Trailer"])
    return teams - losers - {"TBD"}


def _playoff_summary(series: pd.DataFrame) -> str:
    alive = _teams_alive(series)
    finals = series[series["Round"] == "Finals"]
    if not finals.empty and bool(finals.iloc[0]["Complete"]):
        champ = finals.iloc[0]["Leader"]
        return f"🏆 {TEAM_NAMES.get(champ, champ)} are the 2026 WNBA champions."
    in_progress = series[~series["Complete"].astype(bool)]
    rnd = in_progress["Round"].iloc[0] if not in_progress.empty else series["Round"].iloc[0]
    names = ", ".join(sorted(TEAM_NAMES.get(t, t) for t in alive))
    return f"{rnd} in progress · {len(alive)} teams alive: {names}"


def _refresh_note() -> str:
    from data.store import get_refresh_meta
    meta = get_refresh_meta("playoffs")
    if not meta:
        return ""
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        ts = datetime.fromisoformat(meta["updated"]).astimezone(ZoneInfo("America/New_York"))
        when = ts.strftime("%b %-d, %-I:%M %p ET")
    except Exception:
        when = str(meta.get("updated", ""))[:16]
    return f"Updated {when} · source: {meta.get('source', '')}"


def _short_date(d: str) -> str:
    # "Sun, October 4" → "Sun Oct 4"
    try:
        dow, rest = d.split(", ", 1)
        month, day = rest.split()
        return f"{dow} {month[:3]} {day}"
    except ValueError:
        return d


def _series_card(row, games: pd.DataFrame, seeds: dict[str, int], best_of: int):
    sid = row["series_id"]
    g = games[games["series_id"] == sid].sort_values("Game") if not games.empty else games
    lw, tw = int(row.get("LeaderWins", 0) or 0), int(row.get("TrailerWins", 0) or 0)
    complete = bool(row.get("Complete"))
    to_win = best_of // 2 + 1

    # Show the higher seed on top
    teams = [(row["Leader"], lw), (row["Trailer"], tw)]
    teams.sort(key=lambda t: seeds.get(t[0], 99))

    def team_row(abbrev, wins):
        won_series = complete and wins == to_win
        eliminated = complete and not won_series
        return html.Div([
            html.Img(src=TEAM_LOGOS.get(abbrev, ""), style={"height": "28px", "width": "28px",
                                                             "objectFit": "contain"}, className="me-2"),
            html.Span(str(seeds.get(abbrev, "")), className="text-muted me-2",
                      style={"fontSize": "0.8em", "width": "12px", "display": "inline-block"}),
            html.Span(TEAM_NAMES.get(abbrev, abbrev),
                      style={"fontWeight": "700" if won_series else "500",
                             "flex": "1", "opacity": 0.45 if eliminated else 1}),
            html.Span(str(wins), style={"fontSize": "1.4em", "fontWeight": "700",
                                        "color": GOLD if won_series else ("#666" if eliminated else "white")}),
        ], className="d-flex align-items-center py-1")

    game_lines = []
    for _, gm in g.iterrows():
        played = pd.notna(gm.get("AwayPts")) and pd.notna(gm.get("HomePts"))
        if complete and not played:
            continue
        live = gm.get("State") == "live"
        if live:
            ap, hp = int(gm["AwayPts"]), int(gm["HomePts"])
            body = [html.Span("LIVE ", style={"color": "#e74c3c", "fontWeight": "700"}),
                    f"{gm['Away']} {ap} @ {gm['Home']} {hp}",
                    html.Span(f" · {gm.get('Detail', '')}", className="text-muted")]
            cls = ""
        elif played:
            ap, hp = int(gm["AwayPts"]), int(gm["HomePts"])
            away = html.B(f"{gm['Away']} {ap}") if ap > hp else html.Span(f"{gm['Away']} {ap}")
            home = html.B(f"{gm['Home']} {hp}") if hp > ap else html.Span(f"{gm['Home']} {hp}")
            body = [away, " @ ", home]
            cls = ""
        else:
            if "IfNecessary" in gm and pd.notna(gm["IfNecessary"]):
                if_nec = bool(gm["IfNecessary"])
            else:
                # A game is only needed if neither team can have clinched before it
                if_nec = int(gm["Game"]) > (lw + tw) + (to_win - max(lw, tw))
            tip = f" · {gm['Tip']}" if pd.notna(gm.get("Tip")) and gm.get("Tip") else ""
            body = [f"{gm['Away']} @ {gm['Home']}{tip}{' (if nec.)' if if_nec else ''}"]
            cls = "text-muted"
        game_lines.append(html.Div(
            [html.Span(f"G{int(gm['Game'])} · {_short_date(str(gm['Date']))} · ", className="text-muted")] + body,
            className=cls, style={"fontSize": "0.8em"},
        ))

    return dbc.Card(dbc.CardBody([
        team_row(*teams[0]),
        team_row(*teams[1]),
        html.Div(row.get("Status", ""), className="text-info mt-1 mb-2", style={"fontSize": "0.85em"}),
        html.Div(game_lines),
    ]), className="mb-3", style={"backgroundColor": "#1a1d2b", "border": "1px solid #2a2e40"})


def _tbd_card(label: str):
    return dbc.Card(dbc.CardBody(html.Div(label, className="text-muted text-center py-3")),
                    className="mb-3",
                    style={"backgroundColor": "#14161f", "border": "1px dashed #2a2e40"})


def _playoff_bracket(series: pd.DataFrame, games: pd.DataFrame, seeds: dict[str, int]):
    def slot(r):
        return min(_SEED_SLOT.get(seeds.get(r["Leader"], 0), 9), _SEED_SLOT.get(seeds.get(r["Trailer"], 0), 9))

    expected = {"First Round": 4, "Semifinals": 2, "Finals": 1}
    cols = []
    for rnd in PLAYOFF_ROUNDS:
        rs = series[series["Round"] == rnd]
        # A sweep lists fewer games, so take the longest series in the round
        n = games[games["series_id"].isin(rs["series_id"])]["Game"].max() if not games.empty else None
        best_of = int(n) if pd.notna(n) else 1
        done = rs[rs["Complete"].astype(bool)] if not rs.empty else rs
        if not done.empty:  # winner's win total pins the length even if every series was a sweep
            best_of = max(best_of, 2 * int(done[["LeaderWins", "TrailerWins"]].max().max()) - 1)
        cards = [
            _tbd_card(f"Awaiting semifinal winners · {r['Status']}")
            if "TBD" in (r["Leader"], r["Trailer"]) else _series_card(r, games, seeds, best_of)
            for _, r in sorted(rs.iterrows(), key=lambda kv: slot(kv[1]))
        ]
        while len(cards) < expected[rnd]:
            cards.append(_tbd_card("Awaiting " + ("semifinal winners" if rnd == "Finals" else "first round")))
        cols.append(dbc.Col([
            html.H5(rnd + (f" · best of {best_of}" if not rs.empty else ""), className="mb-3"),
            # Spread later-round cards vertically so the bracket reads as a tree
            html.Div(cards, className="d-flex flex-column justify-content-around h-100"),
        ], lg=4, md=12))
    return dbc.Row(cols, className="g-4")


def _playoff_player_averages(logs: pd.DataFrame) -> pd.DataFrame:
    df = logs.copy()
    num = ["MP", "FG", "FGA", "3P", "3PA", "FT", "FTA", "TRB", "AST", "STL", "BLK", "TOV", "PTS", "GmSc"]
    for c in num:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    grp = df.groupby(["Player", "Tm"])
    agg = grp[[c for c in num if c in df.columns]].mean()
    tot = grp[["FG", "FGA", "3P", "3PA", "FT", "FTA", "PTS"]].sum()
    agg["G"] = grp.size()
    agg["W-L"] = grp["Result"].apply(lambda r: f"{(r == 'W').sum()}-{(r == 'L').sum()}")
    agg["FG%"] = tot["FG"] / tot["FGA"].where(tot["FGA"] > 0)
    agg["3P%"] = tot["3P"] / tot["3PA"].where(tot["3PA"] > 0)
    agg["FT%"] = tot["FT"] / tot["FTA"].where(tot["FTA"] > 0)
    tsa = 2 * (tot["FGA"] + 0.44 * tot["FTA"])
    agg["TS%"] = tot["PTS"] / tsa.where(tsa > 0)
    agg = agg.reset_index().rename(columns={"Tm": "Team"})
    return agg


def _playoff_leaders_chart(agg: pd.DataFrame, stat: str) -> go.Figure:
    df = agg.copy()
    if stat in ("TS%",):
        df = df[df["MP"] >= 15]  # avoid tiny-sample efficiency outliers
    df = df.dropna(subset=[stat]).sort_values(stat, ascending=False).head(15).iloc[::-1]
    if df.empty:
        return _empty_fig("No playoff data for this stat.")
    is_pct = stat.endswith("%")
    label = {"TS%": "True Shooting %", "GmSc": "Game Score"}.get(stat, STAT_LABELS.get(stat, stat))
    hovers = [
        f"<b>{r['Player']}</b> · {r['Team']}<br>{int(r['G'])} GP ({r['W-L']}) · "
        f"{label}: {r[stat]:.1%}" if is_pct else
        f"<b>{r['Player']}</b> · {r['Team']}<br>{int(r['G'])} GP ({r['W-L']}) · {label}: {r[stat]:.1f}"
        for _, r in df.iterrows()
    ]
    fig = go.Figure(go.Bar(
        x=df[stat], y=df["Player"], orientation="h",
        marker_color=[TEAM_COLORS.get(t, BLUE) for t in df["Team"]],
        hovertext=hovers, hovertemplate="%{hovertext}<extra></extra>",
    ))
    fig.update_layout(
        title=f"Top 15 — {label}" + (" (15+ MPG)" if stat == "TS%" else ""),
        xaxis_tickformat=".0%" if is_pct else "",
        template="plotly_dark", height=520, margin=dict(l=160),
    )
    return fig


def _playoff_leaders_table(agg: pd.DataFrame, stat: str):
    cols = ["Player", "Team", "G", "W-L", "MP", "PTS", "TRB", "AST", "STL", "BLK", "TOV",
            "FG%", "3P%", "FT%", "TS%", "GmSc"]
    display = agg.sort_values(stat, ascending=False)[[c for c in cols if c in agg.columns]].copy()
    for c in ["MP", "PTS", "TRB", "AST", "STL", "BLK", "TOV", "GmSc"]:
        if c in display.columns:
            display[c] = display[c].round(1)
    for c in ["FG%", "3P%", "FT%", "TS%"]:
        if c in display.columns:
            display[c] = display[c].round(3)
    return dash_table.DataTable(
        data=display.to_dict("records"),
        columns=[{"name": c, "id": c} for c in display.columns],
        sort_action="native",
        style_table={"overflowX": "auto"},
        style_header={"backgroundColor": "#1e2130", "color": "white", "fontWeight": "bold"},
        style_data={"backgroundColor": "#13161f", "color": "white"},
        style_data_conditional=[{"if": {"row_index": "odd"}, "backgroundColor": "#181b28"}],
        page_size=20,
    )
