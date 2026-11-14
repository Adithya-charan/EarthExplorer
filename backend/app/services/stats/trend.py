"""Trend statistics: OLS, Mann-Kendall (original, seasonal, Hamed-Rao), Sen's slope.

All slopes are expressed per YEAR of elapsed time computed from real timestamps
(see ``sampling.to_years``). Mann-Kendall only uses the ORDER of observations, so it
is valid for irregular sampling; Sen's slope uses the actual time differences.

References (see docs/METHODOLOGY.md): Mann 1945; Kendall 1975; Sen 1968;
Hirsch, Slack & Smith 1982; Hamed & Rao 1998.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

from .constants import MAX_N_PAIRWISE


def _finite(x: float | None) -> float | None:
    return None if x is None or not np.isfinite(x) else float(x)


# --------------------------------------------------------------------------
# Ordinary least squares
# --------------------------------------------------------------------------
@dataclass
class OLSResult:
    slope: float
    intercept: float
    std_err: float
    ci_low: float
    ci_high: float
    p_value: float
    r_squared: float
    n: int
    df: int


def linear_regression(t: np.ndarray, y: np.ndarray, alpha: float = 0.05) -> OLSResult:
    n = len(y)
    res = stats.linregress(t, y)
    df = n - 2
    tcrit = float(stats.t.ppf(1 - alpha / 2, df))
    se = float(res.stderr)
    return OLSResult(
        slope=float(res.slope),
        intercept=float(res.intercept),
        std_err=se,
        ci_low=float(res.slope) - tcrit * se,
        ci_high=float(res.slope) + tcrit * se,
        p_value=float(res.pvalue) if np.isfinite(res.pvalue) else 1.0,
        r_squared=float(res.rvalue**2) if np.isfinite(res.rvalue) else 0.0,
        n=n,
        df=df,
    )


@dataclass
class HACResult:
    slope: float
    std_err: float
    ci_low: float
    ci_high: float
    p_value: float
    maxlags: int


def ols_hac(t: np.ndarray, y: np.ndarray, alpha: float = 0.05) -> HACResult | None:
    """OLS slope with Newey-West (HAC) standard errors; assumes observations are equally spaced."""
    import statsmodels.api as sm

    n = len(y)
    maxlags = max(1, int(np.floor(4 * (n / 100.0) ** (2.0 / 9.0))))
    try:
        fit = sm.OLS(y, sm.add_constant(t)).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})
        ci = np.asarray(fit.conf_int(alpha=alpha))[1]
        values = [float(fit.params[1]), float(fit.bse[1]), float(ci[0]), float(ci[1]), float(fit.pvalues[1])]
    except Exception:  # noqa: BLE001 - degenerate designs (constant y, etc.)
        return None
    if not all(np.isfinite(values)):
        return None
    return HACResult(values[0], values[1], values[2], values[3], values[4], maxlags)


# --------------------------------------------------------------------------
# Mann-Kendall
# --------------------------------------------------------------------------
def mk_score(y: np.ndarray) -> int:
    """Kendall's S: sum over i<j of sign(y_j - y_i)."""
    s = 0
    for i in range(len(y) - 1):
        s += int(np.sign(y[i + 1 :] - y[i]).sum())
    return s


def mk_variance(y: np.ndarray) -> float:
    """Var(S) with the tie correction."""
    n = len(y)
    _, counts = np.unique(y, return_counts=True)
    ties = float(sum(c * (c - 1) * (2 * c + 5) for c in counts if c > 1))
    return (n * (n - 1) * (2 * n + 5) - ties) / 18.0


def mk_z(s: float, var_s: float) -> float:
    if var_s <= 0 or s == 0:
        return 0.0
    return (s - np.sign(s)) / np.sqrt(var_s)  # continuity correction


def _classify(z: float, p: float, alpha: float) -> str:
    if p < alpha:
        return "increasing" if z > 0 else "decreasing"
    return "no_clear_trend"


@dataclass
class MKResult:
    s: float
    var_s: float
    z: float
    p_value: float
    tau: float
    n: int
    trend: str
    significant: bool
    seasons_used: int | None = None
    seasons_total: int | None = None


def mann_kendall(y: np.ndarray, alpha: float = 0.05) -> MKResult:
    n = len(y)
    s = float(mk_score(y))
    var_s = mk_variance(y)
    z = float(mk_z(s, var_s))
    p = float(2 * stats.norm.sf(abs(z)))
    return MKResult(s, var_s, z, p, s / (0.5 * n * (n - 1)), n, _classify(z, p, alpha), p < alpha)


def season_groups(season: np.ndarray, min_per_season: int) -> tuple[list[np.ndarray], int]:
    """Index arrays (time ordered) for every season with enough observations, plus total seasons seen."""
    groups: list[np.ndarray] = []
    labels = np.unique(season)
    for lab in labels:
        idx = np.flatnonzero(season == lab)
        if len(idx) >= min_per_season:
            groups.append(idx)
    return groups, len(labels)


def seasonal_mann_kendall(y: np.ndarray, season: np.ndarray, alpha: float, min_per_season: int) -> MKResult:
    """Seasonal Mann-Kendall (Hirsch et al. 1982): S and Var(S) summed over seasons.

    Seasons are treated as independent (the covariance-adjusted version of Hirsch & Slack
    1984 is NOT implemented). Seasons with fewer than ``min_per_season`` observations are skipped.
    """
    groups, total = season_groups(season, min_per_season)
    s_tot, v_tot, pairs = 0.0, 0.0, 0.0
    for idx in groups:
        yg = y[idx]
        s_tot += mk_score(yg)
        v_tot += mk_variance(yg)
        pairs += 0.5 * len(yg) * (len(yg) - 1)
    z = float(mk_z(s_tot, v_tot))
    p = float(2 * stats.norm.sf(abs(z)))
    n_used = int(sum(len(g) for g in groups))
    return MKResult(
        s_tot, v_tot, z, p, s_tot / pairs if pairs else 0.0, n_used, _classify(z, p, alpha), p < alpha, len(groups), total
    )


def hamed_rao(y: np.ndarray, alpha: float = 0.05) -> MKResult | None:
    """Autocorrelation-corrected Mann-Kendall (Hamed & Rao 1998) via pymannkendall.

    Valid for equally spaced, gap-free, non-seasonal series. Returns ``None`` if the
    corrected variance is not positive.
    """
    import pymannkendall as pmk

    try:
        with np.errstate(invalid="ignore", divide="ignore"):
            r = pmk.hamed_rao_modification_test(np.asarray(y, dtype=float), alpha=alpha)
    except Exception:  # noqa: BLE001
        return None
    if not (np.isfinite(r.var_s) and r.var_s > 0 and np.isfinite(r.p) and np.isfinite(r.z)):
        return None
    n = len(y)
    return MKResult(
        float(r.s), float(r.var_s), float(r.z), float(r.p), float(r.Tau), n, _classify(float(r.z), float(r.p), alpha), float(r.p) < alpha
    )


# --------------------------------------------------------------------------
# Sen's slope
# --------------------------------------------------------------------------
@dataclass
class SenResult:
    slope: float
    ci_low: float | None
    ci_high: float | None
    intercept: float
    n_pairs: int


def _pairwise(t: np.ndarray, y: np.ndarray, idx: np.ndarray | None = None) -> np.ndarray:
    tt, yy = (t, y) if idx is None else (t[idx], y[idx])
    parts = []
    for i in range(len(tt) - 1):
        dt = tt[i + 1 :] - tt[i]
        ok = dt > 0
        parts.append((yy[i + 1 :][ok] - yy[i]) / dt[ok])
    return np.concatenate(parts) if parts else np.array([])


def _sen_from_slopes(slopes: np.ndarray, t: np.ndarray, y: np.ndarray, var_s: float, alpha: float) -> SenResult:
    slopes = np.sort(slopes)
    n_pairs = len(slopes)
    med = float(np.median(slopes))
    z = float(stats.norm.ppf(1 - alpha / 2))
    sigma = float(np.sqrt(var_s)) if var_s > 0 else 0.0
    # Index selection follows Sen (1968) eq. 2.6 as implemented in scipy.stats.theilslopes.
    lo = max(int(np.round((n_pairs - z * sigma) / 2.0)) - 1, 0)
    hi = min(int(np.round((n_pairs + z * sigma) / 2.0)), n_pairs - 1)
    return SenResult(med, _finite(slopes[lo]), _finite(slopes[hi]), float(np.median(y - med * t)), n_pairs)


def sen_slope(t: np.ndarray, y: np.ndarray, alpha: float = 0.05) -> SenResult:
    if len(y) > MAX_N_PAIRWISE:
        raise ValueError("series too long for exact pairwise Sen's slope")
    return _sen_from_slopes(_pairwise(t, y), t, y, mk_variance(y), alpha)


def seasonal_sen_slope(
    t: np.ndarray, y: np.ndarray, season: np.ndarray, alpha: float, min_per_season: int
) -> SenResult:
    """Median of within-season pairwise slopes (Hirsch et al. 1982), per year of elapsed time."""
    groups, _ = season_groups(season, min_per_season)
    if sum(len(g) * (len(g) - 1) // 2 for g in groups) > MAX_N_PAIRWISE * (MAX_N_PAIRWISE - 1) // 2:
        raise ValueError("series too long for exact pairwise Sen's slope")
    slopes = np.concatenate([_pairwise(t, y, g) for g in groups])
    var_s = float(sum(mk_variance(y[g]) for g in groups))
    used = np.concatenate(groups)
    return _sen_from_slopes(slopes, t[used], y[used], var_s, alpha)
