import dash_bootstrap_components as dbc
from dash import dcc, html

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

FOOTER = html.Footer(
    dbc.Container(
        html.Small(
            "Data: stats.wnba.com (unofficial API) · Refreshed nightly · "
            "Stats are estimates; small sample sizes produce wide uncertainty intervals.",
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
                            {"label": "Win Shares", "value": "WS"},
                            {"label": "True Shooting % (Bayesian)", "value": "TS_POSTERIOR"},
                            {"label": "Usage vs Efficiency", "value": "USG%"},
                        ],
                        value="WS",
                        clearable=False,
                    ),
                ], md=3),
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
    return html.Div([
        dbc.Container([
            dbc.Row(dbc.Col(html.H2("Player Deep Dive"))),
            dbc.Row(dbc.Col(
                dcc.Dropdown(id="player-select", placeholder="Search for a player...",
                             clearable=False),
                md=5, className="mb-4"
            )),
            dbc.Row([
                dbc.Col(dcc.Graph(id="player-ts-chart"), md=6),
                dbc.Col(dcc.Graph(id="player-usage-chart"), md=6),
            ]),
            dbc.Row(dbc.Col(dcc.Graph(id="player-trend-chart"), className="mt-4")),
        ]),
    ])


def team_layout() -> html.Div:
    return html.Div([
        dbc.Container([
            dbc.Row(dbc.Col(html.H2("Team — On/Off Impact"))),
            dbc.Row(dbc.Col(
                dcc.Dropdown(id="team-select", placeholder="Select a team...", clearable=False),
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
        FOOTER,
    ])
