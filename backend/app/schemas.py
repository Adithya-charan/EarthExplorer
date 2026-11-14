"""Pydantic request / response models shared by services and routers."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

DatasetStatus = Literal["synthetic_demo", "uploaded", "nasa_verified", "observed_global", "synthetic_regional_demo"]
DataClass = Literal["observed_global", "synthetic_regional_demo"]
Severity = Literal["error", "warning", "info"]
Aggregation = Literal["none", "quarterly", "annual"]
SeasonalityMode = Literal["auto", "none", "seasonal"]
DuplicatePolicy = Literal["error", "mean", "first", "last"]
TrendLabel = Literal["increasing", "decreasing", "no_clear_trend", "insufficient_data"]
PrimaryStatus = Literal["standard", "autocorrelation_corrected", "exploratory_uncorrected", "insufficient_data"]

OPTIONAL_CANONICAL_FIELDS = (
    "dataset_id",
    "dataset_name",
    "mission",
    "instrument",
    "product",
    "quality_flag",
    "latitude",
    "longitude",
    "spatial_geometry",
    "spatial_resolution",
    "temporal_resolution",
    "original_variable",
    "original_unit",
    "source_file",
)


# --------------------------------------------------------------------------
# Provenance / datasets
# --------------------------------------------------------------------------
class Provenance(BaseModel):
    """Where the numbers in a response came from. Attached to every data response."""

    dataset_id: str
    dataset_name: str
    status: DatasetStatus
    is_synthetic: bool = Field(description="True if ANY row used in this response is synthetic.")
    synthetic_row_fraction: float
    data_sources: list[str]
    source_file: str | None = None
    notice: str | None = None
    dataset_checksum: str | None = Field(default=None, description="SHA-256 of the dataset's canonical rows (date, region, variable, value, unit); identifies the exact data version.")
    generated_at: str | None = Field(default=None, description="UTC time this response was produced.")


class PackageCheck(BaseModel):
    """One validation result produced while loading a packaged CSV."""

    code: str
    severity: Severity
    message: str


class DatasetInfo(BaseModel):
    """What a user must see whenever a packaged dataset is selected."""

    data_class: DataClass
    label: str
    data_source: str
    spatial_scope: str
    temporal_coverage: str
    unit: str
    unit_note: str
    limitations: list[str]
    source_files: list[str]
    regional_analysis_allowed: bool
    checks: list[PackageCheck] = []


class DatasetSummary(BaseModel):
    id: str
    name: str
    status: DatasetStatus
    is_synthetic: bool
    n_rows: int
    n_valid: int
    n_missing: int
    date_start: date | None
    date_end: date | None
    n_variables: int
    n_regions: int
    n_series: int
    data_sources: list[str]
    source_file: str | None = None
    created_at: str | None = None
    notice: str | None = None
    info: DatasetInfo | None = None


class NasaDatasetStatus(BaseModel):
    integrated: bool
    message: str


class DatasetListResponse(BaseModel):
    datasets: list[DatasetSummary]
    default_dataset_id: str | None
    nasa_dataset: NasaDatasetStatus
    package_issues: list[PackageCheck] = []


class SeriesSummary(BaseModel):
    variable: str
    region: str
    units: list[str]
    n_rows: int
    n_valid: int
    n_missing: int
    start: date | None
    end: date | None
    sampling: str
    data_sources: list[str]
    is_synthetic: bool


class VariableSummary(BaseModel):
    name: str
    units: list[str]
    regions: list[str]
    n_rows: int
    n_valid: int
    start: date | None
    end: date | None
    original_names: list[str] = []


class RegionSummary(BaseModel):
    name: str
    variables: list[str]
    n_rows: int
    start: date | None
    end: date | None


class SpatialInfo(BaseModel):
    available: bool
    n_points_with_coordinates: int = 0
    latitude_range: tuple[float, float] | None = None
    longitude_range: tuple[float, float] | None = None
    note: str


class MetadataResponse(BaseModel):
    provenance: Provenance
    dataset: DatasetSummary
    variables: list[VariableSummary]
    regions: list[RegionSummary]
    series: list[SeriesSummary]
    optional_fields_present: list[str]
    spatial: SpatialInfo
    quality: QualityReport | None = None


class ObservationsResponse(BaseModel):
    provenance: Provenance
    total: int
    limit: int
    offset: int
    columns: list[str]
    rows: list[dict[str, Any]]


# --------------------------------------------------------------------------
# Ingestion: mapping, profile, quality
# --------------------------------------------------------------------------
class MappingDefaults(BaseModel):
    """Constants declared by the user when a canonical field has no source column.

    Every default is an explicit user declaration; the app never guesses units
    or provenance flags.
    """

    model_config = ConfigDict(extra="forbid")

    region: str | None = Field(default=None, max_length=200)
    variable: str | None = Field(default=None, max_length=200)
    unit: str | None = Field(default=None, max_length=100)
    data_source: str | None = Field(default=None, max_length=300)
    is_synthetic: bool | None = None
    dataset_name: str | None = Field(default=None, max_length=200)


class ColumnMapping(BaseModel):
    """Source-column -> canonical-field mapping."""

    model_config = ConfigDict(extra="forbid")

    date: str | None = None
    region: str | None = None
    variable: str | None = None
    value: str | None = None
    unit: str | None = None
    data_source: str | None = None
    is_synthetic: str | None = None
    optional: dict[str, str] = Field(default_factory=dict)
    defaults: MappingDefaults = Field(default_factory=MappingDefaults)
    date_format: str | None = Field(default=None, max_length=60)
    duplicate_policy: DuplicatePolicy = "error"

    @field_validator("optional")
    @classmethod
    def _optional_keys(cls, v: dict[str, str]) -> dict[str, str]:
        bad = [k for k in v if k not in OPTIONAL_CANONICAL_FIELDS]
        if bad:
            raise ValueError(f"Unknown optional canonical field(s): {', '.join(bad)}")
        return v


class ColumnProfile(BaseModel):
    name: str
    inferred_type: Literal["numeric", "datetime", "boolean", "text", "empty"]
    n_non_empty: int
    n_missing: int
    n_unique: int
    examples: list[str]


class SourceInspection(BaseModel):
    filename: str
    format: str
    encoding: str
    delimiter: str
    n_rows: int
    n_columns: int
    columns: list[str]
    preview: list[dict[str, str]]


class SourceProfile(SourceInspection):
    column_profiles: list[ColumnProfile]
    suggested_mapping: ColumnMapping
    mapping_notes: list[str]
    mapping_complete: bool = Field(
        description="True if the suggested mapping already satisfies every required canonical field."
    )
    warnings: list[str] = []


class QualityIssue(BaseModel):
    severity: Severity
    code: str
    message: str
    count: int | None = None
    examples: list[str] = []


class QualityReport(BaseModel):
    n_source_rows: int
    n_rows_retained: int
    n_rows_dropped: int
    n_invalid_dates: int
    n_invalid_values: int
    n_invalid_labels: int
    n_missing_values: int
    n_duplicate_identical: int
    n_duplicate_conflicting: int
    duplicate_policy: DuplicatePolicy
    n_series: int
    variables: list[str]
    regions: list[str]
    units_by_variable: dict[str, list[str]]
    date_min: date | None
    date_max: date | None
    issues: list[QualityIssue]
    ambiguities: list[str]
    can_import: bool
    requires_confirmation: bool


class UploadResponse(BaseModel):
    imported: bool
    dry_run: bool
    quality: QualityReport
    dataset: DatasetSummary | None = None
    message: str


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------
class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=1, max_length=100)
    variable: str = Field(min_length=1, max_length=200)
    region: str = Field(min_length=1, max_length=200)
    start: date | None = None
    end: date | None = None
    aggregation: Aggregation = "none"
    seasonality: SeasonalityMode = "auto"
    alpha: float = Field(default=0.05, gt=0.0, le=0.2, description="Significance level; CIs use 1 - alpha.")


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=1, max_length=100)
    variable: str = Field(min_length=1, max_length=200)
    regions: list[str] = Field(min_length=2, max_length=12)
    start: date | None = None
    end: date | None = None
    aggregation: Aggregation = "none"
    seasonality: SeasonalityMode = "auto"
    alpha: float = Field(default=0.05, gt=0.0, le=0.2)

    @field_validator("regions")
    @classmethod
    def _unique_regions(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("regions must be unique")
        return v


class SeriesPoint(BaseModel):
    date: str  # ISO date (YYYY-MM-DD)
    value: float | None
    fitted_ols: float | None = None
    fitted_sen: float | None = None
    deseasonalized: float | None = None
    n_in_period: int | None = None


class SamplingInfo(BaseModel):
    label: Literal["daily", "weekly", "monthly", "quarterly", "annual", "irregular", "insufficient"]
    median_step_days: float | None
    regular: bool
    seasonal_period: int | None = Field(description="Observations per seasonal cycle, if defined for this sampling.")
    expected_n: int | None = Field(description="Observations expected on the regular grid between first and last valid date.")
    grid_missing: int | None
    grid_missing_fraction: float | None
    longest_gap_steps: int | None


class CoverageInfo(BaseModel):
    n_rows: int
    n_missing_values: int
    n_valid: int
    first_date: str | None
    last_date: str | None
    span_years: float | None


class AggregationInfo(BaseModel):
    method: Aggregation
    native_sampling: str
    expected_per_period: int | None = None
    min_coverage: float | None = None
    periods_total: int | None = None
    periods_dropped_low_coverage: int | None = None
    note: str | None = None


class LinearRegressionResult(BaseModel):
    test_name: str = "OLS linear regression (t-test on slope)"
    slope_per_year: float
    intercept: float
    intercept_at: str
    std_err: float
    ci_low: float
    ci_high: float
    confidence_level: float
    p_value: float
    r_squared: float
    n: int
    df: int
    significant: bool


class HacRegressionResult(BaseModel):
    test_name: str = "OLS with Newey-West (HAC) standard errors"
    slope_per_year: float
    std_err: float
    ci_low: float
    ci_high: float
    p_value: float
    maxlags: int
    significant: bool


class MannKendallResult(BaseModel):
    variant: Literal["original", "seasonal", "hamed_rao"]
    test_name: str
    s: float
    var_s: float
    z: float
    p_value: float
    tau: float
    n: int
    trend: Literal["increasing", "decreasing", "no_clear_trend"]
    significant: bool
    alpha: float
    seasons_used: int | None = None
    seasons_total: int | None = None
    notes: list[str] = []


class SenSlopeResult(BaseModel):
    method: Literal["sen", "seasonal_sen"]
    method_name: str
    slope_per_year: float
    ci_low: float | None
    ci_high: float | None
    intercept: float
    confidence_level: float
    n_pairs: int
    ci_excludes_zero: bool | None


class AutocorrelationResult(BaseModel):
    evaluated: bool
    reason_not_evaluated: str | None = None
    residual_basis: str | None = None
    lag1: float | None = None
    durbin_watson: float | None = None
    ljung_box_lags: int | None = None
    ljung_box_p: float | None = None
    flagged: bool | None = None
    effective_n_ar1: float | None = None
    approximate: bool = False
    correction_applied: bool = False
    correction_method: str | None = None
    note: str | None = None


class SeasonalityResult(BaseModel):
    period: int | None
    assessed: bool
    detected: bool
    method_used: Literal["none", "seasonal_mann_kendall"]
    kruskal_p: float | None = None
    eta_squared: float | None = None
    n_cycles: float | None = None
    note: str


class PrimaryResult(BaseModel):
    """The single result that headlines the analysis. Which test it comes from is stated explicitly."""

    available: bool
    status: PrimaryStatus
    trend: TrendLabel
    estimated_direction: Literal["increasing", "decreasing", "flat", "unknown"]
    test_name: str | None
    p_value: float | None
    alpha: float
    significant: bool | None
    slope_per_year: float | None
    slope_ci_low: float | None
    slope_ci_high: float | None
    slope_method: str | None
    unit: str
    slope_unit: str
    total_change_over_period: float | None
    reason: str | None = None


class AnalysisWarning(BaseModel):
    code: str
    message: str


class ExplanationStatement(BaseModel):
    text: str
    evidence: list[dict[str, str]] = Field(
        default_factory=list, description="[{label, value}] pairs from the computed results that support the sentence."
    )


class ExplanationSection(BaseModel):
    heading: str
    statements: list[ExplanationStatement]


class Explanation(BaseModel):
    generator: str = "deterministic-rules-v1"
    uses_external_ai: bool = False
    sections: list[ExplanationSection]


class AnalyzeResponse(BaseModel):
    provenance: Provenance
    request: AnalyzeRequest
    unit: str
    sampling: SamplingInfo
    coverage: CoverageInfo
    aggregation: AggregationInfo
    points: list[SeriesPoint]
    linear_regression: LinearRegressionResult | None
    linear_regression_hac: HacRegressionResult | None = None
    mann_kendall: MannKendallResult | None
    seasonal_mann_kendall: MannKendallResult | None = None
    mann_kendall_hamed_rao: MannKendallResult | None = None
    sens_slope: SenSlopeResult | None
    autocorrelation: AutocorrelationResult
    seasonality: SeasonalityResult
    primary: PrimaryResult
    warnings: list[AnalysisWarning]
    assumptions: list[str]
    explanation: Explanation | None = None


class RegionComparisonRow(BaseModel):
    region: str
    unit: str
    trend: TrendLabel
    estimated_direction: Literal["increasing", "decreasing", "flat", "unknown"]
    slope_per_year: float | None
    slope_ci_low: float | None
    slope_ci_high: float | None
    test_name: str | None
    status: PrimaryStatus
    p_value: float | None
    p_value_adjusted_bh: float | None
    significant_raw: bool | None
    significant_adjusted: bool | None
    n_valid: int
    first_date: str | None
    last_date: str | None
    sampling: str
    grid_missing_fraction: float | None


class CompareResponse(BaseModel):
    provenance: Provenance
    request: CompareRequest
    comparable: bool
    unit: str | None
    units_by_region: dict[str, str]
    results: list[AnalyzeResponse]
    rows: list[RegionComparisonRow]
    n_tests: int
    multiple_testing_method: str
    direction_summary: Literal["same_direction", "opposite_directions", "mixed_or_insufficient"]
    warnings: list[AnalysisWarning]
    explanation: Explanation | None = None


class ExplainRequest(BaseModel):
    """Exactly one of ``analysis`` / ``comparison`` must be supplied."""

    analysis: AnalyzeResponse | None = None
    comparison: CompareResponse | None = None


class ExplainResponse(BaseModel):
    explanation: Explanation


# --------------------------------------------------------------------------
# Methodology
# --------------------------------------------------------------------------
class MethodologyReference(BaseModel):
    citation: str
    url: str | None = None


class MethodologySection(BaseModel):
    id: str
    title: str
    body: list[str]


class MethodologyResponse(BaseModel):
    sections: list[MethodologySection]
    references: list[MethodologyReference]
    defaults: dict[str, Any]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
    datasets_loaded: int
    nasa_dataset_integrated: bool
    uses_external_ai: bool = False
    # Earth Explorer: state of the reference atlas, geocoder and terrain service (None if not configured).
    geo: dict[str, Any] | None = None


MetadataResponse.model_rebuild()
