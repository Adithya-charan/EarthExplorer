"""Pydantic models for the Earth Time Machine API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Outcome = Literal["change_detected", "no_clear_change", "insufficient_data"]
Quality = Literal["good", "fair", "poor"]


class ChangeParams(BaseModel):
    """Tunable detection thresholds. Defaults are conservative and are echoed back in every summary."""

    window_years: int = Field(1, ge=1, le=5, description="Years averaged at each end of the period.")
    min_valid_obs_monthly: int = Field(6, ge=1, le=60, description="Usable same-season observations needed in each window (monthly data).")
    min_valid_obs_yearly: int = Field(1, ge=1, le=20, description="Usable observations needed in each window (yearly data).")
    min_obs_valid_fraction: float = Field(0.5, ge=0.0, le=1.0, description="An observation with fewer valid pixels than this is not used.")
    min_pixel_obs_fraction: float = Field(0.34, ge=0.0, le=1.0, description="A pixel needs valid data in at least this share of a window's observations.")
    water_frequency: float = Field(0.5, gt=0.0, le=1.0, description="A pixel is water when it is water in at least this share of its valid observations.")
    min_change_pct: float = Field(5.0, ge=0.0, le=100.0, description="Gross change (gain + loss) must exceed this % of the starting water area.")
    min_hotspot_ha: float = Field(2.0, ge=0.0, le=10_000.0, description="Smallest change area reported as a hotspot.")
    min_feature_px: int = Field(3, ge=1, le=15, description="Change features narrower than this many pixels are treated as positional noise.")
    noise_factor: float = Field(2.0, ge=0.0, le=20.0, description="Gross change must exceed this multiple of the year-to-year scatter.")


class DetectRequest(BaseModel):
    dataset_id: str | None = None
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    start_year: int = Field(ge=1800, le=2200)
    end_year: int = Field(ge=1800, le=2200)
    params: ChangeParams | None = None


class SessionRequest(BaseModel):
    query: str | None = Field(None, max_length=200)
    location_id: str | None = Field(None, max_length=200)
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    start_year: int = Field(ge=1800, le=2200)
    end_year: int = Field(ge=1800, le=2200)
    online: bool = True


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=600)
    analysis_id: str | None = None
    history: list[dict[str, str]] = Field(default_factory=list, max_length=12)


class ObservationInfo(BaseModel):
    date: str
    quality: Quality
    valid_fraction: float
    usable: bool
    water_share: float | None = None
    sensor: str | None = None


class DatasetInfo(BaseModel):
    id: str
    name: str
    description: str
    is_synthetic: bool
    simulated_label: str | None
    source: str
    product: str
    format: str
    crs: str
    resolution_m: float
    temporal_resolution: Literal["monthly", "yearly", "irregular"]
    bbox: list[float]
    coverage: dict[str, str]
    observation_count: int
    usable_count: int
    classes: dict[str, str]
    real_dataset_targets: list[dict[str, Any]] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class LocationOut(BaseModel):
    id: str
    name: str
    display_name: str
    lat: float
    lon: float
    kind: str = "place"
    source: str
    bbox: list[float] | None = None
    zoom_altitude_m: float = 12_000.0


class PeriodCheck(BaseModel):
    requested: dict[str, int]
    supported: dict[str, str] | None
    effective: dict[str, int] | None
    status: Literal["ok", "clipped", "outside", "too_short"]
    messages: list[str] = Field(default_factory=list)


class LatestObservation(BaseModel):
    label: str = "Latest available observation"
    date: str
    location: str
    source: str
    spatial_resolution_m: float
    quality: Quality
    valid_fraction: float
    temporal_resolution: str
    historical_coverage: dict[str, str]
    is_synthetic: bool
    simulated_label: str | None
    note: str


class Insufficient(BaseModel):
    code: str
    reason: str
    missing: list[str] = Field(default_factory=list)
    available_dates: list[str] = Field(default_factory=list)
    suggested_period: dict[str, int] | None = None


class SessionResponse(BaseModel):
    status: Literal["ready", "no_dataset", "not_found", "ambiguous", "period_unsupported"]
    message: str
    location: LocationOut | None = None
    alternatives: list[LocationOut] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    datasets: list[DatasetInfo] = Field(default_factory=list)
    dataset: DatasetInfo | None = None
    period: PeriodCheck | None = None
    latest: LatestObservation | None = None
    insufficient: Insufficient | None = None
    is_synthetic: bool = False
    simulated_label: str | None = None


class Hotspot(BaseModel):
    id: str
    rank: int
    kind: Literal["loss", "gain"]
    area_ha: float
    geometry_area_ha: float
    share_of_change_pct: float
    centroid: dict[str, float]
    bbox: list[float]
    region: str
    description: str


class ProgressionPoint(BaseModel):
    year: int
    water_ha: float
    cumulative_loss_ha: float
    cumulative_gain_ha: float
    observations: int


class ChangeSummary(BaseModel):
    outcome: Outcome
    headline: str
    analysis_id: str | None = None
    dataset: DatasetInfo | None = None
    location_name: str | None = None
    period: PeriodCheck | None = None
    first_observation: dict[str, Any] | None = None
    last_observation: dict[str, Any] | None = None
    observations_used: dict[str, Any] = Field(default_factory=dict)
    areas: dict[str, float | None] = Field(default_factory=dict)
    most_affected: dict[str, Any] | None = None
    hotspots: list[Hotspot] = Field(default_factory=list)
    progression: list[ProgressionPoint] = Field(default_factory=list)
    trend: dict[str, Any] | None = None
    quality: dict[str, Any] = Field(default_factory=dict)
    confidence: Literal["high", "medium", "low"] | None = None
    confidence_reasons: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    what_was_analysed: str = ""
    insufficient: Insufficient | None = None
    thresholds: dict[str, Any] = Field(default_factory=dict)
    bbox: list[float] | None = None
    layers: dict[str, str] = Field(default_factory=dict)
    is_synthetic: bool = False
    simulated_label: str | None = None


class Explanation(BaseModel):
    text: str
    source: Literal["groq", "deterministic"]
    model: str | None = None
    notice: str | None = None
    tools_used: list[str] = Field(default_factory=list)


class ChatAnswer(BaseModel):
    answer: str
    source: Literal["groq", "deterministic"]
    model: str | None = None
    notice: str | None = None
    tools_used: list[str] = Field(default_factory=list)
