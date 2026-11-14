"""Trend analysis and regional comparison orchestration.

This module selects a series from a dataset, decides which statistical procedures are
appropriate for the sampling that is actually present, runs them, and packages the
results with provenance and caveats. It never fabricates or interpolates values.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from app.errors import AppError, not_found, unprocessable
from app.schemas import (
    AggregationInfo,
    AnalysisWarning,
    AnalyzeRequest,
    AnalyzeResponse,
    AutocorrelationResult,
    CompareRequest,
    CompareResponse,
    CoverageInfo,
    HacRegressionResult,
    LinearRegressionResult,
    MannKendallResult,
    PrimaryResult,
    RegionComparisonRow,
    SamplingInfo,
    SenSlopeResult,
    SeriesPoint,
    SeasonalityResult,
)
from app.services.provenance import build_provenance
from app.services.stats import diagnostics as diag
from app.services.stats import trend as tr
from app.services.stats.constants import (
    GAP_WARN_FRACTION,
    MAX_N_MK,
    MAX_N_PAIRWISE,
    MIN_CYCLES,
    MIN_N_AUTOCORR,
    MIN_N_HAC,
    MIN_N_REGRESSION,
    MIN_N_TREND,
    MIN_PER_SEASON,
    MIN_SEASONS_FRACTION,
)
from app.services.stats.sampling import (
    aggregate,
    detect_sampling,
    grid_stats,
    season_ids,
    to_years,
)
from app.services.store import DatasetRecord

SEASONAL_NAME = "Seasonal Mann-Kendall (Hirsch et al. 1982; seasons treated as independent)"
HR_NAME = "Mann-Kendall with Hamed & Rao (1998) autocorrelation correction"
MK_NAME = "Mann-Kendall trend test (normal approximation, tie-corrected)"

STANDARD_ASSUMPTIONS = [
    "Time is computed from the actual timestamps and expressed in years of 365.25 days; rows are never assumed to be evenly spaced.",
    "Missing observations are excluded and reported. They are never interpolated or replaced by zero.",
    "Mann-Kendall assumes independent observations. Positive autocorrelation makes the plain test too eager to report a trend; the autocorrelation check in the results says whether that is a concern.",
    "Ordinary least squares is a descriptive straight-line fit. It assumes a linear trend and independent, equal-variance residuals, and can miss non-linear behaviour.",
    "Sen's slope is the median of pairwise slopes; it is robust to outliers but still describes a single straight-line rate of change.",
    "A statistically significant monotonic trend is not evidence of cause. Confounding factors, instrument or sampling changes are not assessed here.",
]


def _f(x: float | None) -> float | None:
    return None if x is None or not math.isfinite(x) else float(x)


def _iso(ts: pd.Timestamp) -> str:
    return ts.strftime("%Y-%m-%d")


# --------------------------------------------------------------------------
# Series selection
# --------------------------------------------------------------------------
def require_variable(record: DatasetRecord, variable: str) -> pd.DataFrame:
    sub = record.data[record.data["variable"] == variable]
    if sub.empty:
        raise not_found("variable_not_found", f"Variable '{variable}' does not exist in dataset '{record.name}'.")
    return sub


def select_series(record: DatasetRecord, variable: str, region: str, start, end) -> pd.DataFrame:
    var_rows = require_variable(record, variable)
    sub = var_rows[var_rows["region"] == region]
    if sub.empty:
        raise not_found("series_not_found", f"Region '{region}' has no data for variable '{variable}' in this dataset.")
    if start is not None and end is not None and start > end:
        raise unprocessable("invalid_date_range", "The start date must not be after the end date.")
    if start is not None:
        sub = sub[sub["date"] >= pd.Timestamp(start)]
    if end is not None:
        sub = sub[sub["date"] < pd.Timestamp(end) + pd.Timedelta(days=1)]
    if sub.empty:
        raise unprocessable("no_rows_in_range", "No observations fall inside the selected date range.")
    return sub.sort_values("date")


# --------------------------------------------------------------------------
# Single-series analysis
# --------------------------------------------------------------------------
def analyze_series(record: DatasetRecord, req: AnalyzeRequest, with_explanation: bool = True) -> AnalyzeResponse:
    from app.services.explain import explain_analysis  # local import avoids a cycle

    sub = select_series(record, req.variable, req.region, req.start, req.end)
    units = sorted(sub["unit"].dropna().unique().tolist())
    if len(units) != 1:
        raise unprocessable(
            "mixed_units",
            f"The selected series contains more than one unit ({', '.join(units)}). "
            "No unit conversion is performed, so it cannot be analysed as one series.",
        )
    unit = units[0]
    provenance = build_provenance(record, sub)
    alpha = req.alpha
    cl = 1 - alpha

    series = sub[["date", "value"]].reset_index(drop=True)
    native = detect_sampling(series["date"])
    agg_info = AggregationInfo(method="none", native_sampling=native.label)
    warnings: list[AnalysisWarning] = []
    assumptions = list(STANDARD_ASSUMPTIONS)

    n_in_period = None
    if req.aggregation != "none":
        out = aggregate(series, req.aggregation, native)
        series = out.frame.reset_index(drop=True)
        n_in_period = series["n_in_period"].to_numpy()
        agg_info = AggregationInfo(
            method=req.aggregation,
            native_sampling=native.label,
            expected_per_period=out.expected_per_period,
            min_coverage=0.75,
            periods_total=out.periods_total,
            periods_dropped_low_coverage=out.periods_dropped,
            note=out.note,
        )
        assumptions.append(out.note)
        if out.periods_dropped:
            warnings.append(
                AnalysisWarning(
                    code="aggregation_periods_dropped",
                    message=f"{out.periods_dropped} of {out.periods_total} periods had too little coverage to be aggregated and were left missing.",
                )
            )
        sampling = detect_sampling(series["date"])
    else:
        sampling = native

    valid = series[series["value"].notna()].reset_index(drop=True)
    n = len(valid)
    n_rows = len(series)
    if n == 0:
        raise unprocessable("no_valid_observations", "The selection contains no valid (non-missing) observations.")

    first, last = valid["date"].iloc[0], valid["date"].iloc[-1]
    span_years = float((last - first).total_seconds() / (86400 * 365.25))
    grid = grid_stats(sampling, valid["date"])
    coverage = CoverageInfo(
        n_rows=n_rows,
        n_missing_values=n_rows - n,
        n_valid=n,
        first_date=_iso(first),
        last_date=_iso(last),
        span_years=_f(span_years),
    )
    sampling_info = SamplingInfo(
        label=sampling.label,  # type: ignore[arg-type]
        median_step_days=_f(sampling.median_step_days),
        regular=sampling.regular,
        seasonal_period=sampling.period,
        expected_n=grid.expected_n,
        grid_missing=grid.grid_missing,
        grid_missing_fraction=_f(grid.grid_missing_fraction),
        longest_gap_steps=grid.longest_gap_steps,
    )

    # ---- warnings about the data themselves ----
    if provenance.is_synthetic:
        warnings.append(
            AnalysisWarning(
                code="synthetic_data",
                message="Synthetic demo data: these results describe artificial numbers and are not scientific findings.",
            )
        )
    if n_rows - n:
        warnings.append(
            AnalysisWarning(
                code="missing_values",
                message=f"{n_rows - n} of {n_rows} records have no value; they were excluded and not filled in.",
            )
        )
    if sampling.label == "irregular":
        warnings.append(
            AnalysisWarning(
                code="irregular_sampling",
                message="Sampling is irregular. Slopes use the real time differences, but lag-based diagnostics and seasonal tests are not available.",
            )
        )
    if grid.grid_missing_fraction is not None and grid.grid_missing_fraction > GAP_WARN_FRACTION:
        warnings.append(
            AnalysisWarning(
                code="grid_gaps",
                message=(
                    f"{grid.grid_missing} of {grid.expected_n} expected {sampling.label} steps "
                    f"({grid.grid_missing_fraction:.0%}) have no valid value; the longest gap is {grid.longest_gap_steps} steps."
                ),
            )
        )
    if n < MIN_N_TREND:
        warnings.append(
            AnalysisWarning(
                code="insufficient_data",
                message=f"Only {n} valid observations. Trend tests need at least {MIN_N_TREND}; results are not shown as evidence.",
            )
        )
    elif n < 30:
        warnings.append(
            AnalysisWarning(code="limited_data", message=f"Only {n} valid observations; statistical power is limited.")
        )

    # ---- time axis ----
    origin = valid["date"].iloc[0]
    t = to_years(valid["date"], origin)
    y = valid["value"].to_numpy(dtype="float64")
    t_all = to_years(series["date"], origin)

    # ---- OLS ----
    ols = tr.linear_regression(t, y, alpha) if n >= MIN_N_REGRESSION else None
    ols_model = (
        LinearRegressionResult(
            slope_per_year=ols.slope,
            intercept=ols.intercept,
            intercept_at=_iso(origin),
            std_err=ols.std_err,
            ci_low=ols.ci_low,
            ci_high=ols.ci_high,
            confidence_level=cl,
            p_value=ols.p_value,
            r_squared=ols.r_squared,
            n=ols.n,
            df=ols.df,
            significant=ols.p_value < alpha,
        )
        if ols
        else None
    )

    # ---- rank-based tests ----
    mk = sen = None
    can_mk = n >= MIN_N_TREND
    if can_mk and n > MAX_N_MK:
        can_mk = False
        warnings.append(
            AnalysisWarning(
                code="series_too_long",
                message=f"{n} observations exceed the {MAX_N_MK} that the exact Mann-Kendall computation supports. Aggregate to quarterly or annual values.",
            )
        )
    if can_mk:
        mk = tr.mann_kendall(y, alpha)
        if n <= MAX_N_PAIRWISE:
            sen = tr.sen_slope(t, y, alpha)
        else:
            warnings.append(
                AnalysisWarning(
                    code="sen_unavailable",
                    message=f"Sen's slope needs all pairwise slopes and is limited to {MAX_N_PAIRWISE} observations; the OLS slope is used instead.",
                )
            )

    # ---- seasonality ----
    season = season_ids(sampling, valid["date"])
    n_cycles = (n / sampling.period) if sampling.period else None
    season_diag = None
    season_component: dict[int, float] | None = None
    can_seasonal = False
    if season is not None and can_mk and n_cycles is not None and n_cycles >= MIN_CYCLES:
        groups, total_seasons = tr.season_groups(season, MIN_PER_SEASON)
        can_seasonal = len(groups) >= math.ceil(MIN_SEASONS_FRACTION * (sampling.period or 1)) and len(groups) >= 2
        base_slope, base_icpt = (sen.slope, sen.intercept) if sen else ((ols.slope, ols.intercept) if ols else (None, None))
        if base_slope is not None:
            resid0 = y - (base_icpt + base_slope * t)
            season_diag = diag.seasonality(resid0, season)
            if season_diag is not None:
                means = diag.season_means(resid0, season)
                center = float(np.mean(list(means.values())))
                season_component = {s: m - center for s, m in means.items()}

    seasonal_note = ""
    use_seasonal = False
    if req.seasonality == "seasonal":
        if can_seasonal:
            use_seasonal = True
        else:
            seasonal_note = "A seasonal analysis was requested but is not possible for this series"
            seasonal_note += (
                " (sampling has no defined seasonal cycle)."
                if sampling.period is None
                else f" (needs at least {MIN_CYCLES} cycles and enough observations per season)."
            )
            warnings.append(AnalysisWarning(code="seasonal_unavailable", message=seasonal_note + " The non-seasonal test was used."))
    elif req.seasonality == "auto":
        if season_diag is not None and season_diag.detected and can_seasonal:
            use_seasonal = True
    # req.seasonality == "none": never seasonal

    smk = sen_s = None
    if use_seasonal:
        smk = tr.seasonal_mann_kendall(y, season, alpha, MIN_PER_SEASON)
        try:
            sen_s = tr.seasonal_sen_slope(t, y, season, alpha, MIN_PER_SEASON)
        except ValueError:
            sen_s = None

    if season_diag is not None:
        detected = season_diag.detected
        if use_seasonal:
            note = (
                f"Seasonality detected (Kruskal-Wallis p = {season_diag.kruskal_p:.3g}; month-of-year explains "
                f"{season_diag.eta_squared:.0%} of detrended variance). The seasonal Mann-Kendall test and seasonal Sen's slope were used."
            )
        elif detected and req.seasonality == "none":
            note = "Seasonality was detected but the non-seasonal test was selected by request; the trend test ignores the seasonal cycle."
            warnings.append(AnalysisWarning(code="seasonality_ignored", message=note))
        elif detected:
            note = "Seasonality was detected but the series is too sparse for the seasonal test; the non-seasonal test was used."
            warnings.append(AnalysisWarning(code="seasonality_unaccounted", message=note))
        else:
            note = (
                f"No significant seasonal pattern detected (Kruskal-Wallis p = {season_diag.kruskal_p:.3g}); "
                "the non-seasonal test was used."
            )
        season_res = SeasonalityResult(
            period=sampling.period,
            assessed=True,
            detected=detected,
            method_used="seasonal_mann_kendall" if use_seasonal else "none",
            kruskal_p=_f(season_diag.kruskal_p),
            eta_squared=_f(season_diag.eta_squared),
            n_cycles=_f(n_cycles),
            note=note,
        )
    else:
        if sampling.period is None:
            why = f"Sampling is {sampling.label}, which has no seasonal cycle defined in this app."
        elif n < MIN_N_TREND:
            why = "Too few observations to assess seasonality."
        else:
            why = f"Fewer than {MIN_CYCLES} full seasonal cycles are available."
        season_res = SeasonalityResult(
            period=sampling.period, assessed=False, detected=False, method_used="none", n_cycles=_f(n_cycles), note=why
        )

    # ---- autocorrelation diagnostics ----
    resid = None
    basis = None
    line = sen_s if (use_seasonal and sen_s) else sen
    if line is not None:
        resid = y - (line.intercept + line.slope * t)
        basis = "residuals of Sen's slope line"
    elif ols is not None:
        resid = y - (ols.intercept + ols.slope * t)
        basis = "residuals of the OLS line"
    if resid is not None and use_seasonal and season is not None:
        means = diag.season_means(resid, season)
        resid = resid - np.array([means[int(s)] for s in season])
        basis += " after removing season means"

    ac = AutocorrelationResult(evaluated=False, reason_not_evaluated="Too few observations.")
    ac_diag = None
    if resid is not None and n >= MIN_N_AUTOCORR:
        if not sampling.regular:
            ac = AutocorrelationResult(
                evaluated=False,
                reason_not_evaluated="Sampling is irregular; lag-based diagnostics assume equally spaced observations.",
            )
        else:
            ac_diag = diag.autocorrelation(resid)
            if ac_diag is None:
                ac = AutocorrelationResult(evaluated=False, reason_not_evaluated="The residuals have no variance.")
            else:
                approx = bool(grid.grid_missing)
                ac = AutocorrelationResult(
                    evaluated=True,
                    residual_basis=basis,
                    lag1=_f(ac_diag.lag1),
                    durbin_watson=_f(ac_diag.durbin_watson),
                    ljung_box_lags=ac_diag.ljung_box_lags,
                    ljung_box_p=_f(ac_diag.ljung_box_p),
                    flagged=ac_diag.flagged,
                    effective_n_ar1=_f(ac_diag.effective_n_ar1),
                    approximate=approx,
                    note=(
                        "Observations with gaps are treated as adjacent, so these diagnostics are approximate."
                        if approx
                        else None
                    ),
                )

    # ---- autocorrelation-aware variants ----
    complete_regular = sampling.regular and grid.grid_missing == 0
    hr = None
    if mk is not None and not use_seasonal and complete_regular:
        hr = tr.hamed_rao(y, alpha)
    hac = None
    if ols is not None and complete_regular and n >= MIN_N_HAC:
        hac = tr.ols_hac(t, y, alpha)

    # ---- primary result ----
    slope_unit = f"{unit} per year"
    primary = _primary(
        n=n,
        alpha=alpha,
        unit=unit,
        slope_unit=slope_unit,
        span_years=span_years,
        mk=mk,
        smk=smk,
        hr=hr,
        sen=sen,
        sen_s=sen_s,
        ols=ols,
        use_seasonal=use_seasonal,
        ac=ac,
    )
    if primary.status == "exploratory_uncorrected" and primary.available:
        if ac.evaluated and ac.flagged:
            warnings.append(
                AnalysisWarning(
                    code="autocorrelation_uncorrected",
                    message="Autocorrelation was assessed and is significant in the residuals, but it was not corrected: "
                    + (
                        "the Hamed-Rao correction is not available for the seasonal analysis path."
                        if use_seasonal
                        else "no valid correction is available for this series."
                    )
                    + " The p-value is likely too small; treat the result as exploratory."
                    + (
                        " Aggregating to annual values removes the seasonal cycle and enables the autocorrelation-corrected test."
                        if sampling.period is not None and req.aggregation == "none"
                        else ""
                    ),
                )
            )
        elif not ac.evaluated:
            warnings.append(
                AnalysisWarning(
                    code="autocorrelation_unknown",
                    message="Autocorrelation could not be assessed, so the p-value is an uncorrected, exploratory value.",
                )
            )
    if ac.evaluated:
        ac.correction_applied = primary.status == "autocorrelation_corrected"
        ac.correction_method = HR_NAME if ac.correction_applied else None

    # ---- points for charts ----
    fitted_line = None
    if line is not None:
        fitted_line = (line.intercept, line.slope)
    elif ols is not None:
        fitted_line = (ols.intercept, ols.slope)
    points = _points(series, t_all, ols, fitted_line, season_component if (use_seasonal or (season_diag and season_diag.detected)) else None, sampling, n_in_period)

    result = AnalyzeResponse(
        provenance=provenance,
        request=req,
        unit=unit,
        sampling=sampling_info,
        coverage=coverage,
        aggregation=agg_info,
        points=points,
        linear_regression=ols_model,
        linear_regression_hac=(
            HacRegressionResult(
                slope_per_year=hac.slope,
                std_err=hac.std_err,
                ci_low=hac.ci_low,
                ci_high=hac.ci_high,
                p_value=hac.p_value,
                maxlags=hac.maxlags,
                significant=hac.p_value < alpha,
            )
            if hac
            else None
        ),
        mann_kendall=_mk_model(mk, "original", MK_NAME, alpha),
        seasonal_mann_kendall=_mk_model(smk, "seasonal", SEASONAL_NAME, alpha),
        mann_kendall_hamed_rao=_mk_model(hr, "hamed_rao", HR_NAME, alpha),
        sens_slope=_sen_model(sen_s if use_seasonal and sen_s else sen, use_seasonal and sen_s is not None, cl, alpha),
        autocorrelation=ac,
        seasonality=season_res,
        primary=primary,
        warnings=warnings,
        assumptions=assumptions,
    )
    if with_explanation:
        result.explanation = explain_analysis(result)
    return result


def _mk_model(r: tr.MKResult | None, variant: str, name: str, alpha: float) -> MannKendallResult | None:
    if r is None:
        return None
    notes: list[str] = []
    if variant == "seasonal":
        notes.append("Per-season S and Var(S) are summed; seasons are treated as independent.")
    if variant == "hamed_rao":
        notes.append("Variance is inflated using significant autocorrelations of the detrended ranks; valid for gap-free, equally spaced data.")
    return MannKendallResult(
        variant=variant,  # type: ignore[arg-type]
        test_name=name,
        s=r.s,
        var_s=r.var_s,
        z=r.z,
        p_value=r.p_value,
        tau=r.tau,
        n=r.n,
        trend=r.trend,  # type: ignore[arg-type]
        significant=r.significant,
        alpha=alpha,
        seasons_used=r.seasons_used,
        seasons_total=r.seasons_total,
        notes=notes,
    )


def _sen_model(s: tr.SenResult | None, seasonal: bool, cl: float, alpha: float) -> SenSlopeResult | None:
    if s is None:
        return None
    lo, hi = s.ci_low, s.ci_high
    return SenSlopeResult(
        method="seasonal_sen" if seasonal else "sen",
        method_name="Seasonal Sen's slope (median of within-season pairwise slopes)" if seasonal else "Sen's slope (median of pairwise slopes)",
        slope_per_year=s.slope,
        ci_low=lo,
        ci_high=hi,
        intercept=s.intercept,
        confidence_level=cl,
        n_pairs=s.n_pairs,
        ci_excludes_zero=(None if lo is None or hi is None else bool(lo > 0 or hi < 0)),
    )


def _direction(slope: float | None) -> str:
    if slope is None:
        return "unknown"
    if slope > 0:
        return "increasing"
    if slope < 0:
        return "decreasing"
    return "flat"


def _primary(*, n, alpha, unit, slope_unit, span_years, mk, smk, hr, sen, sen_s, ols, use_seasonal, ac) -> PrimaryResult:
    if mk is None:
        reason = (
            f"Only {n} valid observations; at least {MIN_N_TREND} are required for the trend tests."
            if n < MIN_N_TREND
            else "The Mann-Kendall computation is not available for this series length."
        )
        return PrimaryResult(
            available=False,
            status="insufficient_data",
            trend="insufficient_data",
            estimated_direction="unknown",
            test_name=None,
            p_value=None,
            alpha=alpha,
            significant=None,
            slope_per_year=None,
            slope_ci_low=None,
            slope_ci_high=None,
            slope_method=None,
            unit=unit,
            slope_unit=slope_unit,
            total_change_over_period=None,
            reason=reason,
        )

    flagged = ac.flagged if ac.evaluated else None
    if use_seasonal and smk is not None:
        test, test_name = smk, SEASONAL_NAME
        status = "standard" if flagged is False else "exploratory_uncorrected"
        line = sen_s
    else:
        test, test_name, line = mk, MK_NAME, sen
        if flagged is False:
            status = "standard"
        elif flagged and hr is not None:
            test, test_name, status = hr, HR_NAME, "autocorrelation_corrected"
        else:
            status = "exploratory_uncorrected"

    if line is not None:
        slope, lo, hi = line.slope, line.ci_low, line.ci_high
        method = "Seasonal Sen's slope" if use_seasonal and sen_s is not None else "Sen's slope"
    elif ols is not None:
        slope, lo, hi, method = ols.slope, ols.ci_low, ols.ci_high, "OLS slope (Sen's slope unavailable)"
    else:
        slope = lo = hi = None
        method = None
    return PrimaryResult(
        available=True,
        status=status,  # type: ignore[arg-type]
        trend=test.trend,  # type: ignore[arg-type]
        estimated_direction=_direction(slope),  # type: ignore[arg-type]
        test_name=test_name,
        p_value=test.p_value,
        alpha=alpha,
        significant=test.significant,
        slope_per_year=_f(slope),
        slope_ci_low=_f(lo),
        slope_ci_high=_f(hi),
        slope_method=method,
        unit=unit,
        slope_unit=slope_unit,
        total_change_over_period=_f(slope * span_years) if slope is not None else None,
    )


def _points(series, t_all, ols, line, season_component, sampling, n_in_period) -> list[SeriesPoint]:
    dates = series["date"]
    has_time = bool((dates != dates.dt.normalize()).any())
    fmt = "%Y-%m-%dT%H:%M:%S" if has_time else "%Y-%m-%d"
    iso = dates.dt.strftime(fmt).tolist()
    vals = series["value"].to_numpy(dtype="float64")
    ols_fit = (ols.intercept + ols.slope * t_all) if ols else None
    sen_fit = (line[0] + line[1] * t_all) if line else None
    season = season_ids(sampling, dates) if season_component is not None else None
    points: list[SeriesPoint] = []
    for i in range(len(series)):
        v = _f(vals[i])
        deseason = None
        if season is not None and v is not None:
            deseason = _f(v - season_component.get(int(season[i]), 0.0))
        points.append(
            SeriesPoint(
                date=iso[i],
                value=v,
                fitted_ols=_f(ols_fit[i]) if ols_fit is not None else None,
                fitted_sen=_f(sen_fit[i]) if sen_fit is not None else None,
                deseasonalized=deseason,
                n_in_period=int(n_in_period[i]) if n_in_period is not None else None,
            )
        )
    return points


# --------------------------------------------------------------------------
# Regional comparison
# --------------------------------------------------------------------------
def compare_regions(record: DatasetRecord, req: CompareRequest, with_explanation: bool = True) -> CompareResponse:
    from app.services.explain import explain_comparison

    var_rows = require_variable(record, req.variable)
    known = set(var_rows["region"].unique())
    missing = [r for r in req.regions if r not in known]
    if missing:
        raise not_found("region_not_found", f"No data for variable '{req.variable}' in region(s): {', '.join(missing)}.")

    results: list[AnalyzeResponse] = []
    for region in req.regions:
        results.append(
            analyze_series(
                record,
                AnalyzeRequest(
                    dataset_id=req.dataset_id,
                    variable=req.variable,
                    region=region,
                    start=req.start,
                    end=req.end,
                    aggregation=req.aggregation,
                    seasonality=req.seasonality,
                    alpha=req.alpha,
                ),
                with_explanation=False,
            )
        )

    units_by_region = {r.request.region: r.unit for r in results}
    unit_set = sorted(set(units_by_region.values()))
    comparable = len(unit_set) == 1
    warnings: list[AnalysisWarning] = []
    if not comparable:
        warnings.append(
            AnalysisWarning(
                code="incompatible_units",
                message="The regions report this variable in different units "
                f"({'; '.join(f'{k}: {v}' for k, v in units_by_region.items())}). "
                "No conversion is applied, so the regions are not plotted on a common axis and are not compared.",
            )
        )

    labels = {r.sampling.label for r in results}
    if len(labels) > 1:
        warnings.append(
            AnalysisWarning(
                code="sampling_mismatch",
                message="The regions are sampled at different temporal resolutions ("
                + "; ".join(f"{r.request.region}: {r.sampling.label}" for r in results)
                + "). Trend statistics are not directly comparable without aggregating to a common resolution.",
            )
        )
    firsts = [pd.Timestamp(r.coverage.first_date) for r in results]
    lasts = [pd.Timestamp(r.coverage.last_date) for r in results]
    overlap = (min(lasts) - max(firsts)).days
    union = (max(lasts) - min(firsts)).days
    if overlap < 0:
        warnings.append(AnalysisWarning(code="no_overlap", message="The regions' observation periods do not overlap in time."))
    elif union > 0 and overlap / union < 0.9:
        warnings.append(
            AnalysisWarning(
                code="coverage_mismatch",
                message="The regions cover different time periods ("
                + "; ".join(f"{r.request.region}: {r.coverage.first_date} to {r.coverage.last_date}" for r in results)
                + "). Trends over different periods are not directly comparable.",
            )
        )
    ns = [r.coverage.n_valid for r in results]
    if min(ns) / max(ns) < 0.8:
        warnings.append(
            AnalysisWarning(
                code="sample_size_mismatch",
                message="Sample sizes differ substantially ("
                + "; ".join(f"{r.request.region}: n = {r.coverage.n_valid}" for r in results)
                + "), so the tests have different statistical power.",
            )
        )
    gappy = [r.request.region for r in results if (r.sampling.grid_missing_fraction or 0) > GAP_WARN_FRACTION]
    if gappy:
        warnings.append(
            AnalysisWarning(
                code="missing_data",
                message=f"More than {GAP_WARN_FRACTION:.0%} of the regular grid is missing in: {', '.join(gappy)}.",
            )
        )
    insufficient = [r.request.region for r in results if not r.primary.available]
    if insufficient:
        warnings.append(
            AnalysisWarning(code="insufficient_data", message=f"Too few observations for a trend test in: {', '.join(insufficient)}.")
        )
    if any(r.provenance.is_synthetic for r in results):
        warnings.append(
            AnalysisWarning(code="synthetic_data", message="Synthetic demo data: this comparison describes artificial numbers only.")
        )

    # Benjamini-Hochberg across the regions that produced a primary p-value.
    idx = [i for i, r in enumerate(results) if r.primary.available and r.primary.p_value is not None]
    adjusted = diag.benjamini_hochberg([results[i].primary.p_value for i in idx])  # type: ignore[misc]
    adj_by_idx = dict(zip(idx, adjusted))
    rows: list[RegionComparisonRow] = []
    for i, r in enumerate(results):
        p = r.primary
        adj = adj_by_idx.get(i)
        rows.append(
            RegionComparisonRow(
                region=r.request.region,
                unit=r.unit,
                trend=p.trend,
                estimated_direction=p.estimated_direction,
                slope_per_year=p.slope_per_year,
                slope_ci_low=p.slope_ci_low,
                slope_ci_high=p.slope_ci_high,
                test_name=p.test_name,
                status=p.status,
                p_value=p.p_value,
                p_value_adjusted_bh=_f(adj),
                significant_raw=p.significant,
                significant_adjusted=None if adj is None else bool(adj < req.alpha),
                n_valid=r.coverage.n_valid,
                first_date=r.coverage.first_date,
                last_date=r.coverage.last_date,
                sampling=r.sampling.label,
                grid_missing_fraction=r.sampling.grid_missing_fraction,
            )
        )

    dirs = {row.estimated_direction for row in rows if row.estimated_direction in ("increasing", "decreasing")}
    evaluable = [row for row in rows if row.estimated_direction in ("increasing", "decreasing")]
    if not comparable or len(evaluable) < 2:
        summary = "mixed_or_insufficient"
    elif dirs == {"increasing", "decreasing"}:
        summary = "opposite_directions"
    elif len(dirs) == 1 and len(evaluable) == len(rows):
        summary = "same_direction"
    else:
        summary = "mixed_or_insufficient"

    subset = var_rows[var_rows["region"].isin(req.regions)]
    resp = CompareResponse(
        provenance=build_provenance(record, subset),
        request=req,
        comparable=comparable,
        unit=unit_set[0] if comparable else None,
        units_by_region=units_by_region,
        results=results,
        rows=rows,
        n_tests=len(idx),
        multiple_testing_method="Benjamini-Hochberg false discovery rate (FDR) across the regions compared",
        direction_summary=summary,  # type: ignore[arg-type]
        warnings=warnings,
    )
    if with_explanation:
        resp.explanation = explain_comparison(resp)
    return resp


__all__ = ["analyze_series", "compare_regions", "select_series", "require_variable", "AppError"]
