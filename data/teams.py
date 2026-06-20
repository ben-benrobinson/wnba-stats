"""
WNBA team metadata: logo URLs and display names.
All logo URLs verified against ESPN CDN (200 OK).
"""

ESPN_BASE = "https://a.espncdn.com/i/teamlogos/wnba/500"

# Maps basketball-reference abbreviation → ESPN CDN logo URL
TEAM_LOGOS: dict[str, str] = {
    "ATL": f"{ESPN_BASE}/atl.png",
    "CHI": f"{ESPN_BASE}/chi.png",
    "CON": f"{ESPN_BASE}/con.png",
    "DAL": f"{ESPN_BASE}/dal.png",
    "GSV": f"{ESPN_BASE}/gsv.png",
    "IND": f"{ESPN_BASE}/ind.png",
    "LAS": f"{ESPN_BASE}/la.png",   # LA Sparks → ESPN uses "la"
    "LVA": f"{ESPN_BASE}/lv.png",   # Las Vegas Aces → ESPN uses "lv"
    "MIN": f"{ESPN_BASE}/min.png",
    "NYL": f"{ESPN_BASE}/nyl.png",
    "PHO": f"{ESPN_BASE}/phx.png",
    "POR": f"{ESPN_BASE}/por.png",
    "SEA": f"{ESPN_BASE}/sea.png",
    "TOR": f"{ESPN_BASE}/tor.png",
    "WAS": f"{ESPN_BASE}/was.png",
}

TEAM_NAMES: dict[str, str] = {
    "ATL": "Atlanta Dream",
    "CHI": "Chicago Sky",
    "CON": "Connecticut Sun",
    "DAL": "Dallas Wings",
    "GSV": "Golden State Valkyries",
    "IND": "Indiana Fever",
    "LAS": "Los Angeles Sparks",
    "LVA": "Las Vegas Aces",
    "MIN": "Minnesota Lynx",
    "NYL": "New York Liberty",
    "PHO": "Phoenix Mercury",
    "POR": "Portland Fire",
    "SEA": "Seattle Storm",
    "TOR": "Toronto Tempo",
    "WAS": "Washington Mystics",
}
