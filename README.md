# WNBA Stats

A statistically rigorous WNBA performance dashboard answering one core question: **how important is this player to their team?**

## What it does

| Metric | Method | Why it matters |
|--------|--------|----------------|
| **Win Shares** | Box-score estimate of wins produced | Single number for player importance |
| **True Shooting % (Bayesian)** | Beta-Binomial posterior with 90% CI | Early-season TS% is noise — this shows how confident to be |
| **On/Off Net Rating** | Points-per-100-poss with/without player | Does the team actually perform better with them on the floor? |
| **On/Off CI** | Normal approximation, 90% CI | Gold bars = statistically meaningful signal |

## Dashboard tabs

- **League** — top 30 players ranked by Win Shares, TS%, or On/Off delta
- **Player** — drill into any player: cumulative TS% with shrinking uncertainty, usage vs. efficiency scatter, points trend
- **Team** — on/off impact waterfall per roster showing who the team can't afford to lose

## Data

Pulled from the unofficial `stats.wnba.com` API (no key required). Refreshed nightly via cron after games complete. Stored in SQLite locally.

## Running locally

```bash
pip install -r requirements.txt
python -m scripts.bootstrap   # seeds the database
python dashboard/app.py       # http://localhost:8050
```

## Deployment

See [DEPLOY.md](DEPLOY.md) for EC2 + Nginx + Gunicorn setup.

## Roadmap

- [ ] Play-by-play data (shot quality, RAPM)
- [ ] Season-over-season player development curves
- [ ] Lineup analysis (5-man unit net ratings)
