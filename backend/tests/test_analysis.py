"""Analysis and comparison services on small deterministic fixtures and on the bundled synthetic data."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.errors import AppError
from app.schemas import AnalyzeRequest, CompareRequest
from app.services.analysis import analyze_series, compare_regions
from app.services.store import DatasetStore

from .helpers import canonical_df, make_record, monthly_dates

DEMO = "synthetic-demo"


@pytest.fixture()
def demo(settings):
    store = DatasetStore(settings)
    store.load_all()
    return store.get(DEMO)


def req(record=None, variable="V1", region="R1", **kw) -> AnalyzeRequest:
    return AnalyzeRequest(dataset_id="fixture-id", variable=variable, region=region, **kw)


def ar1(n, phi, seed, sigma=1.0):
    rng = np.random.default_rng(seed)
    e = rng.normal(0, sigma, n)
    x = np.zeros(n)
    x[0] = e[0]
    for i in range(1, n):
        x[i] = phi * x[i - 1] + e[i]
    return x


def annual_df(values, **kw):
    return canonical_df(values, dates=pd.date_range("1960-01-01", periods=len(values), freq="YS"), **kw)


# ------------------------------------------------------------------ the demo data
def test_demo_dataset_is_flagged_synthetic_everywhere(demo):
    assert demo.status == "synthetic_demo"
    assert demo.data["is_synthetic"].all()
    assert demo.data["data_source"].str.contains("Synthetic", case=False).all()
    res = analyze_series(demo, AnalyzeRequest(dataset_id=DEMO, variable="Synthetic Index A", region="Region Alpha"))
    assert res.provenance.is_synthetic and res.provenance.status == "synthetic_demo"
    assert res.provenance.synthetic_row_fraction == 1.0
    assert "synthetic" in (res.provenance.notice or "").lower()
    assert any(w.code == "synthetic_data" for w in res.warnings)


def test_demo_file_contains_no_nasa_claims_or_coordinates(settings):
    text = settings.demo_csv_path.read_text(encoding="utf-8").lower()
    for word in ("nasa", "satellite", "modis", "landsat", "mission", "observed", "latitude", "longitude"):
        assert word not in text


def test_demo_alpha_increasing_beta_decreasing_gamma_flat(demo):
    def go(region):
        return analyze_series(demo, AnalyzeRequest(dataset_id=DEMO, variable="Synthetic Index A", region=region)).primary

    a, b, g = go("Region Alpha"), go("Region Beta"), go("Region Gamma")
    assert a.trend == "increasing" and a.significant and a.slope_per_year > 0
    assert b.trend == "decreasing" and b.significant and b.slope_per_year < 0
    assert g.trend == "no_clear_trend" and not g.significant
    assert a.slope_unit == "synthetic unit A per year"


def test_seasonal_method_is_chosen_automatically_and_labelled(demo):
    r = analyze_series(demo, AnalyzeRequest(dataset_id=DEMO, variable="Synthetic Index B", region="Region Alpha"))
    assert r.seasonality.detected and r.seasonality.method_used == "seasonal_mann_kendall"
    assert r.seasonal_mann_kendall is not None and r.seasonal_mann_kendall.seasons_used == 12
    assert "Seasonal Mann-Kendall" in r.primary.test_name
    assert "not a validated" not in r.primary.test_name
    assert r.sens_slope.method == "seasonal_sen"
    assert any(p.deseasonalized is not None for p in r.points)  # descriptive aid only
    # the plain test is still reported alongside for comparison
    assert r.mann_kendall is not None and r.mann_kendall.variant == "original"


def test_seasonality_can_be_switched_off_and_is_then_flagged(demo):
    r = analyze_series(demo, AnalyzeRequest(dataset_id=DEMO, variable="Synthetic Index B", region="Region Alpha", seasonality="none"))
    assert r.seasonality.method_used == "none" and r.seasonal_mann_kendall is None
    assert r.primary.test_name.startswith("Mann-Kendall")
    assert any(w.code == "seasonality_ignored" for w in r.warnings)


def test_seasonal_requested_for_annual_data_falls_back_with_a_warning(demo):
    r = analyze_series(demo, AnalyzeRequest(dataset_id=DEMO, variable="Synthetic Index C", region="Region Gamma", seasonality="seasonal"))
    assert r.sampling.label == "annual" and r.sampling.seasonal_period is None
    assert r.seasonal_mann_kendall is None
    assert any(w.code == "seasonal_unavailable" for w in r.warnings)


def test_missing_values_are_reported_and_never_filled(demo):
    r = analyze_series(demo, AnalyzeRequest(dataset_id=DEMO, variable="Synthetic Index A", region="Region Gamma"))
    assert r.coverage.n_rows == 288 and r.coverage.n_missing_values == 12 and r.coverage.n_valid == 276
    assert r.sampling.grid_missing == 12 and r.sampling.longest_gap_steps == 12
    blanks = [p for p in r.points if p.value is None]
    assert len(blanks) == 12  # kept as gaps in the chart data, not zero
    assert any(w.code == "missing_values" for w in r.warnings)
    assert r.linear_regression.n == 276
    # gaps => HAC / Hamed-Rao need a gap-free grid and are therefore not offered
    assert r.mann_kendall_hamed_rao is None and r.linear_regression_hac is None


def test_annual_aggregation_of_monthly_data(demo):
    r = analyze_series(demo, AnalyzeRequest(dataset_id=DEMO, variable="Synthetic Index A", region="Region Alpha", aggregation="annual"))
    assert r.aggregation.method == "annual" and r.aggregation.native_sampling == "monthly"
    assert r.sampling.label == "annual" and r.coverage.n_valid == 24
    assert r.seasonality.assessed is False
    assert all(p.n_in_period == 12 for p in r.points)
    assert r.primary.trend == "increasing"
    assert r.primary.slope_per_year == pytest.approx(0.06, abs=0.03)  # still per YEAR after aggregation


def test_date_range_filter_is_inclusive_and_changes_the_sample(demo):
    full = analyze_series(demo, AnalyzeRequest(dataset_id=DEMO, variable="Synthetic Index A", region="Region Alpha"))
    sub = analyze_series(
        demo,
        AnalyzeRequest(dataset_id=DEMO, variable="Synthetic Index A", region="Region Alpha", start="2010-01-01", end="2014-12-01"),
    )
    assert full.coverage.n_valid == 288 and sub.coverage.n_valid == 60
    assert sub.coverage.first_date == "2010-01-01" and sub.coverage.last_date == "2014-12-01"


def test_alpha_controls_confidence_level(demo):
    a = analyze_series(demo, AnalyzeRequest(dataset_id=DEMO, variable="Synthetic Index A", region="Region Alpha", alpha=0.01))
    b = analyze_series(demo, AnalyzeRequest(dataset_id=DEMO, variable="Synthetic Index A", region="Region Alpha", alpha=0.10))
    assert a.linear_regression.confidence_level == pytest.approx(0.99)
    assert (a.linear_regression.ci_high - a.linear_regression.ci_low) > (b.linear_regression.ci_high - b.linear_regression.ci_low)


# --------------------------------------------------------------- selection errors
def test_unknown_selections_raise_404(demo):
    for kw, code in [
        ({"variable": "Nope", "region": "Region Alpha"}, "variable_not_found"),
        ({"variable": "Synthetic Index A", "region": "Nowhere"}, "series_not_found"),
    ]:
        with pytest.raises(AppError) as exc:
            analyze_series(demo, AnalyzeRequest(dataset_id=DEMO, **kw))
        assert exc.value.status_code == 404 and exc.value.code == code


def test_invalid_and_empty_date_ranges(demo):
    base = dict(dataset_id=DEMO, variable="Synthetic Index A", region="Region Alpha")
    with pytest.raises(AppError) as e1:
        analyze_series(demo, AnalyzeRequest(**base, start="2020-01-01", end="2010-01-01"))
    assert e1.value.code == "invalid_date_range"
    with pytest.raises(AppError) as e2:
        analyze_series(demo, AnalyzeRequest(**base, start="1990-01-01", end="1991-01-01"))
    assert e2.value.code == "no_rows_in_range"


def test_all_missing_selection_raises_clear_error():
    rec = make_record(canonical_df([np.nan] * 20))
    with pytest.raises(AppError) as exc:
        analyze_series(rec, req())
    assert exc.value.code == "no_valid_observations"


def test_mixed_units_in_a_series_refuse_to_analyse():
    df = canonical_df(np.arange(24.0))
    df.loc[3, "unit"] = "other"
    with pytest.raises(AppError) as exc:
        analyze_series(make_record(df), req())
    assert exc.value.code == "mixed_units" and exc.value.status_code == 422


# ---------------------------------------------------------- limited / odd data
def test_too_few_observations_gives_no_trend_claim():
    r = analyze_series(make_record(canonical_df([1, 2, 3, 4, 5, 6])), req())
    assert r.primary.available is False and r.primary.trend == "insufficient_data" and r.primary.p_value is None
    assert r.mann_kendall is None and r.sens_slope is None
    assert r.linear_regression is not None  # n >= 5 still allows a descriptive fit
    assert any(w.code == "insufficient_data" for w in r.warnings)
    assert r.explanation and "No trend test could be run" in " ".join(s.text for sec in r.explanation.sections for s in sec.statements)


def test_three_points_run_nothing():
    r = analyze_series(make_record(canonical_df([1, 2, 3])), req())
    assert r.linear_regression is None and r.mann_kendall is None and not r.primary.available


def test_irregular_timestamps_use_real_time_for_slopes():
    rng = np.random.default_rng(3)
    days = np.sort(rng.choice(np.arange(0, 6000), size=60, replace=False))
    dates = pd.Timestamp("2000-01-01") + pd.to_timedelta(days, unit="D")
    t = (dates - dates[0]).total_seconds().to_numpy() / (86400 * 365.25)
    r = analyze_series(make_record(canonical_df(2.0 * t, dates=dates)), req())
    assert r.sampling.label == "irregular"
    assert r.primary.slope_per_year == pytest.approx(2.0)
    assert r.linear_regression.slope_per_year == pytest.approx(2.0)
    assert r.autocorrelation.evaluated is False and "irregular" in r.autocorrelation.reason_not_evaluated.lower()
    assert r.primary.status == "exploratory_uncorrected"  # cannot be assessed -> not presented as confirmed
    assert any(w.code == "irregular_sampling" for w in r.warnings)


def test_seasonal_requires_enough_cycles():
    n = 24  # two years of monthly data
    y = 3 * np.sin(2 * np.pi * np.arange(n) / 12) + np.arange(n) * 0.01
    r = analyze_series(make_record(canonical_df(y)), req())
    assert r.seasonality.assessed is False and r.seasonality.method_used == "none"


# ---------------------------------------------------- autocorrelation handling
def test_autocorrelated_annual_series_uses_hamed_rao_correction():
    y = ar1(80, 0.75, seed=12) + 0.02 * np.arange(80)
    r = analyze_series(make_record(annual_df(y)), req())
    assert r.autocorrelation.evaluated and r.autocorrelation.flagged
    assert r.primary.status == "autocorrelation_corrected"
    assert "Hamed" in r.primary.test_name
    assert r.mann_kendall_hamed_rao is not None
    # the correction must make the evidence weaker than the naive test, never stronger
    assert r.mann_kendall_hamed_rao.p_value >= r.mann_kendall.p_value
    assert r.autocorrelation.correction_applied and r.autocorrelation.correction_method


def test_white_noise_series_is_standard_status():
    y = np.random.default_rng(31).normal(size=80)
    r = analyze_series(make_record(annual_df(y)), req())
    assert r.autocorrelation.evaluated and r.autocorrelation.flagged is False
    assert r.primary.status == "standard" and r.primary.trend == "no_clear_trend"


def test_gappy_autocorrelated_series_is_exploratory_not_corrected():
    y = ar1(80, 0.75, seed=12) + 0.02 * np.arange(80)
    y[30:36] = np.nan
    r = analyze_series(make_record(annual_df(y)), req())
    assert r.autocorrelation.evaluated and r.autocorrelation.approximate
    assert r.primary.status == "exploratory_uncorrected"
    assert any(w.code == "autocorrelation_uncorrected" for w in r.warnings)
    assert r.mann_kendall_hamed_rao is None


def test_hac_regression_is_offered_for_long_gap_free_regular_series():
    y = ar1(120, 0.6, seed=2) + 0.01 * np.arange(120)
    r = analyze_series(make_record(annual_df(y)), req())
    assert r.linear_regression_hac is not None
    assert r.linear_regression_hac.std_err > r.linear_regression.std_err


# ---------------------------------------------------------------- comparison
def test_compare_finds_opposite_directions_in_demo_data(demo):
    c = compare_regions(
        demo, CompareRequest(dataset_id=DEMO, variable="Synthetic Index A", regions=["Region Alpha", "Region Beta"])
    )
    assert c.comparable and c.unit == "synthetic unit A"
    assert c.direction_summary == "opposite_directions"
    dirs = {r.region: r.estimated_direction for r in c.rows}
    assert dirs == {"Region Alpha": "increasing", "Region Beta": "decreasing"}
    assert c.n_tests == 2 and c.provenance.is_synthetic
    for row in c.rows:
        assert row.p_value_adjusted_bh >= row.p_value
        assert row.n_valid == 288 and row.sampling == "monthly"
    assert c.explanation is not None


def test_compare_same_direction_summary():
    a = canonical_df(np.arange(60.0) + np.random.default_rng(1).normal(0, 1, 60), region="A")
    b = canonical_df(2 * np.arange(60.0) + np.random.default_rng(2).normal(0, 1, 60), region="B")
    rec = make_record(pd.concat([a, b], ignore_index=True))
    c = compare_regions(rec, CompareRequest(dataset_id="fixture-id", variable="V1", regions=["A", "B"]))
    assert c.direction_summary == "same_direction"


def test_compare_warns_about_mixed_resolution_and_coverage(demo):
    c = compare_regions(
        demo,
        CompareRequest(dataset_id=DEMO, variable="Synthetic Index C", regions=["Region Alpha", "Region Beta", "Region Gamma"]),
    )
    codes = {w.code for w in c.warnings}
    assert {"sampling_mismatch", "coverage_mismatch", "sample_size_mismatch"} <= codes
    assert c.comparable  # same unit, so numbers are comparable; the warnings explain the caveats


def test_compare_refuses_to_compare_different_units():
    a = canonical_df(np.arange(40.0), region="A", unit="degC")
    b = canonical_df(np.arange(40.0), region="B", unit="K")
    rec = make_record(pd.concat([a, b], ignore_index=True))
    c = compare_regions(rec, CompareRequest(dataset_id="fixture-id", variable="V1", regions=["A", "B"]))
    assert c.comparable is False and c.unit is None
    assert c.direction_summary == "mixed_or_insufficient"
    assert any(w.code == "incompatible_units" for w in c.warnings)
    text = " ".join(s.text for sec in c.explanation.sections for s in sec.statements)
    assert "different units" in text and "No unit conversion" in text


def test_compare_flags_regions_with_insufficient_data():
    a = canonical_df(np.arange(40.0), region="A")
    b = canonical_df([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], region="B")
    rec = make_record(pd.concat([a, b], ignore_index=True))
    c = compare_regions(rec, CompareRequest(dataset_id="fixture-id", variable="V1", regions=["A", "B"]))
    row_b = next(r for r in c.rows if r.region == "B")
    assert row_b.trend == "insufficient_data" and row_b.p_value is None and row_b.p_value_adjusted_bh is None
    assert c.n_tests == 1 and c.direction_summary == "mixed_or_insufficient"


def test_compare_unknown_region_is_404(demo):
    with pytest.raises(AppError) as exc:
        compare_regions(demo, CompareRequest(dataset_id=DEMO, variable="Synthetic Index A", regions=["Region Alpha", "Atlantis"]))
    assert exc.value.status_code == 404 and "Atlantis" in exc.value.message


def test_compare_request_validation():
    with pytest.raises(ValueError):
        CompareRequest(dataset_id="d", variable="v", regions=["only-one"])
    with pytest.raises(ValueError):
        CompareRequest(dataset_id="d", variable="v", regions=["a", "a"])


def test_monthly_dates_helper_is_monthly():
    assert len(monthly_dates(n=24)) == 24
