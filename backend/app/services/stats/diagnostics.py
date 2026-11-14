"""Autocorrelation and seasonality diagnostics, plus multiple-testing adjustment."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

from .constants import AUTOCORR_ALPHA, MIN_N_AUTOCORR, MIN_PER_SEASON


# --------------------------------------------------------------------------
# Autocorrelation
# --------------------------------------------------------------------------
@dataclass
class AutocorrDiag:
    lag1: float
    durbin_watson: float
    ljung_box_lags: int
    ljung_box_p: float
    flagged: bool
    effective_n_ar1: float | None


def autocorrelation(resid: np.ndarray) -> AutocorrDiag | None:
    """Diagnostics on detrended (and, where used, deseasonalized) residuals.

    Observations are treated as equally spaced; callers must say so when that is only approximate.
    Returns ``None`` when there is too little data or no variance.
    """
    from statsmodels.stats.diagnostic import acorr_ljungbox
    from statsmodels.stats.stattools import durbin_watson
    from statsmodels.tsa.stattools import acf

    n = len(resid)
    if n < MIN_N_AUTOCORR or float(np.var(resid)) <= 1e-12:
        return None
    lag1 = float(acf(resid, nlags=1, fft=False)[1])
    lags = max(1, min(10, n // 5))
    lb = acorr_ljungbox(resid, lags=[lags], return_df=True)
    p = float(lb["lb_pvalue"].iloc[0])
    n_eff = float(n * (1 - lag1) / (1 + lag1)) if lag1 > 0 else None
    return AutocorrDiag(lag1, float(durbin_watson(resid)), lags, p, bool(p < AUTOCORR_ALPHA), n_eff)


# --------------------------------------------------------------------------
# Seasonality
# --------------------------------------------------------------------------
@dataclass
class SeasonalityDiag:
    kruskal_p: float
    eta_squared: float
    detected: bool
    seasons_tested: int


def season_means(resid: np.ndarray, season: np.ndarray) -> dict[int, float]:
    return {int(s): float(resid[season == s].mean()) for s in np.unique(season)}


def seasonality(resid: np.ndarray, season: np.ndarray, alpha: float = 0.05) -> SeasonalityDiag | None:
    """Kruskal-Wallis test of residuals (after trend removal) across seasons.

    ``eta_squared`` is the share of residual variance explained by the season means.
    Needs at least two seasons with >= MIN_PER_SEASON observations.
    """
    groups = [resid[season == s] for s in np.unique(season)]
    groups = [g for g in groups if len(g) >= MIN_PER_SEASON]
    if len(groups) < 2:
        return None
    try:
        p = float(stats.kruskal(*groups).pvalue)
    except ValueError:  # all values identical
        return None
    allv = np.concatenate(groups)
    grand = allv.mean()
    ss_total = float(((allv - grand) ** 2).sum())
    ss_between = float(sum(len(g) * (g.mean() - grand) ** 2 for g in groups))
    eta = ss_between / ss_total if ss_total > 0 else 0.0
    return SeasonalityDiag(p, eta, bool(p < alpha), len(groups))


# --------------------------------------------------------------------------
# Multiple comparisons
# --------------------------------------------------------------------------
def benjamini_hochberg(p_values: list[float]) -> list[float]:
    """Benjamini-Hochberg adjusted p-values (FDR), in the original order."""
    if not p_values:
        return []
    from statsmodels.stats.multitest import multipletests

    return [float(x) for x in multipletests(p_values, method="fdr_bh")[1]]
