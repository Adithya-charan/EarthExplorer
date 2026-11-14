"""Statistical correctness against known values and independent reference implementations."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pymannkendall as pmk
import pytest
import statsmodels.api as sm
from scipy import stats

from app.errors import AppError
from app.services.stats import diagnostics as dg
from app.services.stats import trend as tr
from app.services.stats.sampling import aggregate, detect_sampling, grid_stats, season_ids, to_years

from .helpers import canonical_df


def ar1(n: int, phi: float, seed: int, sigma: float = 1.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    e = rng.normal(0, sigma, n)
    x = np.zeros(n)
    x[0] = e[0]
    for i in range(1, n):
        x[i] = phi * x[i - 1] + e[i]
    return x


# ---------------------------------------------------------------- time axis
def test_to_years_uses_real_elapsed_time():
    dates = pd.to_datetime(["2000-01-01", "2001-01-01", "2004-01-01"])
    t = to_years(dates)
    assert t[0] == 0.0
    assert t[1] == pytest.approx(366 / 365.25)  # 2000 is a leap year
    assert t[2] == pytest.approx(1461 / 365.25)  # exactly four Julian years


def test_sen_slope_is_per_year_not_per_row():
    # 0.25 units per month == 3.0 units per year; must NOT come out as 0.25 or 36.
    dates = pd.date_range("2000-01-01", periods=120, freq="MS")
    y = 0.25 * np.arange(120)
    res = tr.sen_slope(to_years(dates), y, 0.05)
    assert res.slope == pytest.approx(3.0, abs=0.03)


def test_ols_slope_respects_irregular_timestamps():
    # Observations 1, 2 and 10 years apart: row index would give a wrong slope.
    dates = pd.to_datetime(["2000-01-01", "2001-01-01", "2003-01-01", "2013-01-01", "2014-01-01", "2016-01-01"])
    t = to_years(dates)
    y = 5.0 + 2.0 * t
    res = tr.linear_regression(t, y)
    assert res.slope == pytest.approx(2.0)
    assert res.intercept == pytest.approx(5.0)


# ---------------------------------------------------------------------- OLS
def test_ols_matches_statsmodels_and_scipy():
    rng = np.random.default_rng(11)
    t = np.arange(48) / 12.0
    y = 1.0 + 0.8 * t + rng.normal(0, 0.7, 48)
    res = tr.linear_regression(t, y, 0.05)
    fit = sm.OLS(y, sm.add_constant(t)).fit()
    lo, hi = np.asarray(fit.conf_int(0.05))[1]
    assert res.slope == pytest.approx(fit.params[1])
    assert res.intercept == pytest.approx(fit.params[0])
    assert (res.ci_low, res.ci_high) == (pytest.approx(lo), pytest.approx(hi))
    assert res.p_value == pytest.approx(fit.pvalues[1])
    assert res.r_squared == pytest.approx(fit.rsquared)
    assert res.df == 46
    assert stats.linregress(t, y).slope == pytest.approx(res.slope)


def test_ols_ci_narrower_at_lower_confidence():
    rng = np.random.default_rng(2)
    t = np.arange(60) / 12.0
    y = 0.3 * t + rng.normal(0, 1, 60)
    wide = tr.linear_regression(t, y, 0.01)
    narrow = tr.linear_regression(t, y, 0.10)
    assert (wide.ci_high - wide.ci_low) > (narrow.ci_high - narrow.ci_low)


def test_hac_standard_error_exceeds_naive_for_autocorrelated_noise():
    t = np.arange(240) / 12.0
    y = ar1(240, 0.7, seed=5)
    naive = tr.linear_regression(t, y)
    hac = tr.ols_hac(t, y)
    assert hac is not None
    assert hac.std_err > naive.std_err


# ----------------------------------------------------------- Mann-Kendall
def test_mk_known_values_strictly_increasing():
    r = tr.mann_kendall(np.arange(1.0, 11.0))
    assert r.s == 45
    assert r.var_s == pytest.approx(10 * 9 * 25 / 18)  # 125, no ties
    assert r.z == pytest.approx(44 / np.sqrt(125))
    assert r.p_value == pytest.approx(2 * stats.norm.sf(44 / np.sqrt(125)))
    assert r.tau == pytest.approx(1.0)
    assert r.trend == "increasing" and r.significant


def test_mk_known_values_strictly_decreasing():
    r = tr.mann_kendall(np.arange(10.0, 0.0, -1.0))
    assert r.s == -45
    assert r.z < 0
    assert r.trend == "decreasing" and r.significant


def test_mk_no_trend_series_is_not_significant():
    y = np.array([3, 1, 4, 1, 5, 2, 6, 2, 5, 3, 5, 1, 4, 2, 3, 4], dtype=float)
    r = tr.mann_kendall(y)
    assert not r.significant
    assert r.trend == "no_clear_trend"
    white = np.random.default_rng(7).normal(size=60)
    assert tr.mann_kendall(white).trend == "no_clear_trend"


def test_mk_constant_series_has_zero_statistic():
    r = tr.mann_kendall(np.full(12, 4.2))
    assert r.s == 0 and r.z == 0 and r.p_value == pytest.approx(1.0)


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_mk_matches_pymannkendall(seed):
    rng = np.random.default_rng(seed)
    y = np.round(0.05 * np.arange(80) + rng.normal(0, 1, 80), 1)  # rounding creates ties
    mine = tr.mann_kendall(y, 0.05)
    ref = pmk.original_test(y, alpha=0.05)
    assert mine.s == pytest.approx(ref.s)
    assert mine.var_s == pytest.approx(ref.var_s)
    assert mine.z == pytest.approx(ref.z)
    assert mine.p_value == pytest.approx(ref.p)
    assert mine.tau == pytest.approx(ref.Tau)


def test_mk_tie_correction_reduces_variance():
    no_ties = tr.mk_variance(np.arange(10.0))
    ties = tr.mk_variance(np.array([1, 1, 2, 2, 3, 3, 4, 4, 5, 5], dtype=float))
    assert ties < no_ties


# ------------------------------------------------------------- Sen's slope
def test_sen_matches_scipy_theilslopes_regular():
    rng = np.random.default_rng(3)
    t = np.arange(60) / 12.0
    y = 0.4 * t + rng.normal(0, 1, 60)
    mine = tr.sen_slope(t, y, 0.05)
    ref = stats.theilslopes(y, t, 0.95)
    assert mine.slope == pytest.approx(ref.slope)
    assert mine.ci_low == pytest.approx(ref.low_slope)
    assert mine.ci_high == pytest.approx(ref.high_slope)


def test_sen_matches_scipy_theilslopes_irregular_times():
    rng = np.random.default_rng(4)
    t = np.sort(rng.uniform(0, 20, 50))
    y = -0.3 * t + rng.normal(0, 1, 50)
    mine = tr.sen_slope(t, y, 0.10)
    ref = stats.theilslopes(y, t, 0.90)
    assert mine.slope == pytest.approx(ref.slope)
    assert mine.ci_low == pytest.approx(ref.low_slope)
    assert mine.ci_high == pytest.approx(ref.high_slope)


def test_sen_exact_line_has_exact_slope_and_intercept():
    t = np.arange(20) * 0.5
    y = 7.0 + 1.5 * t
    res = tr.sen_slope(t, y)
    assert res.slope == pytest.approx(1.5)
    assert res.intercept == pytest.approx(7.0)


def test_sen_is_robust_to_an_outlier():
    t = np.arange(30) / 12.0
    y = 2.0 * t
    y[15] += 500.0
    assert tr.sen_slope(t, y).slope == pytest.approx(2.0, abs=0.05)
    assert abs(tr.linear_regression(t, y).slope - 2.0) > 1.0  # OLS is not


# ------------------------------------------------------------ seasonal tests
def _seasonal_series(years: int = 15, seed: int = 8):
    rng = np.random.default_rng(seed)
    n = years * 12
    idx = np.arange(n)
    y = 0.02 * idx / 12 + 3.0 * np.sin(2 * np.pi * idx / 12) + rng.normal(0, 0.5, n)
    return idx, y, (idx % 12) + 1


def test_seasonal_mk_matches_pymannkendall():
    _, y, season = _seasonal_series()
    mine = tr.seasonal_mann_kendall(y, season, 0.05, 3)
    ref = pmk.seasonal_test(y, period=12)
    assert mine.s == pytest.approx(ref.s)
    assert mine.var_s == pytest.approx(ref.var_s)
    assert mine.z == pytest.approx(ref.z)
    assert mine.p_value == pytest.approx(ref.p)
    assert mine.seasons_used == 12


def test_seasonal_sen_matches_pymannkendall_in_per_year_units():
    idx, y, season = _seasonal_series()
    dates = pd.date_range("2000-01-01", periods=len(idx), freq="MS")
    mine = tr.seasonal_sen_slope(to_years(dates), y, season, 0.05, 3)
    ref_slope = pmk.seasonal_sens_slope(y, period=12)[0]  # slope per seasonal cycle == per year
    assert mine.slope == pytest.approx(ref_slope, rel=0.01)


def test_seasonal_test_is_not_fooled_by_a_pure_seasonal_cycle():
    n = 15 * 12
    idx = np.arange(n)
    y = np.round(5 * np.sin(2 * np.pi * idx / 12), 6)  # strong cycle, no trend (rounded: no float noise)
    season = (idx % 12) + 1
    res = tr.seasonal_mann_kendall(y, season, 0.05, 3)
    assert res.trend == "no_clear_trend"
    assert res.s == 0  # every year repeats the same value in each month


def test_seasonal_mk_skips_seasons_with_too_few_observations():
    y = np.arange(10.0)
    season = np.array([1, 1, 1, 1, 1, 2, 2, 3, 3, 3])
    r = tr.seasonal_mann_kendall(y, season, 0.05, 3)
    assert r.seasons_used == 2 and r.seasons_total == 3  # season 2 has only two observations


def test_hamed_rao_matches_pymannkendall_and_handles_degenerate_input():
    y = ar1(120, 0.6, seed=9) + 0.01 * np.arange(120)
    mine = tr.hamed_rao(y)
    ref = pmk.hamed_rao_modification_test(y)
    assert mine is not None and mine.p_value == pytest.approx(ref.p)
    assert tr.hamed_rao(np.full(30, 1.0)) is None


# ------------------------------------------------------------ diagnostics
def test_autocorrelation_flags_ar1_but_not_white_noise():
    ac = dg.autocorrelation(ar1(200, 0.7, seed=1))
    assert ac is not None and ac.flagged and 0.5 < ac.lag1 < 0.9
    assert ac.effective_n_ar1 is not None and ac.effective_n_ar1 < 200
    white = dg.autocorrelation(np.random.default_rng(21).normal(size=200))
    assert white is not None and not white.flagged


def test_autocorrelation_needs_enough_data_and_variance():
    assert dg.autocorrelation(np.arange(5.0)) is None
    assert dg.autocorrelation(np.zeros(50)) is None


def test_seasonality_detected_for_cycle_not_for_noise():
    idx = np.arange(15 * 12)
    season = (idx % 12) + 1
    cyc = np.sin(2 * np.pi * idx / 12) + np.random.default_rng(1).normal(0, 0.2, len(idx))
    d = dg.seasonality(cyc, season)
    assert d is not None and d.detected and d.eta_squared > 0.5
    noise = dg.seasonality(np.random.default_rng(5).normal(size=len(idx)), season)
    assert noise is not None and not noise.detected


def test_benjamini_hochberg_known_example():
    adj = dg.benjamini_hochberg([0.01, 0.04, 0.03, 0.005])
    assert adj == pytest.approx([0.02, 0.04, 0.04, 0.02])
    assert all(a >= p for a, p in zip(adj, [0.01, 0.04, 0.03, 0.005]))
    assert dg.benjamini_hochberg([]) == []


# ------------------------------------------------------------ sampling
def test_detect_sampling_labels():
    assert detect_sampling(pd.Series(pd.date_range("2000-01-15", periods=24, freq="MS") + pd.Timedelta(days=14))).label == "monthly"
    assert detect_sampling(pd.Series(pd.date_range("2000-01-01", periods=60, freq="D"))).label == "daily"
    assert detect_sampling(pd.Series(pd.date_range("2000-01-01", periods=30, freq="W"))).label == "weekly"
    assert detect_sampling(pd.Series(pd.date_range("2000-01-01", periods=12, freq="QS"))).label == "quarterly"
    assert detect_sampling(pd.Series(pd.date_range("2000-01-01", periods=12, freq="YS"))).label == "annual"
    assert detect_sampling(pd.Series(pd.to_datetime(["2000-01-01", "2000-01-05"]))).label == "insufficient"


def test_detect_sampling_irregular():
    rng = np.random.default_rng(1)
    days = np.sort(rng.choice(np.arange(0, 2000), size=40, replace=False))
    s = detect_sampling(pd.Series(pd.Timestamp("2000-01-01") + pd.to_timedelta(days, unit="D")))
    assert s.label == "irregular" and not s.regular and s.period is None


def test_monthly_sampling_has_period_12_and_season_ids():
    d = pd.Series(pd.date_range("2000-01-01", periods=36, freq="MS"))
    s = detect_sampling(d)
    assert s.period == 12 and s.regular
    ids = season_ids(s, d)
    assert list(ids[:13]) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 1]


def test_grid_stats_reports_gaps_without_filling_them():
    d = pd.Series(pd.date_range("2000-01-01", periods=24, freq="MS"))
    valid = d.drop(index=[5, 6, 7, 8, 9, 15])  # 5 + 1 months missing
    g = grid_stats(detect_sampling(d), valid)
    assert g.expected_n == 24
    assert g.grid_missing == 6
    assert g.grid_missing_fraction == pytest.approx(6 / 24)
    assert g.longest_gap_steps == 5


def test_aggregate_annual_requires_coverage_and_never_interpolates():
    dates = pd.date_range("2000-01-01", periods=36, freq="MS")
    vals = np.arange(36, dtype=float)
    vals[12 + 3 :12 + 3 + 4] = np.nan  # 2001: 8 valid of 12 -> below 75 % (9 needed)
    vals[24 + 3 : 24 + 3 + 3] = np.nan  # 2002: 9 valid of 12 -> kept
    df = pd.DataFrame({"date": dates, "value": vals})
    out = aggregate(df, "annual", detect_sampling(df["date"]))
    assert out.expected_per_period == 12
    assert out.periods_dropped == 1
    f = out.frame
    assert f["value"].iloc[0] == pytest.approx(np.mean(vals[:12]))
    assert np.isnan(f["value"].iloc[1])
    assert f["value"].iloc[2] == pytest.approx(np.nanmean(vals[24:36]))


def test_aggregate_rejects_unsupported_sampling():
    df = pd.DataFrame({"date": pd.date_range("2000-01-01", periods=10, freq="YS"), "value": np.arange(10.0)})
    with pytest.raises(AppError) as exc:
        aggregate(df, "annual", detect_sampling(df["date"]))
    assert exc.value.status_code == 422


def test_canonical_df_helper_roundtrip():
    df = canonical_df([1, 2, 3])
    assert list(df.columns)[:7] == ["date", "region", "variable", "value", "unit", "data_source", "is_synthetic"]
