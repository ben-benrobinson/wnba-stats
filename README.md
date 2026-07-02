# WNBA Stats

A WNBA stats dashboard for digging into player and team performance — sortable league
leaderboards, per-player splits (opponent quality, home/away, date range), and
team-level filtering by opponent.

## What it does

- **League** — leaderboard across PTS, TRB, AST, STL, BLK, TOV, MP, FG%, 3P%, FT%
- **Player** — per-game stat table, shooting splits vs. league average, league
  percentile rank (filterable by minutes played), and game-log splits (vs. teams
  above/below .500, home/away)
- **Team** — roster stats filterable by opponent quality, specific opponents, and date

## Data

Pulled from basketball-reference.com (box scores + game logs). Refreshed nightly via
cron after games complete. Stored in SQLite locally.

## Running locally

```bash
pip install -r requirements.txt
python -m scripts.bootstrap   # seeds the database
python dashboard/app.py       # http://localhost:8050
```

## Deployment

See [DEPLOY.md](DEPLOY.md) for EC2 + Nginx + Gunicorn setup.

## Roadmap

- [ ] Advanced/derived stats (Win Shares, PER, on/off net rating) — revisit once the
      basics are solid
- [ ] Consistency / variance scoring across games
- [ ] Play-by-play data (shot quality)
