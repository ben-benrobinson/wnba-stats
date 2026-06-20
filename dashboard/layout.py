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
        dbc.AccordionItem(title="Metric Glossary", children=[
            dbc.Row([
                dbc.Col([
                    html.H6("Win Shares (WS)"),
                    html.P("Estimates the number of team wins a player has produced over the season. "
                           "Combines offensive and defensive contributions into a single number. "
                           "A WS of 3.0 means the player is responsible for roughly 3 team wins. "
                           "Computed by basketball-reference from box score data."),

                    html.H6("Win Shares per 40 minutes (WS/40)"),
                    html.P("Win Shares scaled to a per-40-minute rate, making it fair to compare starters "
                           "who log heavy minutes against bench players with fewer opportunities. "
                           "League average is roughly 0.100."),

                    html.H6("Offensive Win Shares (OWS) / Defensive Win Shares (DWS)"),
                    html.P("WS split into offensive and defensive contributions. "
                           "OWS reflects scoring efficiency and playmaking; DWS reflects rebounding, "
                           "steals, blocks, and defensive positioning."),

                    html.H6("True Shooting % (TS%)"),
                    html.P([
                        "The most complete measure of shooting efficiency. Unlike FG%, it accounts for "
                        "3-pointers (worth more) and free throws. Formula: ",
                        html.Code("TS% = PTS / (2 × (FGA + 0.44 × FTA))"),
                        ". League average is roughly 54.5%. A player at 60%+ is elite."
                    ]),

                    html.H6("True Shooting % — Bayesian Posterior"),
                    html.P("Raw TS% is unreliable early in the season — a player who goes 3-for-3 "
                           "from three looks like a 100% shooter. Bayesian shrinkage fixes this by "
                           "pulling each player's TS% toward the league average, weighted by how many "
                           "attempts they've taken. The more attempts, the more the posterior trusts "
                           "the observed rate. The error bars show the 90% credible interval — the range "
                           "where the player's true shooting talent likely falls."),
                ], md=6),
                dbc.Col([
                    html.H6("Player Efficiency Rating (PER)"),
                    html.P("A per-minute box score rating that combines all positive contributions "
                           "(points, rebounds, assists, steals, blocks) and subtracts negatives "
                           "(missed shots, turnovers, fouls). Scaled so that 15.0 is league average. "
                           "Useful for a quick read but doesn't capture defense well."),

                    html.H6("Usage Rate (USG%)"),
                    html.P("The percentage of team possessions a player uses while on the floor — "
                           "via field goal attempts, free throw attempts, or turnovers. "
                           "A player at 30%+ is a primary option; 15% or below is a role player. "
                           "High usage + high efficiency = star player."),

                    html.H6("Offensive Rating (ORtg)"),
                    html.P("Points the team scores per 100 possessions while this player is on the floor. "
                           "League average is roughly 100. Measures how well the offense runs with the player."),

                    html.H6("Defensive Rating (DRtg)"),
                    html.P("Points the team allows per 100 possessions while this player is on the floor. "
                           "Lower is better. A player with DRtg of 95 is anchoring a very good defense."),

                    html.H6("Net Rating (Net Rtg)"),
                    html.P([
                        "The most important single number for player impact: ",
                        html.Code("Net Rtg = ORtg − DRtg"),
                        ". Positive means the team outscores opponents when this player is on the floor. "
                        "In the Team view, we show each player's Net Rating relative to their team average "
                        "— gold bars mean the team is measurably better with them on the court."
                    ]),
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
                            {"label": "Win Shares", "value": "WS"},
                            {"label": "Win Shares per 40 min", "value": "WS/40"},
                            {"label": "True Shooting % (Bayesian)", "value": "TS_POSTERIOR"},
                            {"label": "Usage vs Efficiency", "value": "USG%"},
                            {"label": "Player Efficiency Rating", "value": "PER"},
                            {"label": "Offensive Rating", "value": "ORtg"},
                            {"label": "Net Rating (ORtg - DRtg)", "value": "NET_RTG"},
                        ],
                        value="WS",
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
    adv = load("player_advanced")
    player_options = []
    if not adv.empty:
        import pandas as pd
        adv = adv[adv["Player"] != "Player"]
        for _, row in adv.iterrows():
            if pd.notna(row.get("Player")) and row.get("Team") != "TOT":
                player_options.append({
                    "label": f"{row['Player']} ({row['Team']})",
                    "value": f"{row['Player']}|{row['Team']}",
                })

    return html.Div([
        dbc.Container([
            dbc.Row(dbc.Col(html.H2("Player Deep Dive"))),
            dbc.Row(dbc.Col(
                dcc.Dropdown(id="player-select", placeholder="Search for a player...",
                             options=player_options, clearable=False),
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
    adv = load("player_advanced")
    team_options = []
    if not adv.empty:
        teams = sorted(t for t in adv["Team"].dropna().unique() if t not in ("TOT", "Team"))
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
