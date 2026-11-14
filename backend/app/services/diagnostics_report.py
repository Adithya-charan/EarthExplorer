"""Runtime data diagnostics computed from the selected series only (no canned values)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.schemas import AutocorrelationResult
from app.schemas_diagnostics import (
    AutocorrelationDiagnostics,
    DiagnosticsResponse,
    MissingnessDiagnostics,
    MonthOfYearStat,
    RandomErrorDiagnostics,
)
from app.services.analysis import select_series
from app.services.ingestion.package_adapters import month_gaps
from app.services.provenance import build_provenance
from app.services.stats import diagnostics as dg
from app.services.store import DatasetRecord

ASSUMPTIONS = [
    "Everything here is computed from the rows of the selected series; no value is filled, interpolated or smoothed.",
    "Month-of-year statistics pool the same calendar month across years; they describe the sample, not a climatology with uncertainty.",
    "Autocorrelation uses residuals from a straight-line (OLS) fit and, separately, after also removing month-of-year means; "
    "observations are treated as equally spaced, which is exact only when no months are missing.",
    "The random-error variable is uncertainty-related. It is reported next to the values but is not a confidence interval and is never used as a weight.",
]

RANDOM_ERROR_NOTE = (
    "Random error is an uncertainty-related variable. For the observed global series it is Giovanni's area average of per-cell "
    "random error, which is not the uncertainty of the area-mean precipitation. It is not a confidence interval and is not used "
    "as a statistical weight."
)


def _f(x) -> float | None:
    return None if x is None or not np.isfinite(x) else float(x)


def missingness(sub: pd.DataFrame) -> MissingnessDiagnostics:
    dates = sub["date"]
    first = dates.min().to_period("M").to_timestamp()
    last = dates.max().to_period("M").to_timestamp()
    full = pd.date_range(first, last, freq="MS")
    valid_months = set(sub.loc[sub["value"].notna(), "date"].dt.to_period("M").dt.to_timestamp())
    longest = run = 0
    for m in full:
        run = 0 if m in valid_months else run + 1
        longest = max(longest, run)
    valid = int(sub["value"].notna().sum())
    return MissingnessDiagnostics(
        first_month=first.date(),
        last_month=last.date(),
        expected_months=len(full),
        present_rows=len(sub),
        valid_values=valid,
        missing_values=int(sub["value"].isna().sum()),
        absent_months=[m.date() for m in month_gaps(dates)],
        longest_gap_months=longest,
        coverage_fraction=valid / len(full) if len(full) else 0.0,
        note="Absent or missing months are reported as they are; the analysis never fills them.",
    )


def month_of_year(sub: pd.DataFrame) -> list[MonthOfYearStat]:
    ok = sub.dropna(subset=["value"])
    out = []
    for m in range(1, 13):
        v = ok.loc[ok["date"].dt.month == m, "value"].to_numpy(dtype=float)
        n = len(v)
        out.append(
            MonthOfYearStat(
                month=m,
                n=n,
                mean=_f(v.mean()) if n else None,
                median=_f(np.median(v)) if n else None,
                std=_f(v.std(ddof=1)) if n > 1 else None,
                minimum=_f(v.min()) if n else None,
                maximum=_f(v.max()) if n else None,
            )
        )
    return out


def _result(d: dg.AutocorrDiag | None, basis: str) -> AutocorrelationResult:
    if d is None:
        return AutocorrelationResult(evaluated=False, reason_not_evaluated="Too few values or no variance.", residual_basis=basis)
    return AutocorrelationResult(
        evaluated=True,
        residual_basis=basis,
        lag1=d.lag1,
        durbin_watson=d.durbin_watson,
        ljung_box_lags=d.ljung_box_lags,
        ljung_box_p=d.ljung_box_p,
        flagged=d.flagged,
        effective_n_ar1=d.effective_n_ar1,
    )


def autocorrelation_diag(sub: pd.DataFrame) -> AutocorrelationDiagnostics:
    ok = sub.dropna(subset=["value"]).sort_values("date")
    n = len(ok)
    if n < 3:
        return AutocorrelationDiagnostics(evaluated=False, reason_not_evaluated=f"Only {n} valid value(s).", n=n, note="Not enough data for autocorrelation diagnostics.")
    contiguous = len(month_gaps(ok["date"])) == 0
    months = ok["date"].dt.year * 12 + ok["date"].dt.month
    t = (months - months.iloc[0]).to_numpy(dtype=float) / 12.0
    y = ok["value"].to_numpy(dtype=float)
    if np.ptp(t) > 0:
        slope, intercept = np.polyfit(t, y, 1)
    else:
        slope, intercept = 0.0, float(y.mean())
    resid = y - (intercept + slope * t)
    moy = ok["date"].dt.month.to_numpy()
    enough = all(int((moy == m).sum()) >= 2 for m in np.unique(moy))
    if enough:
        deseas = resid.copy()
        for m in np.unique(moy):
            deseas[moy == m] -= resid[moy == m].mean()
        second = _result(dg.autocorrelation(deseas), "OLS-detrended residuals minus month-of-year means")
    else:
        second = AutocorrelationResult(evaluated=False, reason_not_evaluated="Some calendar months have fewer than two values.", residual_basis="deseasonalized")
    note = (
        "Strong positive lag-1 autocorrelation means consecutive months are not independent, so p-values from methods that "
        "assume independence are too optimistic."
    )
    if not contiguous:
        note += " Months are missing, so equal spacing is only approximate."
    return AutocorrelationDiagnostics(
        evaluated=True,
        n=n,
        contiguous_months=contiguous,
        detrended=_result(dg.autocorrelation(resid), "OLS-detrended residuals"),
        detrended_and_deseasonalized=second,
        note=note,
    )


def random_error_diag(record: DatasetRecord, region: str, precip: pd.DataFrame) -> RandomErrorDiagnostics | None:
    err = record.data[(record.data["variable"] == "random_error") & (record.data["region"] == region)]
    if err.empty:
        return None
    p = precip.dropna(subset=["value"])
    e = err.dropna(subset=["value"])
    aligned = set(p["date"]) == set(e["date"])
    merged = p[["date", "value"]].merge(e[["date", "value"]], on="date", suffixes=("_p", "_e"))
    if merged.empty:
        return RandomErrorDiagnostics(available=False, reason_unavailable="No shared dates between the value and random-error series.", dates_aligned=False, note=RANDOM_ERROR_NOTE)
    ratio = merged["value_e"] / merged["value_p"].replace(0, np.nan)
    return RandomErrorDiagnostics(
        available=True,
        dates_aligned=bool(aligned),
        n_aligned=len(merged),
        mean_random_error=_f(merged["value_e"].mean()),
        mean_precipitation=_f(merged["value_p"].mean()),
        mean_error_to_value_ratio=_f(ratio.mean()),
        unit=str(err["unit"].iloc[0]),
        usable_as_confidence_interval=False,
        note=RANDOM_ERROR_NOTE,
    )


def build_diagnostics(record: DatasetRecord, variable: str, region: str, start=None, end=None) -> DiagnosticsResponse:
    sub = select_series(record, variable, region, start, end)
    units = sub["unit"].dropna().unique().tolist()
    return DiagnosticsResponse(
        provenance=build_provenance(record, sub),
        variable=variable,
        region=region,
        unit=units[0] if len(units) == 1 else None,
        missingness=missingness(sub),
        month_of_year=month_of_year(sub),
        autocorrelation=autocorrelation_diag(sub),
        random_error=random_error_diag(record, region, sub) if variable == "precipitation" else None,
        assumptions=ASSUMPTIONS,
    )
