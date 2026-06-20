import dash_bootstrap_components as dbc
from dash import dcc, html
from data.store import load

NAVBAR = dbc.NavbarSimple(
    brand="WNBA Stats",
    brand_href="/",
    color="dark",
    dark=True,
    className="mb-4",
    children=[
        dbc.NavItem(dbc.NavLink("League", href="/")),
        dbc.NavItem(dbc.NavLink("Player", href="/player")),
        dbc.NavItem(dbc.NavLink("Team", href="/team")),
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
    dbc.Container(
        html.Small(
            "Data: basketball-reference.com · Refreshed nightly · "
            "Stats computed by basketball-reference from box scores. "
            "Bayesian TS% computed in-house.",
            className="text-muted",
        ),
        className="py-3",
    )
)


def league_layout() -> html.Div:
    return html.Div([
        dbc.Container([
            dbc.Row(dbc.Col(html.H2("League — Player Importance Rankings"), className="mb-3")),
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
                dbc.Col(dcc.Graph(id="player-ts-chart"), md=6),
                dbc.Col(dcc.Graph(id="player-usage-chart"), md=6),
            ]),
            dbc.Row(dbc.Col(dcc.Graph(id="player-trend-chart"), className="mt-4")),
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
            dbc.Row(dbc.Col(html.H2("Team — Player Impact"))),
            dbc.Row(dbc.Col(
                dcc.Dropdown(id="team-select", placeholder="Select a team...",
                             options=team_options, clearable=False),
                md=4, className="mb-4"
            )),
            dbc.Row(dbc.Col(dcc.Graph(id="team-onoff-chart"))),
            dbc.Row(dbc.Col(
                html.P(
                    "Bars show on/off net rating delta. Error bars are 90% credible intervals. "
                    "Gold bars indicate statistically meaningful signal (CI excludes zero).",
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
