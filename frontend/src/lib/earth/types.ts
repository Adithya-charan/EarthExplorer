/** Types for the Earth Explorer API (mirrors backend/app/geo/schemas.py). */

export type FeatureClass =
  | "city"
  | "country"
  | "state_province"
  | "continent"
  | "mountain_range"
  | "mountain_peak"
  | "river"
  | "lake"
  | "ocean_sea"
  | "desert"
  | "forest"
  | "island"
  | "landmark"
  | "region"
  | "coordinate"
  | "other";

export type GeometryType = "Point" | "LineString" | "MultiLineString" | "Polygon" | "MultiPolygon";
export type PointKind = "user_supplied" | "provider_point" | "label_point" | "representative_point" | "line_midpoint";
export type Provider = "natural_earth" | "openstreetmap" | "user" | "builtin";
export type ResolveStatus = "resolved" | "ambiguous" | "not_found" | "invalid" | "error";
export type Severity = "info" | "warning" | "error";

export interface BBox {
  west: number;
  south: number;
  /** Unwrapped: greater than 180 when the box crosses the antimeridian. */
  east: number;
  north: number;
  crosses_antimeridian: boolean;
}

export interface Context {
  country: string | null;
  country_code: string | null;
  admin1: string | null;
  admin2: string | null;
  locality: string | null;
  label: string | null;
  source_note: string | null;
}

export interface SourceInfo {
  provider: Provider;
  provider_name: string;
  dataset: string | null;
  source_id: string | null;
  scale: string | null;
  license: string;
  attribution: string;
  url: string | null;
}

export interface PointInfo {
  latitude: number;
  longitude: number;
  kind: PointKind;
  note: string;
}

export interface GeometryInfo {
  available: boolean;
  type: GeometryType | null;
  quality: "not_applicable" | "generalized" | "unavailable" | "provider_reported";
  generalization: string | null;
  simplify_tolerance_deg: number | null;
  vertex_count: number | null;
  crosses_antimeridian: boolean;
  area_km2: number | null;
  length_km: number | null;
  note: string | null;
}

export interface Validation {
  status: "validated" | "validated_with_limits" | "user_supplied_unverified";
  checks: string[];
  limitations: string[];
}

export interface Fact {
  key: string;
  label: string;
  value: string | number;
  unit: string | null;
  source: string;
}

export interface Candidate {
  id: string;
  name: string;
  display_name: string;
  feature_class: FeatureClass;
  class_label: string;
  shape_hint: "point" | "line" | "area";
  context: Context;
  latitude: number;
  longitude: number;
  position_kind: PointKind;
  provider: Provider;
  provider_name: string;
  provider_importance: number | null;
  bbox: BBox | null;
  also_matched: string[];
  note: string | null;
}

export interface GeoJSONGeometry {
  type: string;
  coordinates?: unknown;
  geometries?: GeoJSONGeometry[];
}

export interface ResolvedLocation {
  id: string;
  name: string;
  display_name: string;
  query: string | null;
  feature_class: FeatureClass;
  class_label: string;
  geometry_type: GeometryType;
  context: Context;
  point: PointInfo;
  bbox: BBox | null;
  geometry: GeoJSONGeometry | null;
  geometry_info: GeometryInfo;
  source: SourceInfo;
  validation: Validation;
  facts: Fact[];
  also_matched: string[];
  resolution: "user_selected" | "only_match" | "coordinates" | "by_id";
}

export interface Message {
  code: string;
  severity: Severity;
  text: string;
}

export interface ResolveItemInput {
  ref: string;
  query?: string;
  candidate_id?: string;
  coordinates?: { lat: number; lon: number; label?: string };
}

export interface ResolveItemResult {
  ref: string;
  status: ResolveStatus;
  query: string | null;
  resolved: ResolvedLocation | null;
  candidates: Candidate[];
  messages: Message[];
}

export interface ResolveResponse {
  results: ResolveItemResult[];
  online_geocoder: "used" | "disabled" | "unavailable";
  all_resolved: boolean;
}

export interface GeocodeResponse {
  query: string;
  candidates: Candidate[];
  sources: Record<string, string>;
  messages: Message[];
  attributions: string[];
}

// ------------------------------------------------------------------------------ preferences
export type VisualFormat = "2d" | "3d" | "both";
export type DetailLevel = "basic" | "intermediate" | "advanced";
export type StyleName = "satellite" | "atlas" | "scientific" | "cinematic" | "dark" | "light" | "custom";
export type ViewpointPreset =
  | "earth"
  | "asia"
  | "europe"
  | "africa"
  | "north_america"
  | "south_america"
  | "australia"
  | "antarctica";
export type Projection2D = "auto" | "mercator" | "equal_earth";
/** What the 2D view is drawn with once the backend has decided. */
export type ResolvedProjection2D = "mercator" | "equal_earth" | "polar_north" | "polar_south";

export interface Viewpoint {
  mode: "auto" | "preset" | "region";
  preset?: ViewpointPreset | null;
  region_location_id?: string | null;
}

export interface CustomStyle {
  ocean: string;
  land: string;
  border: string;
  label: string;
  accent: string;
}

export interface LabelSettings {
  location_names: boolean;
  region_names: boolean;
  coordinates: boolean;
  feature_names: boolean;
  custom: Record<string, string>;
}

export interface EffectSettings {
  day_night: boolean;
  atmosphere: boolean;
  terrain_shading: boolean;
  borders: boolean;
  pins: boolean;
  connect_lines: boolean;
  info_panels: boolean;
}

export interface VisualizationPreferences {
  format: VisualFormat;
  viewpoint: Viewpoint;
  detail: DetailLevel;
  style: StyleName;
  custom_style?: CustomStyle | null;
  labels: LabelSettings;
  effects: EffectSettings;
  projection_2d: Projection2D;
}

export interface PreviewRequest {
  locations: { location_id: string }[];
  preferences: VisualizationPreferences;
  language?: string;
}

export interface ConfirmRequest extends PreviewRequest {
  confirmation_token: string;
  confirmed: boolean;
}

export interface SummaryLocation {
  index: number;
  id: string;
  name: string;
  display_name: string;
  context_label: string | null;
  country: string | null;
  class_label: string;
  feature_class: FeatureClass;
  latitude: number;
  longitude: number;
  coordinates_text: string;
  geometry_type: GeometryType;
  geometry_quality: string;
  point_kind: PointKind;
  source: string;
  data_status: string;
}

export interface Leg {
  from_index: number;
  to_index: number;
  distance_km: number;
  initial_bearing_deg: number;
  crosses_antimeridian: boolean;
}

export interface Camera {
  mode: "auto" | "preset" | "region";
  description: string;
  bbox: BBox | null;
  center: { lat: number; lon: number };
  zoom_hint: number | null;
  max_zoom: number;
  framing_note: string;
}

export interface AttributionItem {
  id: string;
  text: string;
  url: string | null;
  kind: "verified_data" | "generalized_data" | "imagery" | "computed" | "software";
  note: string | null;
}

export interface QualityItem {
  category: "source_data" | "generalized" | "illustrative" | "unavailable";
  text: string;
}

export interface PreviewResponse {
  question: string;
  summary: {
    locations: SummaryLocation[];
    format: VisualFormat;
    viewpoint: string;
    detail: DetailLevel;
    style: StyleName;
    labels: Record<string, unknown>;
    effects: Record<string, boolean>;
    projection_2d: ResolvedProjection2D;
    legs: Leg[];
  };
  camera: Camera;
  warnings: Message[];
  attributions: AttributionItem[];
  data_quality: QualityItem[];
  confirmation_token: string;
  can_confirm: boolean;
}

export interface GeoJSONFeatureCollection {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    id?: string | number;
    geometry: GeoJSONGeometry;
    properties: Record<string, unknown>;
  }>;
}

export interface GeneratedVisualization {
  id: string;
  generated_at: string;
  confirmed_token: string;
  preferences: VisualizationPreferences;
  locations: ResolvedLocation[];
  connections: GeoJSONFeatureCollection;
  legs: Leg[];
  camera: Camera;
  warnings: Message[];
  attributions: AttributionItem[];
  notes: string[];
}

export interface ElevationResult {
  available: boolean;
  latitude: number;
  longitude: number;
  elevation_m: number | null;
  zoom: number | null;
  approx_resolution_m: number | null;
  tile: { z: number; x: number; y: number } | null;
  source: string;
  attribution: string;
  notes: string[];
}

export interface TerrainDescriptor {
  type: "raster-dem";
  encoding: "terrarium";
  tiles: string[];
  tile_size: number;
  max_zoom: number;
  attribution: string;
  attribution_url: string;
  notes: string[];
}
