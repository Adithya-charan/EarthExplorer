// Types mirror the FastAPI Pydantic models in backend/app/schemas.py.
// The browser never recomputes statistics; it only renders what the API returns.

export type DatasetStatus = "synthetic_demo" | "uploaded" | "nasa_verified" | "observed_global" | "synthetic_regional_demo";
export type DataClass = "observed_global" | "synthetic_regional_demo";

export interface PackageCheck {
  code: string;
  severity: "error" | "warning" | "info";
  message: string;
}

/** What a user must see whenever a packaged dataset is selected. */
export interface DatasetInfo {
  data_class: DataClass;
  label: string;
  data_source: string;
  spatial_scope: string;
  temporal_coverage: string;
  unit: string;
  unit_note: string;
  limitations: string[];
  source_files: string[];
  regional_analysis_allowed: boolean;
  checks: PackageCheck[];
}
export type Aggregation = "none" | "quarterly" | "annual";
export type SeasonalityMode = "auto" | "none" | "seasonal";
export type DuplicatePolicy = "error" | "mean" | "first" | "last";
export type TrendLabel = "increasing" | "decreasing" | "no_clear_trend" | "insufficient_data";
export type Direction = "increasing" | "decreasing" | "flat" | "unknown";
export type PrimaryStatus =
  | "standard"
  | "autocorrelation_corrected"
  | "exploratory_uncorrected"
  | "insufficient_data";

export interface Provenance {
  dataset_id: string;
  dataset_name: string;
  status: DatasetStatus;
  is_synthetic: boolean;
  synthetic_row_fraction: number;
  data_sources: string[];
  source_file: string | null;
  notice: string | null;
  dataset_checksum?: string | null;
  generated_at?: string | null;
}

export interface DatasetSummary {
  id: string;
  name: string;
  status: DatasetStatus;
  is_synthetic: boolean;
  n_rows: number;
  n_valid: number;
  n_missing: number;
  date_start: string | null;
  date_end: string | null;
  n_variables: number;
  n_regions: number;
  n_series: number;
  data_sources: string[];
  source_file: string | null;
  created_at: string | null;
  notice: string | null;
  info?: DatasetInfo | null;
}

export interface NasaDatasetStatus {
  integrated: boolean;
  message: string;
}

export interface DatasetListResponse {
  datasets: DatasetSummary[];
  default_dataset_id: string | null;
  nasa_dataset: NasaDatasetStatus;
  package_issues?: PackageCheck[];
}

export interface SeriesSummary {
  variable: string;
  region: string;
  units: string[];
  n_rows: number;
  n_valid: number;
  n_missing: number;
  start: string | null;
  end: string | null;
  sampling: string;
  data_sources: string[];
  is_synthetic: boolean;
}

export interface VariableSummary {
  name: string;
  units: string[];
  regions: string[];
  n_rows: number;
  n_valid: number;
  start: string | null;
  end: string | null;
  original_names: string[];
}

export interface RegionSummary {
  name: string;
  variables: string[];
  n_rows: number;
  start: string | null;
  end: string | null;
}

export interface SpatialInfo {
  available: boolean;
  n_points_with_coordinates: number;
  latitude_range: [number, number] | null;
  longitude_range: [number, number] | null;
  note: string;
}

export interface QualityIssue {
  severity: "error" | "warning" | "info";
  code: string;
  message: string;
  count: number | null;
  examples: string[];
}

export interface QualityReport {
  n_source_rows: number;
  n_rows_retained: number;
  n_rows_dropped: number;
  n_invalid_dates: number;
  n_invalid_values: number;
  n_invalid_labels: number;
  n_missing_values: number;
  n_duplicate_identical: number;
  n_duplicate_conflicting: number;
  duplicate_policy: DuplicatePolicy;
  n_series: number;
  variables: string[];
  regions: string[];
  units_by_variable: Record<string, string[]>;
  date_min: string | null;
  date_max: string | null;
  issues: QualityIssue[];
  ambiguities: string[];
  can_import: boolean;
  requires_confirmation: boolean;
}

export interface MetadataResponse {
  provenance: Provenance;
  dataset: DatasetSummary;
  variables: VariableSummary[];
  regions: RegionSummary[];
  series: SeriesSummary[];
  optional_fields_present: string[];
  spatial: SpatialInfo;
  quality: QualityReport | null;
}

export type ObservationRow = Record<string, string | number | boolean | null>;

export interface ObservationsResponse {
  provenance: Provenance;
  total: number;
  limit: number;
  offset: number;
  columns: string[];
  rows: ObservationRow[];
}

// ----------------------------------------------------------------- upload
export interface MappingDefaults {
  region?: string | null;
  variable?: string | null;
  unit?: string | null;
  data_source?: string | null;
  is_synthetic?: boolean | null;
  dataset_name?: string | null;
}

export interface ColumnMapping {
  date: string | null;
  region: string | null;
  variable: string | null;
  value: string | null;
  unit: string | null;
  data_source: string | null;
  is_synthetic: string | null;
  optional: Record<string, string>;
  defaults: MappingDefaults;
  date_format: string | null;
  duplicate_policy: DuplicatePolicy;
}

export interface ColumnProfile {
  name: string;
  inferred_type: "numeric" | "datetime" | "boolean" | "text" | "empty";
  n_non_empty: number;
  n_missing: number;
  n_unique: number;
  examples: string[];
}

export interface SourceProfile {
  filename: string;
  format: string;
  encoding: string;
  delimiter: string;
  n_rows: number;
  n_columns: number;
  columns: string[];
  preview: Record<string, string>[];
  column_profiles: ColumnProfile[];
  suggested_mapping: ColumnMapping;
  mapping_notes: string[];
  mapping_complete: boolean;
  warnings: string[];
}

export interface UploadResponse {
  imported: boolean;
  dry_run: boolean;
  quality: QualityReport;
  dataset: DatasetSummary | null;
  message: string;
}

// --------------------------------------------------------------- analysis
export interface AnalyzeRequest {
  dataset_id: string;
  variable: string;
  region: string;
  start?: string | null;
  end?: string | null;
  aggregation: Aggregation;
  seasonality: SeasonalityMode;
  alpha: number;
}

export interface CompareRequest {
  dataset_id: string;
  variable: string;
  regions: string[];
  start?: string | null;
  end?: string | null;
  aggregation: Aggregation;
  seasonality: SeasonalityMode;
  alpha: number;
}

export interface SeriesPoint {
  date: string;
  value: number | null;
  fitted_ols: number | null;
  fitted_sen: number | null;
  deseasonalized: number | null;
  n_in_period: number | null;
}

export interface SamplingInfo {
  label: "daily" | "weekly" | "monthly" | "quarterly" | "annual" | "irregular" | "insufficient";
  median_step_days: number | null;
  regular: boolean;
  seasonal_period: number | null;
  expected_n: number | null;
  grid_missing: number | null;
  grid_missing_fraction: number | null;
  longest_gap_steps: number | null;
}

export interface CoverageInfo {
  n_rows: number;
  n_missing_values: number;
  n_valid: number;
  first_date: string | null;
  last_date: string | null;
  span_years: number | null;
}

export interface AggregationInfo {
  method: Aggregation;
  native_sampling: string;
  expected_per_period: number | null;
  min_coverage: number | null;
  periods_total: number | null;
  periods_dropped_low_coverage: number | null;
  note: string | null;
}

export interface LinearRegressionResult {
  test_name: string;
  slope_per_year: number;
  intercept: number;
  intercept_at: string;
  std_err: number;
  ci_low: number;
  ci_high: number;
  confidence_level: number;
  p_value: number;
  r_squared: number;
  n: number;
  df: number;
  significant: boolean;
}

export interface HacRegressionResult {
  test_name: string;
  slope_per_year: number;
  std_err: number;
  ci_low: number;
  ci_high: number;
  p_value: number;
  maxlags: number;
  significant: boolean;
}

export interface MannKendallResult {
  variant: "original" | "seasonal" | "hamed_rao";
  test_name: string;
  s: number;
  var_s: number;
  z: number;
  p_value: number;
  tau: number;
  n: number;
  trend: "increasing" | "decreasing" | "no_clear_trend";
  significant: boolean;
  alpha: number;
  seasons_used: number | null;
  seasons_total: number | null;
  notes: string[];
}

export interface SenSlopeResult {
  method: "sen" | "seasonal_sen";
  method_name: string;
  slope_per_year: number;
  ci_low: number | null;
  ci_high: number | null;
  intercept: number;
  confidence_level: number;
  n_pairs: number;
  ci_excludes_zero: boolean | null;
}

export interface AutocorrelationResult {
  evaluated: boolean;
  reason_not_evaluated: string | null;
  residual_basis: string | null;
  lag1: number | null;
  durbin_watson: number | null;
  ljung_box_lags: number | null;
  ljung_box_p: number | null;
  flagged: boolean | null;
  effective_n_ar1: number | null;
  approximate: boolean;
  correction_applied: boolean;
  correction_method: string | null;
  note: string | null;
}

export interface SeasonalityResult {
  period: number | null;
  assessed: boolean;
  detected: boolean;
  method_used: "none" | "seasonal_mann_kendall";
  kruskal_p: number | null;
  eta_squared: number | null;
  n_cycles: number | null;
  note: string;
}

export interface PrimaryResult {
  available: boolean;
  status: PrimaryStatus;
  trend: TrendLabel;
  estimated_direction: Direction;
  test_name: string | null;
  p_value: number | null;
  alpha: number;
  significant: boolean | null;
  slope_per_year: number | null;
  slope_ci_low: number | null;
  slope_ci_high: number | null;
  slope_method: string | null;
  unit: string;
  slope_unit: string;
  total_change_over_period: number | null;
  reason: string | null;
}

export interface AnalysisWarning {
  code: string;
  message: string;
}

export interface ExplanationStatement {
  text: string;
  evidence: { label: string; value: string }[];
}

export interface ExplanationSection {
  heading: string;
  statements: ExplanationStatement[];
}

export interface Explanation {
  generator: string;
  uses_external_ai: boolean;
  sections: ExplanationSection[];
}

export interface AnalyzeResponse {
  provenance: Provenance;
  request: AnalyzeRequest;
  unit: string;
  sampling: SamplingInfo;
  coverage: CoverageInfo;
  aggregation: AggregationInfo;
  points: SeriesPoint[];
  linear_regression: LinearRegressionResult | null;
  linear_regression_hac: HacRegressionResult | null;
  mann_kendall: MannKendallResult | null;
  seasonal_mann_kendall: MannKendallResult | null;
  mann_kendall_hamed_rao: MannKendallResult | null;
  sens_slope: SenSlopeResult | null;
  autocorrelation: AutocorrelationResult;
  seasonality: SeasonalityResult;
  primary: PrimaryResult;
  warnings: AnalysisWarning[];
  assumptions: string[];
  explanation: Explanation | null;
}

export interface RegionComparisonRow {
  region: string;
  unit: string;
  trend: TrendLabel;
  estimated_direction: Direction;
  slope_per_year: number | null;
  slope_ci_low: number | null;
  slope_ci_high: number | null;
  test_name: string | null;
  status: PrimaryStatus;
  p_value: number | null;
  p_value_adjusted_bh: number | null;
  significant_raw: boolean | null;
  significant_adjusted: boolean | null;
  n_valid: number;
  first_date: string | null;
  last_date: string | null;
  sampling: string;
  grid_missing_fraction: number | null;
}

export interface CompareResponse {
  provenance: Provenance;
  request: CompareRequest;
  comparable: boolean;
  unit: string | null;
  units_by_region: Record<string, string>;
  results: AnalyzeResponse[];
  rows: RegionComparisonRow[];
  n_tests: number;
  multiple_testing_method: string;
  direction_summary: "same_direction" | "opposite_directions" | "mixed_or_insufficient";
  warnings: AnalysisWarning[];
  explanation: Explanation | null;
}

export interface MethodologyResponse {
  sections: { id: string; title: string; body: string[] }[];
  references: { citation: string; url: string | null }[];
  defaults: Record<string, number>;
}

// ---- Data diagnostics (GET /api/diagnostics) ----
export interface MissingnessDiagnostics {
  first_month: string;
  last_month: string;
  expected_months: number;
  present_rows: number;
  valid_values: number;
  missing_values: number;
  absent_months: string[];
  longest_gap_months: number;
  coverage_fraction: number;
  note: string;
}

export interface MonthOfYearStat {
  month: number;
  n: number;
  mean: number | null;
  median: number | null;
  std: number | null;
  minimum: number | null;
  maximum: number | null;
}

export interface AutocorrelationDiagnostics {
  evaluated: boolean;
  reason_not_evaluated: string | null;
  n: number | null;
  contiguous_months: boolean | null;
  detrended: AutocorrelationResult | null;
  detrended_and_deseasonalized: AutocorrelationResult | null;
  note: string;
}

export interface RandomErrorDiagnostics {
  available: boolean;
  reason_unavailable: string | null;
  dates_aligned: boolean | null;
  n_aligned: number | null;
  mean_random_error: number | null;
  mean_precipitation: number | null;
  mean_error_to_value_ratio: number | null;
  unit: string | null;
  usable_as_confidence_interval: boolean;
  note: string;
}

export interface DiagnosticsResponse {
  provenance: Provenance;
  variable: string;
  region: string;
  unit: string | null;
  missingness: MissingnessDiagnostics;
  month_of_year: MonthOfYearStat[];
  autocorrelation: AutocorrelationDiagnostics;
  random_error: RandomErrorDiagnostics | null;
  assumptions: string[];
}

// ---- Story / chat ----------------------------------------------------------
export interface GeoInfo {
  kind: "dataset_coordinates" | "approximate_extent" | "none";
  bbox: [number, number, number, number] | null;
  center: [number, number] | null;
  note: string;
}
export interface ExtremePoint {
  date: string;
  value: number;
}
export interface MonthPoint {
  date: string;
  value: number | null;
  climatology: number | null;
  anomaly: number | null;
  anomaly_z: number | null;
  unusual: boolean;
}
export interface StorySentence {
  kind: "observation" | "comparison" | "context" | "limitation" | "hypothesis";
  text: string;
  evidence: string;
}
export interface StoryStats {
  unit: string;
  mean: number | null;
  minimum: ExtremePoint | null;
  maximum: ExtremePoint | null;
  first: ExtremePoint | null;
  last: ExtremePoint | null;
  change_abs: number | null;
  change_pct: number | null;
  descriptive_slope_per_year: number | null;
  baseline_mean: number | null;
  anomaly_mean: number | null;
  anomaly_pct: number | null;
  previous_period_mean: number | null;
  previous_period_change_pct: number | null;
}
export interface StoryResponse {
  provenance: Provenance;
  dataset_id: string;
  region: string;
  variable: string;
  unit: string;
  period: { start: string; end: string; label: string; n_months_expected: number; n_valid: number; n_missing: number };
  geo: GeoInfo;
  stats: StoryStats | null;
  months: MonthPoint[];
  sentences: StorySentence[];
  why: { cause_established: boolean; statement: string; co_varying: { variable: string; spearman_rho: number; n: number }[] };
  banner: string | null;
  caveats: string[];
}
export interface StoryRequest {
  dataset_id: string;
  region: string;
  variable?: string;
  start: string;
  end: string;
}
export interface RegionsResponse {
  provenance: Provenance;
  dataset_id: string;
  default_variable: string | null;
  regions: { region: string; variables: string[]; start: string | null; end: string | null; geo: GeoInfo }[];
}
export interface ChatAction {
  type: "show_story" | "compare" | "none";
  region: string | null;
  regions: string[];
  variable: string | null;
  start: string | null;
  end: string | null;
}
export interface ChatResponse {
  reply: string;
  understood: Record<string, string>;
  action: ChatAction;
  story: StoryResponse | null;
  suggestions: string[];
}
export interface ChatRequest {
  dataset_id: string;
  message: string;
  current_region?: string | null;
  current_variable?: string | null;
}

export interface GridUploadResponse {
  dataset_id: string;
  name: string;
  variable: string;
  unit: string;
  n_times: number;
  n_lat: number;
  n_lon: number;
  date_start: string;
  date_end: string;
  n_missing_cells_pct: number;
  message: string;
}
export interface GridFrame {
  provenance: Provenance;
  dataset_id: string;
  variable: string;
  unit: string;
  date: string;
  lat: number[];
  lon: number[];
  values: (number | null)[][];
  anomaly: (number | null)[][] | null;
  value_min: number | null;
  value_max: number | null;
  anomaly_abs_max: number | null;
  display_note: string | null;
  note: string;
}

// ---- Whole-record overview ("chronicle") and atlas ----
export interface YearPoint {
  year: number;
  n_months: number;
  mean_value: number | null;
  mean_anomaly: number | null;
  mean_z: number | null;
}
export interface ClimMonth {
  month: number;
  mean: number | null;
  std: number | null;
  n: number;
}
export interface RecordMonth {
  date: string;
  value: number;
  anomaly: number;
  z: number;
}
export interface RecordYear {
  year: number;
  mean_anomaly: number;
  mean_z: number;
}
export interface OverviewResponse {
  provenance: Provenance;
  dataset_id: string;
  region: string;
  variable: string;
  unit: string;
  banner: string | null;
  first_year: number;
  last_year: number;
  years: YearPoint[];
  matrix_values: (number | null)[][];
  matrix_z: (number | null)[][];
  climatology: ClimMonth[];
  decades: { decade: number; mean_anomaly: number; n_years: number }[];
  wettest_months: RecordMonth[];
  driest_months: RecordMonth[];
  wettest_years: RecordYear[];
  driest_years: RecordYear[];
  trend: { slope_per_decade: number; p_value: number; n_years: number; note: string } | null;
  sentences: StorySentence[];
  caveats: string[];
}
export interface AtlasResponse {
  provenance: Provenance;
  dataset_id: string;
  variable: string;
  unit: string;
  banner: string | null;
  years: number[];
  regions: { region: string; mean_value: number | null; trend_z_per_decade: number | null; z: (number | null)[] }[];
  note: string;
}

export interface SnapshotPoint {
  region: string;
  lon: number;
  lat: number;
  value: number | null;
  usual: number | null;
  anomaly: number | null;
  z: number | null;
}
export interface SnapshotResponse {
  provenance: Provenance;
  dataset_id: string;
  variable: string;
  unit: string;
  banner: string | null;
  year: number;
  month: number;
  label: string;
  points: SnapshotPoint[];
  unlocated: string[];
  value_max: number;
  sentences: StorySentence[];
  note: string;
}
