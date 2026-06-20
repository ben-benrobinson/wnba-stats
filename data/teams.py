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

# Primary team colors for bar chart fills
TEAM_COLORS: dict[str, str] = {
    "ATL": "#C8102E",  # Atlanta Dream — red
    "CHI": "#418FDE",  # Chicago Sky — sky blue
    "CON": "#E86100",  # Connecticut Sun — orange
    "DAL": "#0057B8",  # Dallas Wings — steel blue
    "GSV": "#7B4F9E",  # Golden State Valkyries — purple
    "IND": "#E03A3E",  # Indiana Fever — red
    "LAS": "#552583",  # Los Angeles Sparks — purple
    "LVA": "#B4001B",  # Las Vegas Aces — dark red
    "MIN": "#236192",  # Minnesota Lynx — teal blue
    "NYL": "#6ECEB2",  # New York Liberty — seafoam green
    "PHO": "#E56020",  # Phoenix Mercury — orange
    "POR": "#CE1141",  # Portland Fire — red
    "SEA": "#2C5234",  # Seattle Storm — forest green
    "TOR": "#722F37",  # Toronto Tempo — maroon
    "WAS": "#002B5C",  # Washington Mystics — navy
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
