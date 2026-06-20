"""
Bayesian shrinkage for shooting percentages and credible intervals.

Small sample sizes (early season, bench players) distort raw percentages wildly.
We use a Beta-Binomial conjugate model: prior is set from the league average,
and the posterior shrinks each player toward that average weighted by sample size.

As N grows the posterior converges to the observed rate; at small N it pulls
toward the league mean. Credible intervals widen at small N and shrink with data.
"""

import numpy as np
import pandas as pd
from scipy.stats import beta as beta_dist


def _beta_params_from_mean_sample(mean: float, sample_size: float) -> tuple[float, float]:
    """Convert a prior mean and effective sample size into Beta(alpha, beta)."""
    alpha = mean * sample_size
    b = (1 - mean) * sample_size
    return alpha, b


def shrink_shooting(
    makes: pd.Series,
    attempts: pd.Series,
    league_mean: float | None = None,
    prior_strength: float = 50.0,
) -> pd.DataFrame:
    """
    Returns a DataFrame with posterior mean and 90% credible interval for each player.

    Args:
        makes: made shots (FGM, FTM, etc.)
        attempts: attempted shots
        league_mean: prior mean (league average). If None, computed from the data.
        prior_strength: effective sample size of the prior. 50 ≈ one average player's
                        season worth of attempts — a reasonable default for WNBA.
    """
    if league_mean is None:
        total_makes = makes.sum()
        total_attempts = attempts.sum()
        league_mean = total_makes / total_attempts if total_attempts > 0 else 0.45

    prior_alpha, prior_beta = _beta_params_from_mean_sample(league_mean, prior_strength)

    post_alpha = prior_alpha + makes.fillna(0)
    post_beta = prior_beta + (attempts.fillna(0) - makes.fillna(0))

    posterior_mean = post_alpha / (post_alpha + post_beta)
    ci_low = beta_dist.ppf(0.05, post_alpha, post_beta)
    ci_high = beta_dist.ppf(0.95, post_alpha, post_beta)

    return pd.DataFrame({
        "posterior_mean": posterior_mean,
        "ci_low_90": ci_low,
        "ci_high_90": ci_high,
        "raw_pct": makes / attempts.replace(0, np.nan),
        "attempts": attempts,
    })


def shrink_ts(pts: pd.Series, fga: pd.Series, fta: pd.Series,
              league_ts: float = 0.545) -> pd.DataFrame:
    """
    Bayesian shrinkage for True Shooting %.
    Uses 2*(FGA + 0.44*FTA) as the denominator (standard TS% formula).
    """
    denom = 2 * (fga + 0.44 * fta)
    half_pts = pts / 2  # TS% = PTS / (2 * TSA), treat as makes/attempts with scale
    return shrink_shooting(half_pts, denom / 2, league_mean=league_ts / 2, prior_strength=50.0)
