import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from dash import dcc, html
from data.store import load


def _placeholder_fig(msg: str, height: int = 300) -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(
        text=msg, xref="paper", yref="paper", x=0.5, y=0.5,
        showarrow=False, font=dict(size=15, color="#888"),
    )
    fig.update_layout(
        template="plotly_dark", paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        height=height, margin=dict(t=20, b=20),
    )
    return fig

NAVBAR = dbc.NavbarSimple(
    brand="WNBA Stats",
    brand_href="/",
    color="dark",
    dark=True,
    className="mb-4",
    children=[
        dbc.NavItem(dbc.NavLink("Standings", href="/")),
        dbc.NavItem(dbc.NavLink("Leaders", href="/league")),
        dbc.NavItem(dbc.NavLink("Player Profile", href="/player")),
        dbc.NavItem(dbc.NavLink("Roster", href="/team")),
        dbc.NavItem(dbc.NavLink("Scatter", href="/scatter")),
        dbc.NavItem(dbc.NavLink("Game Log", href="/gamelog")),
        dbc.NavItem(dbc.NavLink("Durability", href="/durability")),
    ],
)

GLOSSARY = dbc.Container([
    html.Hr(className="mt-5"),
    dbc.Accordion([
        dbc.AccordionItem(title="Stat Glossary", children=[
            dbc.Row([
                dbc.Col([
                    html.H6("PTS — Points per game"),
                    html.P("Average points scored per game."),
                    html.H6("TRB — Total Rebounds per game"),
                    html.P("Offensive + defensive rebounds per game."),
                    html.H6("AST — Assists per game"),
                    html.P("Passes leading directly to a made basket, per game."),
                    html.H6("STL — Steals per game"),
                    html.P("Times the player legally strips or intercepts the ball, per game."),
                    html.H6("BLK — Blocks per game"),
                    html.P("Opponent field goal attempts deflected, per game."),
                ], md=6),
                dbc.Col([
                    html.H6("TOV — Turnovers per game"),
                    html.P("Times the player loses possession, per game. Lower is better."),
                    html.H6("MP — Minutes per game"),
                    html.P("Average playing time per game."),
                    html.H6("FG% — Field Goal Percentage"),
                    html.P("Percentage of field goal attempts made (all 2s and 3s combined)."),
                    html.H6("3P% — 3-Point Percentage"),
                    html.P("Percentage of 3-point attempts made."),
                    html.H6("FT% — Free Throw Percentage"),
                    html.P("Percentage of free throw attempts made."),
                ], md=6),
            ]),
        ]),
    ], start_collapsed=True, className="mb-3"),
], className="mt-4")

FOOTER = html.Footer(
    dbc.Container([
        html.Small(
            "Data: basketball-reference.com · Refreshed nightly · "
            "Stats computed by basketball-reference from box scores. "
            "Bayesian TS% computed in-house.",
            className="text-muted",
        ),
        html.Div(id="data-quality-badge", className="mt-1"),
    ], className="py-3"),
)


def standings_layout() -> html.Div:
    from data.store import load as _load
    st = _load("player_per_game")
    team_options = []
    if not st.empty and "Team" in st.columns:
        teams = sorted(t for t in st["Team"].dropna().unique() if t not in ("TOT", "Team"))
        team_options = [{"label": t, "value": t} for t in teams]

    return html.Div([
        dbc.Container([
            dbc.Row(dbc.Col(html.H2("League Standings"))),
            dbc.Row(dbc.Col(dcc.Graph(id="standings-chart"))),
            dbc.Row(dbc.Col(html.Div(id="standings-table"), className="mt-3")),
            html.Hr(className="mt-5"),
            dbc.Row([
                dbc.Col(html.H4("Win % Over the Season"), md=8),
                dbc.Col(
                    dcc.Dropdown(
                        id="standings-team-filter",
                        options=team_options,
                        placeholder="All teams (select to highlight)",
                        multi=True,
                        clearable=True,
                    ),
                    md=4,
                ),
            ], className="align-items-center mb-2"),
            dbc.Row(dbc.Col(dcc.Graph(id="standings-winpct-chart"))),
        ]),
    ])


def league_layout() -> html.Div:
    return html.Div([
        dbc.Container([
            dbc.Row(dbc.Col(html.H2("League — Player Stats"), className="mb-3")),
            dbc.Row([
                dbc.Col([
                    html.Label("Sort by"),
                    dcc.Dropdown(
                        id="league-sort",
                        options=[
                            {"label": "Points", "value": "PTS"},
                            {"label": "Rebounds", "value": "TRB"},
                            {"label": "Assists", "value": "AST"},
                            {"label": "Steals", "value": "STL"},
                            {"label": "Blocks", "value": "BLK"},
                            {"label": "Turnovers", "value": "TOV"},
                            {"label": "Minutes", "value": "MP"},
                            {"label": "FG%", "value": "FG%"},
                            {"label": "3P%", "value": "3P%"},
                            {"label": "FT%", "value": "FT%"},
                        ],
                        value="PTS",
                        clearable=False,
                    ),
                ], md=4),
                dbc.Col([
                    html.Label("Min games played"),
                    dcc.Slider(id="league-min-gp", min=1, max=20, step=1, value=5,
                               marks={i: str(i) for i in [1, 5, 10, 15, 20]}),
                ], md=5),
            ], className="mb-4"),
            dbc.Row(dbc.Col(dcc.Graph(id="league-chart"))),
            dbc.Row(dbc.Col(html.Div(id="league-table"), className="mt-4")),
        ]),
    ])


def player_layout() -> html.Div:
    import pandas as pd
    pg = load("player_per_game")
    player_options = []
    if not pg.empty:
        pg = pg[pg["Player"] != "Player"]
        for _, row in pg.iterrows():
            if pd.notna(row.get("Player")) and row.get("Team") not in ("TOT", "Team"):
                player_options.append({
                    "label": f"{row['Player']} ({row['Team']})",
                    "value": f"{row['Player']}|{row['Team']}",
                })

    return html.Div([
        dbc.Container([
            dbc.Row(dbc.Col(html.H2("Player Deep Dive"))),
            dbc.Row([
                dbc.Col(
                    dcc.Dropdown(id="player-select", placeholder="Search for a player...",
                                 options=player_options, clearable=False),
                    md=5,
                ),
                dbc.Col(
                    dcc.Dropdown(
                        id="player-split",
                        options=[
                            {"label": "All games", "value": "all"},
                            {"label": "vs. teams above .500", "value": "above500"},
                            {"label": "vs. teams below .500", "value": "below500"},
                            {"label": "Home games", "value": "home"},
                            {"label": "Away games", "value": "away"},
                        ],
                        value="all",
                        clearable=False,
                    ),
                    md=4,
                ),
            ], className="mb-4"),
            dbc.Row(dbc.Col(html.Div(id="player-split-summary"), className="mb-3")),
            dbc.Row([
                dbc.Col(html.Div(
                    id="player-ts-chart",
                    children=html.Div("👆 Search for a player above to see their per-game stats",
                                      className="text-muted text-center", style={"padding": "120px 0"}),
                ), md=6),
                dbc.Col(dcc.Graph(id="player-usage-chart",
                                  figure=_placeholder_fig("Shooting splits will appear here")),
                       md=6),
            ]),
            dbc.Row([
                dbc.Col(html.Label("Compare against players averaging at least:",
                                   className="small text-muted mt-4"), width=12),
                dbc.Col(
                    dcc.Slider(
                        id="player-min-mp", min=0, max=30, step=1, value=0,
                        marks={i: f"{i}" for i in [0, 5, 10, 15, 20, 25, 30]},
                        tooltip={"placement": "bottom", "always_visible": False},
                    ),
                    md=8,
                ),
            ], className="mb-2"),
            dbc.Row(dbc.Col(dcc.Graph(id="player-trend-chart",
                                      figure=_placeholder_fig("League percentile ranking will appear here")),
                           className="mt-2")),
        ]),
    ])


def team_layout() -> html.Div:
    pg = load("player_per_game")
    team_options = []
    if not pg.empty:
        teams = sorted(t for t in pg["Team"].dropna().unique() if t not in ("TOT", "Team"))
        team_options = [{"label": t, "value": t} for t in teams]

    return html.Div([
        dbc.Container([
            dbc.Row(dbc.Col(html.H2("Team — Player Stats"))),
            dbc.Row([
                dbc.Col(
                    dcc.Dropdown(id="team-select", placeholder="Select a team...",
                                 options=team_options, clearable=False),
                    md=3,
                ),
                dbc.Col(
                    dcc.Dropdown(
                        id="team-quality-filter",
                        options=[
                            {"label": "All games", "value": "all"},
                            {"label": "vs. teams above .500", "value": "above500"},
                            {"label": "vs. teams below .500", "value": "below500"},
                            {"label": "Home games", "value": "home"},
                            {"label": "Away games", "value": "away"},
                        ],
                        value="all",
                        clearable=False,
                        placeholder="Filter by opponent quality...",
                    ),
                    md=3,
                ),
                dbc.Col(
                    dcc.Dropdown(
                        id="team-opp-select",
                        placeholder="Or select specific opponents...",
                        options=[],
                        multi=True,
                        clearable=True,
                    ),
                    md=4,
                ),
            ], className="mb-2"),
            dbc.Row([
                dbc.Col([
                    html.Label("Show games from", className="small text-muted"),
                    dcc.DatePickerSingle(
                        id="team-date-from",
                        placeholder="Start date",
                        display_format="YYYY-MM-DD",
                    ),
                ], md=3),
                dbc.Col([
                    html.Label("Stat to display", className="small text-muted"),
                    dcc.Dropdown(
                        id="team-stat-select",
                        options=[
                            {"label": "Points", "value": "PTS"},
                            {"label": "Rebounds", "value": "TRB"},
                            {"label": "Assists", "value": "AST"},
                            {"label": "Steals", "value": "STL"},
                            {"label": "Blocks", "value": "BLK"},
                            {"label": "Turnovers", "value": "TOV"},
                            {"label": "Minutes", "value": "MP"},
                            {"label": "FG%", "value": "FG%"},
                            {"label": "3P%", "value": "3P%"},
                            {"label": "FT%", "value": "FT%"},
                        ],
                        value="PTS",
                        clearable=False,
                    ),
                ], md=3),
            ], className="mb-2"),
            dbc.Row(dbc.Col(
                html.Small(
                    "Opponent filter and specific opponent selection are mutually exclusive — "
                    "specific opponents take priority if both are set.",
                    className="text-muted",
                )
            ), className="mb-3"),
            dbc.Row(dbc.Col(html.Div(id="team-filter-summary"), className="mb-2")),
            dbc.Row(dbc.Col(dcc.Graph(
                id="team-onoff-chart",
                figure=_placeholder_fig("👆 Select a team above to see player stats", height=500),
            ))),
        ]),
    ])


_STAT_OPTIONS = [
    {"label": "Points", "value": "PTS"},
    {"label": "Rebounds", "value": "TRB"},
    {"label": "Assists", "value": "AST"},
    {"label": "Steals", "value": "STL"},
    {"label": "Blocks", "value": "BLK"},
    {"label": "Turnovers", "value": "TOV"},
    {"label": "Minutes", "value": "MP"},
    {"label": "FG%", "value": "FG%"},
    {"label": "3P%", "value": "3P%"},
    {"label": "FT%", "value": "FT%"},
]


def game_scatter_layout() -> html.Div:
    import pandas as pd
    pg = load("player_per_game")
    player_options = []
    if not pg.empty:
        pg = pg[pg["Player"] != "Player"]
        for _, row in pg.iterrows():
            if pd.notna(row.get("Player")) and row.get("Team") not in ("TOT", "Team"):
                player_options.append({
                    "label": f"{row['Player']} ({row['Team']})",
                    "value": f"{row['Player']}|{row['Team']}",
                })

    return html.Div([
        dbc.Container([
            dbc.Row(dbc.Col(html.H2("Game Log Scatter"))),
            dbc.Row([
                dbc.Col([
                    html.Label("Player", className="small text-muted"),
                    dcc.Dropdown(id="gs-player", placeholder="Search for a player...",
                                 options=player_options, clearable=False),
                ], md=4),
                dbc.Col([
                    html.Label("X axis", className="small text-muted"),
                    dcc.Dropdown(id="gs-x", options=_STAT_OPTIONS, value="PTS", clearable=False),
                ], md=2),
                dbc.Col([
                    html.Label("Y axis", className="small text-muted"),
                    dcc.Dropdown(id="gs-y", options=_STAT_OPTIONS, value="AST", clearable=False),
                ], md=2),
            ], className="mb-3"),
            dbc.Row(dbc.Col(dcc.Graph(
                id="gs-chart",
                figure=_placeholder_fig("Select a player and two stats to see their game log", height=550),
            ))),
        ]),
    ])


def scatter_layout() -> html.Div:
    pg = load("player_per_game")
    team_options = []
    if not pg.empty:
        teams = sorted(t for t in pg["Team"].dropna().unique() if t not in ("TOT", "Team"))
        team_options = [{"label": t, "value": t} for t in teams]

    return html.Div([
        dbc.Container([
            dbc.Row(dbc.Col(html.H2("Scatter — Compare Two Stats"))),
            dbc.Row([
                dbc.Col([
                    html.Label("X axis", className="small text-muted"),
                    dcc.Dropdown(id="scatter-x", options=_STAT_OPTIONS, value="PTS", clearable=False),
                ], md=2),
                dbc.Col([
                    html.Label("Y axis", className="small text-muted"),
                    dcc.Dropdown(id="scatter-y", options=_STAT_OPTIONS, value="TRB", clearable=False),
                ], md=2),
                dbc.Col([
                    html.Label("Filter", className="small text-muted"),
                    dcc.Dropdown(
                        id="scatter-quality-filter",
                        options=[
                            {"label": "All games", "value": "all"},
                            {"label": "vs. teams above .500", "value": "above500"},
                            {"label": "vs. teams below .500", "value": "below500"},
                            {"label": "Home games", "value": "home"},
                            {"label": "Away games", "value": "away"},
                        ],
                        value="all",
                        clearable=False,
                    ),
                ], md=3),
                dbc.Col([
                    html.Label("Specific opponents", className="small text-muted"),
                    dcc.Dropdown(
                        id="scatter-opp-select",
                        placeholder="All opponents",
                        options=[{"label": t, "value": t} for t in
                                 sorted({t for t in pg["Team"].dropna().unique()
                                         if t not in ("TOT", "Team")})] if not pg.empty else [],
                        multi=True,
                        clearable=True,
                    ),
                ], md=3),
            ], className="mb-2"),
            dbc.Row([
                dbc.Col([
                    html.Label("Games from", className="small text-muted"),
                    dcc.DatePickerSingle(
                        id="scatter-date-from",
                        placeholder="Start date",
                        display_format="YYYY-MM-DD",
                    ),
                ], md=3),
                dbc.Col([
                    html.Label("Min games played", className="small text-muted"),
                    dcc.Slider(id="scatter-min-gp", min=1, max=20, step=1, value=5,
                               marks={i: str(i) for i in [1, 5, 10, 15, 20]}),
                ], md=5),
            ], className="mb-3"),
            dbc.Row(dbc.Col(dcc.Graph(
                id="scatter-chart",
                figure=_placeholder_fig("Select stats above to build the scatter plot", height=550),
            ))),
        ]),
    ])


def durability_layout() -> html.Div:
    pg = load("player_per_game")
    team_options = []
    if not pg.empty:
        teams = sorted(t for t in pg["Team"].dropna().unique() if t not in ("TOT", "Team"))
        team_options = [{"label": t, "value": t} for t in teams]

    return html.Div([
        dbc.Container([
            dbc.Row(dbc.Col(html.H2("Durability — Availability & Impact"))),
            dbc.Row(dbc.Col(
                html.P(
                    "How often does each player suit up — and how much does it matter when they don't?",
                    className="text-muted",
                ),
            )),
            dbc.Row([
                dbc.Col(
                    dcc.Dropdown(
                        id="dur-team-select",
                        placeholder="Select a team...",
                        options=team_options,
                        clearable=False,
                    ),
                    md=3,
                ),
            ], className="mb-4"),
            dbc.Row(dbc.Col(dcc.Graph(
                id="dur-availability-chart",
                figure=_placeholder_fig("👆 Select a team to see availability", height=400),
            ))),
            dbc.Row(dbc.Col(dcc.Graph(
                id="dur-impact-chart",
                figure=_placeholder_fig("Win% with vs. without each player will appear here", height=400),
            ), className="mt-4")),
            dbc.Row(dbc.Col(
                html.Small(
                    "Availability = games played ÷ team games played. "
                    "Win% without requires at least 2 games missed to display.",
                    className="text-muted mt-2",
                )
            )),
        ]),
    ])


def root_layout() -> html.Div:
    return html.Div([
        dcc.Location(id="url", refresh=False),
        NAVBAR,
        html.Div(id="page-content"),
        GLOSSARY,
        FOOTER,
    ])
