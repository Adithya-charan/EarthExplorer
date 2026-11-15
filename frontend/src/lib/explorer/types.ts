export type Outcome = "change_detected" | "no_clear_change" | "insufficient_data";
export type Quality = "good" | "fair" | "poor";
export type BBox = [number, number, number, number]; // west, south, east, north

export interface DatasetVariable {
  key: string;
  label: string;
  class: number | number[];
  primary: boolean;
}

export interface DatasetInfo {
  id: string;
  name: string;
  description: string;
  is_synthetic: boolean;
  simulated_label: string | null;
  source: string;
  product: string;
  format: string;
  crs: string;
  resolution_m: number;
  temporal_resolution: "monthly" | "yearly" | "irregular";
  bbox: BBox;
  coverage: { start: string; end: string };
  observation_count: number;
  usable_count: number;
  classes: Record<string, string>;
  real_dataset_targets: { name: string; coverage: string; resolution_m: number }[];
  issues: string[];
  variables: DatasetVariable[];
  designation: string;
  public_label: string;
  provenance: Record<string, unknown>;
}

export interface LocationOut {
  id: string;
  name: string;
  display_name: string;
  lat: number;
  lon: number;
  kind: string;
  source: string;
  bbox: BBox | null;
  zoom_altitude_m: number;
  level: string;
  hierarchy: string[];
  boundary_status: string | null;
}

export interface BoundaryOut {
  location_id: string;
  name: string;
  level: string;
  status: string;
  authoritative: boolean;
  note: string;
  source: string;
  license: string;
  source_id: string | null;
  bbox: BBox | null;
  geometry: { type: string; coordinates: unknown } | null;
  area_km2: number | null;
  area_is_approximate: boolean;
}

export interface PeriodCheck {
  requested: { start_year: number; end_year: number };
  supported: { start: string; end: string } | null;
  effective: { start_year: number; end_year: number } | null;
  status: "ok" | "clipped" | "outside" | "too_short";
  messages: string[];
}

export interface LatestObservation {
  label: string;
  date: string;
  location: string;
  source: string;
  spatial_resolution_m: number;
  quality: Quality;
  valid_fraction: number;
  temporal_resolution: string;
  historical_coverage: { start: string; end: string };
  is_synthetic: boolean;
  simulated_label: string | null;
  note: string;
}

export interface Insufficient {
  code: string;
  reason: string;
  missing: string[];
  available_dates: string[];
  suggested_period: { start_year: number; end_year: number } | null;
}

export interface SessionResponse {
  status: "ready" | "no_dataset" | "not_found" | "ambiguous" | "period_unsupported";
  message: string;
  location: LocationOut | null;
  alternatives: LocationOut[];
  examples: string[];
  datasets: DatasetInfo[];
  dataset: DatasetInfo | null;
  period: PeriodCheck | null;
  latest: LatestObservation | null;
  insufficient: Insufficient | null;
  nearby_datasets: DatasetInfo[];
  is_synthetic: boolean;
  simulated_label: string | null;
}

export interface Hotspot {
  id: string;
  rank: number;
  kind: "loss" | "gain";
  area_ha: number;
  geometry_area_ha: number;
  share_of_change_pct: number;
  centroid: { lon: number; lat: number };
  bbox: BBox;
  region: string;
  description: string;
}

export interface ProgressionPoint {
  year: number;
  water_ha: number;
  cumulative_loss_ha: number;
  cumulative_gain_ha: number;
  observations: number;
}

export interface ObservationRef {
  date: string;
  quality: Quality;
  valid_fraction: number;
  layer_url: string;
}

export interface ChangeSummary {
  outcome: Outcome;
  headline: string;
  analysis_id: string | null;
  dataset: DatasetInfo | null;
  location_name: string | null;
  period: PeriodCheck | null;
  first_observation: ObservationRef | null;
  last_observation: ObservationRef | null;
  observations_used: Record<string, unknown>;
  areas: Record<string, number | null>;
  most_affected: { region: string; kind: string; area_ha: number; description: string; hotspot_id: string; centroid: { lon: number; lat: number } } | null;
  hotspots: Hotspot[];
  progression: ProgressionPoint[];
  trend: { direction: string; slope_ha_per_year: number; p_value: number; method: string; years: number } | null;
  quality: Record<string, number>;
  confidence: "high" | "medium" | "low" | null;
  confidence_reasons: string[];
  limitations: string[];
  what_was_analysed: string;
  insufficient: Insufficient | null;
  thresholds: Record<string, number>;
  bbox: BBox | null;
  layers: Record<string, string>;
  variable: DatasetVariable | null;
  is_synthetic: boolean;
  simulated_label: string | null;
}

export interface ObservationInfo {
  date: string;
  quality: Quality;
  valid_fraction: number;
  usable: boolean;
  water_share: number | null;
  sensor: string | null;
}

export interface Explanation {
  text: string;
  source: "groq" | "deterministic";
  model: string | null;
  notice: string | null;
  tools_used: string[];
}

export interface ChatAnswer {
  answer: string;
  source: "groq" | "deterministic";
  model: string | null;
  notice: string | null;
  tools_used: string[];
}

export interface HotspotCollection {
  type: "FeatureCollection";
  features: { type: "Feature"; id?: string; geometry: { type: string; coordinates: unknown }; properties: { id: string; rank: number; kind: "loss" | "gain"; area_ha: number; region: string; description: string } }[];
}

export type MapMode = "latest" | "history" | "beforeafter" | "swipe" | "difference" | "hotspots";
