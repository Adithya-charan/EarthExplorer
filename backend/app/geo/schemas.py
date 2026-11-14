"""Pydantic models for the Earth Explorer API."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FeatureClass = Literal[
    "city",
    "country",
    "state_province",
    "continent",
    "mountain_range",
    "mountain_peak",
    "river",
    "lake",
    "ocean_sea",
    "desert",
    "forest",
    "island",
    "landmark",
    "region",
    "coordinate",
    "other",
]
GeometryType = Literal["Point", "LineString", "MultiLineString", "Polygon", "MultiPolygon"]
ShapeHint = Literal["point", "line", "area"]
PointKind = Literal["user_supplied", "provider_point", "label_point", "representative_point", "line_midpoint"]
Provider = Literal["natural_earth", "openstreetmap", "user", "builtin"]
ResolveStatus = Literal["resolved", "ambiguous", "not_found", "invalid", "error"]
Severity = Literal["info", "warning", "error"]

CLASS_LABELS: dict[str, str] = {
    "city": "City or town",
    "country": "Country",
    "state_province": "State, province or region",
    "continent": "Continent",
    "mountain_range": "Mountain range",
    "mountain_peak": "Mountain or peak",
    "river": "River",
    "lake": "Lake",
    "ocean_sea": "Ocean, sea or bay",
    "desert": "Desert",
    "forest": "Forest",
    "island": "Island",
    "landmark": "Landmark or place of interest",
    "region": "Geographic region",
    "coordinate": "Custom coordinates",
    "other": "Other feature",
}
SHAPE_BY_CLASS: dict[str, ShapeHint] = {
    "country": "area",
    "state_province": "area",
    "continent": "area",
    "mountain_range": "area",
    "lake": "area",
    "ocean_sea": "area",
    "desert": "area",
    "forest": "area",
    "island": "area",
    "region": "area",
    "river": "line",
}


class BBox(BaseModel):
    """A bounding box in WGS84 degrees.

    When ``crosses_antimeridian`` is true the box spans the 180° meridian: ``east`` is then *unwrapped*
    (greater than 180, e.g. west=176.8, east=181.7 for Fiji) so ``west <= east`` always holds and the
    width is ``east - west``.
    """

    west: float = Field(ge=-180, le=180)
    south: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=540)
    north: float = Field(ge=-90, le=90)
    crosses_antimeridian: bool = False

    @model_validator(mode="after")
    def _ordered(self) -> "BBox":
        if self.south > self.north:
            raise ValueError("south must not exceed north")
        if self.east < self.west:
            raise ValueError("east must not be less than west (use an unwrapped east across the antimeridian)")
        if self.east - self.west > 360.000001:
            raise ValueError("a bounding box cannot be wider than 360 degrees")
        return self


class Context(BaseModel):
    """Administrative / geographic context. Fields are None when the source does not provide them."""

    country: str | None = None
    country_code: str | None = None
    admin1: str | None = None
    admin2: str | None = None
    locality: str | None = None
    label: str | None = None
    source_note: str | None = None


class SourceInfo(BaseModel):
    provider: Provider
    provider_name: str
    dataset: str | None = None
    source_id: str | None = None
    scale: str | None = None
    license: str
    attribution: str
    url: str | None = None


class PointInfo(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    kind: PointKind
    note: str


class GeometryInfo(BaseModel):
    available: bool
    type: GeometryType | None = None
    quality: Literal["not_applicable", "generalized", "unavailable", "provider_reported"] = "not_applicable"
    generalization: str | None = None
    simplify_tolerance_deg: float | None = None
    vertex_count: int | None = None
    crosses_antimeridian: bool = False
    area_km2: float | None = None
    length_km: float | None = None
    note: str | None = None


class Validation(BaseModel):
    status: Literal["validated", "validated_with_limits", "user_supplied_unverified"]
    checks: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class Fact(BaseModel):
    """One piece of provider-reported information. Only facts the source actually provided are listed."""

    key: str
    label: str
    value: str | float | int
    unit: str | None = None
    source: str


class Candidate(BaseModel):
    id: str
    name: str
    display_name: str
    feature_class: FeatureClass
    class_label: str
    shape_hint: ShapeHint
    context: Context
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    position_kind: PointKind
    provider: Provider
    provider_name: str
    provider_importance: float | None = None
    bbox: BBox | None = None
    also_matched: list[str] = Field(default_factory=list)
    note: str | None = None


class ResolvedLocation(BaseModel):
    """A location whose coordinates / geometry come from a named source. Missing fields stay ``None``."""

    id: str
    name: str
    display_name: str
    query: str | None = None
    feature_class: FeatureClass
    class_label: str
    geometry_type: GeometryType
    context: Context
    point: PointInfo
    bbox: BBox | None = None
    geometry: dict[str, Any] | None = None
    geometry_info: GeometryInfo
    source: SourceInfo
    validation: Validation
    facts: list[Fact] = Field(default_factory=list)
    also_matched: list[str] = Field(default_factory=list)
    resolution: Literal["user_selected", "only_match", "coordinates", "by_id"] = "by_id"


class Message(BaseModel):
    code: str
    severity: Severity = "info"
    text: str


# ----------------------------------------------------------------------------------------- requests
class CoordinateInput(BaseModel):
    lat: float
    lon: float
    label: str | None = Field(default=None, max_length=120)


class ResolveItem(BaseModel):
    """Exactly one of ``query`` (a place name or coordinates), ``candidate_id`` or ``coordinates``."""

    ref: str = Field(min_length=1, max_length=64)
    query: str | None = Field(default=None, max_length=200)
    candidate_id: str | None = Field(default=None, max_length=128)
    coordinates: CoordinateInput | None = None

    @field_validator("query")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = re.sub(r"\s+", " ", v).strip()
        return v or None

    @model_validator(mode="after")
    def _one_input(self) -> "ResolveItem":
        given = [x for x in (self.query, self.candidate_id, self.coordinates) if x is not None]
        if len(given) != 1:
            raise ValueError("give exactly one of query, candidate_id or coordinates")
        return self


class ResolveRequest(BaseModel):
    items: list[ResolveItem] = Field(min_length=1, max_length=25)
    online: bool = True
    language: str = Field(default="en", pattern=r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?$")


class ResolveItemResult(BaseModel):
    ref: str
    status: ResolveStatus
    query: str | None = None
    resolved: ResolvedLocation | None = None
    candidates: list[Candidate] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)


class ResolveResponse(BaseModel):
    results: list[ResolveItemResult]
    online_geocoder: Literal["used", "disabled", "unavailable"]
    all_resolved: bool


class GeocodeResponse(BaseModel):
    query: str
    candidates: list[Candidate]
    sources: dict[str, str]
    messages: list[Message] = Field(default_factory=list)
    attributions: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------------------- visualization
VisualFormat = Literal["2d", "3d", "both"]
DetailLevel = Literal["basic", "intermediate", "advanced"]
StyleName = Literal["satellite", "atlas", "scientific", "cinematic", "dark", "light", "custom"]
ViewpointPreset = Literal[
    "earth", "asia", "europe", "africa", "north_america", "south_america", "australia", "antarctica"
]
HexColor = str


class Viewpoint(BaseModel):
    mode: Literal["auto", "preset", "region"] = "auto"
    preset: ViewpointPreset | None = None
    region_location_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _consistent(self) -> "Viewpoint":
        if self.mode == "preset" and not self.preset:
            raise ValueError("viewpoint.preset is required when mode is 'preset'")
        if self.mode == "region" and not self.region_location_id:
            raise ValueError("viewpoint.region_location_id is required when mode is 'region'")
        return self


class CustomStyle(BaseModel):
    ocean: HexColor = "#0b1d2e"
    land: HexColor = "#1c2b36"
    border: HexColor = "#8aa0b3"
    label: HexColor = "#e8eef3"
    accent: HexColor = "#ffb000"

    @field_validator("ocean", "land", "border", "label", "accent")
    @classmethod
    def _hex(cls, v: str) -> str:
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", v):
            raise ValueError("colours must be 6-digit hex values such as #1a2b3c")
        return v.lower()


class LabelSettings(BaseModel):
    location_names: bool = True
    region_names: bool = True
    coordinates: bool = False
    feature_names: bool = False
    custom: dict[str, str] = Field(default_factory=dict)

    @field_validator("custom")
    @classmethod
    def _custom(cls, v: dict[str, str]) -> dict[str, str]:
        if len(v) > 50:
            raise ValueError("at most 50 custom labels")
        out: dict[str, str] = {}
        for key, text in v.items():
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                out[key[:128]] = text[:80]
        return out


class EffectSettings(BaseModel):
    day_night: bool = False
    atmosphere: bool = True
    terrain_shading: bool = True
    borders: bool = True
    pins: bool = True
    connect_lines: bool = False
    info_panels: bool = True


class VisualizationPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: VisualFormat = "3d"
    viewpoint: Viewpoint = Field(default_factory=Viewpoint)
    detail: DetailLevel = "intermediate"
    style: StyleName = "satellite"
    custom_style: CustomStyle | None = None
    labels: LabelSettings = Field(default_factory=LabelSettings)
    effects: EffectSettings = Field(default_factory=EffectSettings)
    projection_2d: Literal["auto", "mercator", "equal_earth"] = "auto"


class LocationRef(BaseModel):
    """Only an id: the server looks the place up itself, so client-supplied coordinates are refused, not ignored."""

    model_config = ConfigDict(extra="forbid")

    location_id: str = Field(min_length=3, max_length=128)


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locations: list[LocationRef] = Field(min_length=1, max_length=25)
    preferences: VisualizationPreferences = Field(default_factory=VisualizationPreferences)
    language: str = Field(default="en", pattern=r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?$")


class ConfirmRequest(PreviewRequest):
    confirmation_token: str = Field(min_length=64, max_length=64)
    confirmed: bool = False


class SummaryLocation(BaseModel):
    index: int
    id: str
    name: str
    display_name: str
    context_label: str | None
    country: str | None
    class_label: str
    feature_class: FeatureClass
    latitude: float
    longitude: float
    coordinates_text: str
    geometry_type: GeometryType
    geometry_quality: str
    point_kind: PointKind
    source: str
    data_status: str


class Leg(BaseModel):
    from_index: int
    to_index: int
    distance_km: float
    initial_bearing_deg: float
    crosses_antimeridian: bool


class Camera(BaseModel):
    mode: Literal["auto", "preset", "region"]
    description: str
    bbox: BBox | None
    center: dict[str, float]
    zoom_hint: float | None = None
    max_zoom: float = 16
    framing_note: str


class AttributionItem(BaseModel):
    id: str
    text: str
    url: str | None = None
    kind: Literal["verified_data", "generalized_data", "imagery", "computed", "software"]
    note: str | None = None


class PreviewSummary(BaseModel):
    locations: list[SummaryLocation]
    format: VisualFormat
    viewpoint: str
    detail: DetailLevel
    style: StyleName
    labels: dict[str, Any]
    effects: dict[str, bool]
    projection_2d: str
    legs: list[Leg]


class QualityItem(BaseModel):
    """One line of the data-quality statement shown before confirmation.

    ``source_data``  coordinates / outlines taken from a named source (not independently verified)
    ``generalized``  outlines simplified for cartography; fine for display, not for measurement
    ``illustrative`` visual elements that are computed or decorative, not observations
    ``unavailable``  data that was requested but does not exist for this feature
    """

    category: Literal["source_data", "generalized", "illustrative", "unavailable"]
    text: str


class PreviewResponse(BaseModel):
    question: str
    summary: PreviewSummary
    camera: Camera
    warnings: list[Message]
    attributions: list[AttributionItem]
    data_quality: list[QualityItem]
    confirmation_token: str
    can_confirm: bool


class GeneratedVisualization(BaseModel):
    id: str
    generated_at: str
    confirmed_token: str
    preferences: VisualizationPreferences
    locations: list[ResolvedLocation]
    connections: dict[str, Any]
    legs: list[Leg]
    camera: Camera
    warnings: list[Message]
    attributions: list[AttributionItem]
    notes: list[str]
