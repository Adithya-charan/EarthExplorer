"""Response models for the data-diagnostics endpoint (missingness, month-of-year, autocorrelation, random error)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from app.schemas import AutocorrelationResult, Provenance


class MissingnessDiagnostics(BaseModel):
    first_month: date
    last_month: date
    expected_months: int
    present_rows: int
    valid_values: int
    missing_values: int = Field(description="Rows present in the file whose value is missing (e.g. a declared fill value).")
    absent_months: list[date] = Field(description="Months inside the covered period that have no row at all.")
    longest_gap_months: int
    coverage_fraction: float
    note: str


class MonthOfYearStat(BaseModel):
    month: int
    n: int
    mean: float | None
    median: float | None
    std: float | None
    minimum: float | None
    maximum: float | None


class AutocorrelationDiagnostics(BaseModel):
    evaluated: bool
    reason_not_evaluated: str | None = None
    n: int | None = None
    contiguous_months: bool | None = None
    detrended: AutocorrelationResult | None = None
    detrended_and_deseasonalized: AutocorrelationResult | None = None
    note: str


class RandomErrorDiagnostics(BaseModel):
    available: bool
    reason_unavailable: str | None = None
    dates_aligned: bool | None = None
    n_aligned: int | None = None
    mean_random_error: float | None = None
    mean_precipitation: float | None = None
    mean_error_to_value_ratio: float | None = None
    unit: str | None = None
    usable_as_confidence_interval: bool = False
    note: str


class DiagnosticsResponse(BaseModel):
    provenance: Provenance
    variable: str
    region: str
    unit: str | None
    missingness: MissingnessDiagnostics
    month_of_year: list[MonthOfYearStat]
    autocorrelation: AutocorrelationDiagnostics
    random_error: RandomErrorDiagnostics | None = None
    assumptions: list[str]
