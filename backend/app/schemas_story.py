"""Request/response models for the story and chat endpoints."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas import Provenance

SentenceKind = Literal["observation", "comparison", "context", "limitation", "hypothesis"]


class StoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=1, max_length=100)
    region: str = Field(min_length=1, max_length=200)
    variable: str | None = Field(default=None, max_length=200, description="Defaults to the dataset's primary variable.")
    start: date
    end: date


class PeriodInfo(BaseModel):
    start: date
    end: date
    label: str
    n_months_expected: int
    n_valid: int
    n_missing: int


class GeoInfo(BaseModel):
    kind: Literal["dataset_coordinates", "approximate_extent", "none"]
    bbox: tuple[float, float, float, float] | None = Field(default=None, description="west, south, east, north")
    center: tuple[float, float] | None = Field(default=None, description="longitude, latitude")
    note: str


class ExtremePoint(BaseModel):
    date: date
    value: float


class MonthPoint(BaseModel):
    date: date
    value: float | None
    climatology: float | None = None
    anomaly: float | None = None
    anomaly_z: float | None = None
    unusual: bool = False


class StorySentence(BaseModel):
    kind: SentenceKind
    text: str
    evidence: str = Field(description="Which computed number(s) this sentence is based on.")


class CoVarying(BaseModel):
    variable: str
    spearman_rho: float
    n: int


class WhySection(BaseModel):
    cause_established: bool = False
    statement: str
    co_varying: list[CoVarying] = []


class StoryStats(BaseModel):
    unit: str
    mean: float | None
    minimum: ExtremePoint | None
    maximum: ExtremePoint | None
    first: ExtremePoint | None
    last: ExtremePoint | None
    change_abs: float | None = None
    change_pct: float | None = None
    descriptive_slope_per_year: float | None = None
    baseline_mean: float | None = Field(default=None, description="Mean of the same calendar months over the whole series.")
    anomaly_mean: float | None = None
    anomaly_pct: float | None = None
    previous_period_mean: float | None = None
    previous_period_change_pct: float | None = None


class StoryResponse(BaseModel):
    provenance: Provenance
    dataset_id: str
    region: str
    variable: str
    unit: str
    period: PeriodInfo
    geo: GeoInfo
    stats: StoryStats | None
    months: list[MonthPoint]
    sentences: list[StorySentence]
    why: WhySection
    banner: str | None = None
    caveats: list[str] = []


class RegionOption(BaseModel):
    region: str
    variables: list[str]
    start: date | None
    end: date | None
    geo: GeoInfo


class RegionsResponse(BaseModel):
    provenance: Provenance
    dataset_id: str
    default_variable: str | None
    regions: list[RegionOption]


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=500)
    current_region: str | None = None
    current_variable: str | None = None


class ChatAction(BaseModel):
    type: Literal["show_story", "compare", "none"]
    region: str | None = None
    regions: list[str] = []
    variable: str | None = None
    start: date | None = None
    end: date | None = None


class ChatResponse(BaseModel):
    reply: str
    understood: dict[str, str] = Field(default_factory=dict, description="What the parser recognised, so the user can check it.")
    action: ChatAction
    story: StoryResponse | None = None
    suggestions: list[str] = []


class GridFrame(BaseModel):
    provenance: Provenance
    dataset_id: str
    variable: str
    unit: str
    date: date
    lat: list[float]
    lon: list[float]
    values: list[list[float | None]]
    anomaly: list[list[float | None]] | None = None
    value_min: float | None = None
    value_max: float | None = None
    anomaly_abs_max: float | None = None
    display_note: str | None = None
    note: str


class GridUploadResponse(BaseModel):
    dataset_id: str
    name: str
    variable: str
    unit: str
    n_times: int
    n_lat: int
    n_lon: int
    date_start: date
    date_end: date
    n_missing_cells_pct: float
    message: str


# ---- Whole-record overview (rainfall "chronicle") -------------------------------------------------


class YearPoint(BaseModel):
    year: int
    n_months: int
    mean_value: float | None = Field(description="Mean of the valid monthly values; null when fewer than 10 months are valid.")
    mean_anomaly: float | None = Field(description="Mean difference from each calendar month's usual value (same unit).")
    mean_z: float | None = Field(description="Mean standardised anomaly: unit-free, comparable across regions.")


class ClimMonth(BaseModel):
    month: int
    mean: float | None
    std: float | None
    n: int


class DecadePoint(BaseModel):
    decade: int
    mean_anomaly: float
    n_years: int


class RecordMonth(BaseModel):
    date: date
    value: float
    anomaly: float
    z: float


class RecordYear(BaseModel):
    year: int
    mean_anomaly: float
    mean_z: float


class TrendInfo(BaseModel):
    slope_per_decade: float = Field(description="Descriptive least-squares slope of the yearly mean anomaly, in the data's unit per decade.")
    p_value: float
    n_years: int
    note: str


class OverviewResponse(BaseModel):
    provenance: Provenance
    dataset_id: str
    region: str
    variable: str
    unit: str
    banner: str | None
    first_year: int
    last_year: int
    years: list[YearPoint]
    matrix_values: list[list[float | None]] = Field(description="[year index][month 0-11] monthly values; null = missing.")
    matrix_z: list[list[float | None]] = Field(description="Same shape: standardised anomaly vs that calendar month's usual value; null if not computable.")
    climatology: list[ClimMonth]
    decades: list[DecadePoint]
    wettest_months: list[RecordMonth]
    driest_months: list[RecordMonth]
    wettest_years: list[RecordYear]
    driest_years: list[RecordYear]
    trend: TrendInfo | None
    sentences: list[StorySentence]
    caveats: list[str]


class AtlasRegion(BaseModel):
    region: str
    mean_value: float | None
    trend_z_per_decade: float | None = Field(description="Slope of the yearly mean standardised anomaly per decade (unit-free).")
    z: list[float | None] = Field(description="One value per year in `years`; null = not enough months.")


class AtlasResponse(BaseModel):
    provenance: Provenance
    dataset_id: str
    variable: str
    unit: str
    banner: str | None
    years: list[int]
    regions: list[AtlasRegion]
    note: str


# ---- Many regions at once on the map ------------------------------------------------------------


class SnapshotPoint(BaseModel):
    region: str
    lon: float
    lat: float
    value: float | None
    usual: float | None = Field(description="That calendar month's usual value (or the mean of the twelve for a whole year).")
    anomaly: float | None
    z: float | None


class SnapshotResponse(BaseModel):
    provenance: Provenance
    dataset_id: str
    variable: str
    unit: str
    banner: str | None
    year: int
    month: int = Field(description="1-12, or 0 for the whole year.")
    label: str
    points: list[SnapshotPoint]
    unlocated: list[str] = Field(description="Regions with data but no known map position; they are listed, never drawn.")
    value_max: float
    sentences: list[StorySentence]
    note: str
